"""
Match a mix-edit (remix) video against indexed library frames: per-frame embedding + FAISS,
then RANSAC line fit in (remix time, source time) per file.
"""
from __future__ import annotations

import os
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.core.clip_embedding import get_clip_embeddings_batch, prepare_inference_runtime
from src.core.extract_frames import stream_frames_with_ffmpeg_fixed_fps
from src.domain.remix_search_hit import RemixSearchHit
from src.services.remix_embedding_cache import (
    active_profile_id_for_cache,
    save_remix_embedding_cache,
    try_load_remix_embedding_cache,
)
from src.services.remix_match_aggregate import aggregate_match_points_to_segments, normalize_match_path
from src.services.search_service import load_search_assets, _check_asset_profile_compatibility, _FRAME_ASSET_INFO

logger = get_logger("remix_match_service")


def _raw_points_from_normalized_vectors(
    vectors: np.ndarray,
    ref_times: np.ndarray,
    *,
    search_index,
    video_paths,
    timestamps,
    top_k: int,
    score_threshold: float,
    path_allowed,
) -> List[Tuple[str, float, float, float]]:
    """vectors: (N, D) float32, will be L2-normalized in place for FAISS.

    For each remix frame, keep the **best-scoring** hit per distinct source file among the top-K
    neighbors (so downstream RANSAC can resolve (t_remix, t_src) lines).
    """
    raw_points: List[Tuple[str, float, float, float]] = []
    vv = np.asarray(vectors, dtype=np.float32, order="C")
    if vv.ndim != 2 or vv.shape[0] == 0:
        return raw_points
    tt = np.asarray(ref_times, dtype=np.float64).reshape(-1)
    if tt.shape[0] != vv.shape[0]:
        raise RuntimeError("ref_times length mismatch vs embedding rows.")
    import faiss

    faiss.normalize_L2(vv)
    distances, indices = search_index.search(vv, top_k)
    for i in range(vv.shape[0]):
        row_scores = distances[i]
        row_idx = indices[i]
        ref_t = float(tt[i])
        per_path_best: dict[str, Tuple[float, float, str]] = {}
        for rank in range(top_k):
            idx = int(row_idx[rank])
            if idx < 0 or idx >= len(video_paths):
                continue
            score = float(row_scores[rank])
            if score < score_threshold:
                break
            path_s = str(video_paths[idx])
            if not path_allowed(path_s):
                continue
            src_t = float(timestamps[idx])
            key = normalize_match_path(path_s)
            prev = per_path_best.get(key)
            if prev is None or score > prev[0]:
                per_path_best[key] = (score, src_t, path_s)
        for _, (score, src_t, path_s) in per_path_best.items():
            raw_points.append((path_s, src_t, score, ref_t))
    return raw_points


def run_remix_match(
    mix_video_path: str,
    *,
    scope_paths: Optional[Sequence[str]] = None,
    sample_fps: float = 2.0,
    score_threshold: float = 0.26,
    merge_gap_sec: float = 2.5,
    min_segment_sec: float = 1.5,
    remix_cluster_gap_sec: Optional[float] = None,
    faiss_top_k: int = 48,
    speed_min: float = 0.25,
    speed_max: float = 4.0,
    ransac_iterations: int = 384,
    min_line_points: int = 2,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> List[RemixSearchHit]:
    """
    scope_paths: if None or empty, search the full global frame index. Otherwise only hits whose
    indexed video path normalizes to one of these paths are kept.
    """
    mix_video_path = str(mix_video_path).strip()
    if not mix_video_path or not os.path.isfile(mix_video_path):
        raise FileNotFoundError("Mix video path is missing or not a file.")
    if float(speed_min) <= 0 or float(speed_max) <= float(speed_min):
        raise ValueError("speed_max must be greater than speed_min (both positive).")
    if int(min_line_points) < 2:
        raise ValueError("min_line_points must be at least 2.")
    if int(ransac_iterations) < 8:
        raise ValueError("ransac_iterations must be at least 8.")

    prepare_inference_runtime()
    config = load_config()

    search_index, timestamps, video_paths = load_search_assets(config=config)
    if search_index is None:
        raise RuntimeError("Global frame index is missing. Update the index from the library page first.")
    _check_asset_profile_compatibility(config, _FRAME_ASSET_INFO, asset_label="frame")

    scope_keys: Optional[set[str]] = None
    if scope_paths is not None:
        raw = [str(p).strip() for p in scope_paths if str(p).strip()]
        if not raw:
            raise ValueError("Restricted scope is enabled but no library paths are selected.")
        scope_keys = {normalize_match_path(p) for p in raw}

    def path_allowed(path: str) -> bool:
        if scope_keys is None:
            return True
        return normalize_match_path(path) in scope_keys

    embedding_batch_size = max(1, int(config.get("embedding_batch_size", 16) or 16))
    top_k = max(1, min(int(faiss_top_k), int(search_index.ntotal)))

    index_dim = int(getattr(search_index, "d", 0))
    if index_dim <= 0:
        raise RuntimeError("Invalid search index dimension.")

    profile_id = active_profile_id_for_cache(config=config)

    cached = try_load_remix_embedding_cache(
        mix_video_path,
        sample_fps=float(sample_fps),
        model_profile_id=profile_id,
        index_dim=index_dim,
        config=config,
    )

    raw_points: List[Tuple[str, float, float, float]] = []
    processed = 0

    if cached is not None:
        vectors, ref_times = cached
        processed = int(vectors.shape[0])
        if progress_callback is not None:
            progress_callback(0, "remix_progress_cache_hit")
        raw_points = _raw_points_from_normalized_vectors(
            vectors,
            ref_times,
            search_index=search_index,
            video_paths=video_paths,
            timestamps=timestamps,
            top_k=top_k,
            score_threshold=float(score_threshold),
            path_allowed=path_allowed,
        )
    else:
        frame_buf = []
        ref_buf: List[float] = []
        embed_chunks: List[np.ndarray] = []
        time_chunks: List[np.ndarray] = []

        def flush_batch() -> None:
            nonlocal frame_buf, ref_buf, raw_points, processed, embed_chunks, time_chunks
            if not frame_buf:
                return
            vectors = get_clip_embeddings_batch(frame_buf)
            vectors = np.asarray(vectors, dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[1] != index_dim:
                raise RuntimeError(
                    f"Embedding dimension mismatch (got {vectors.shape[1]}, index expects {index_dim})."
                )
            ref_arr = np.asarray(ref_buf, dtype=np.float64)
            raw_points.extend(
                _raw_points_from_normalized_vectors(
                    vectors,
                    ref_arr,
                    search_index=search_index,
                    video_paths=video_paths,
                    timestamps=timestamps,
                    top_k=top_k,
                    score_threshold=float(score_threshold),
                    path_allowed=path_allowed,
                )
            )
            embed_chunks.append(vectors.copy())
            time_chunks.append(ref_arr.copy())
            processed += len(frame_buf)
            frame_buf = []
            ref_buf = []

        for frame, ref_t in stream_frames_with_ffmpeg_fixed_fps(mix_video_path, float(sample_fps)):
            if should_stop is not None and should_stop():
                raise InterruptedError("Remix match stopped by user.")
            frame_buf.append(frame)
            ref_buf.append(float(ref_t))
            if len(frame_buf) >= embedding_batch_size:
                flush_batch()
                if progress_callback is not None:
                    progress_callback(0, f"remix_progress_frames:{processed}")

        flush_batch()
        if progress_callback is not None:
            progress_callback(50, "remix_progress_embed_done")

        if embed_chunks:
            all_vectors = np.vstack(embed_chunks)
            all_times = np.concatenate(time_chunks)
            try:
                save_remix_embedding_cache(
                    mix_video_path,
                    sample_fps=float(sample_fps),
                    model_profile_id=profile_id,
                    index_dim=index_dim,
                    vectors=all_vectors,
                    ref_times=all_times,
                    config=config,
                )
            except Exception as exc:
                logger.debug("Remix embed cache save skipped: %s", exc)

    if progress_callback is not None:
        progress_callback(99, "remix_progress_aggregate")

    segments = aggregate_match_points_to_segments(
        raw_points,
        merge_gap_sec=float(merge_gap_sec),
        min_segment_sec=float(min_segment_sec),
        min_points=int(min_line_points),
        sample_fps=float(sample_fps),
        remix_cluster_gap_sec=remix_cluster_gap_sec,
        speed_min=float(speed_min),
        speed_max=float(speed_max),
        ransac_iterations=int(ransac_iterations),
    )
    logger.info(
        "Remix match finished: mix=%s frames=%s raw_hits=%s segments=%s scope_restricted=%s cache=%s",
        mix_video_path,
        processed,
        len(raw_points),
        len(segments),
        scope_keys is not None,
        cached is not None,
    )
    return segments
