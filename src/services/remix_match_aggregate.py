"""
Remix / mix-cut hit aggregation: per source video, treat (remix_time, source_time) as 2D points,
extract dominant lines t_src ≈ k * t_remix + b with RANSAC, then split inlier runs by remix gaps.

Pure helpers (no FAISS / ONNX imports).
"""
from __future__ import annotations

import math
import os
import random
from typing import Dict, List, Optional, Sequence, Tuple

from src.domain.remix_search_hit import RemixSearchHit


def normalize_match_path(path: str) -> str:
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))
    except OSError:
        return os.path.normcase(os.path.normpath(str(path)))


def _default_remix_chain_gap_sec(sample_fps: float) -> float:
    fps = max(0.01, float(sample_fps))
    return 2.5 / fps


def _group_points_by_path(
    points: Sequence[Tuple[str, float, float, float]],
) -> Dict[str, List[Tuple[str, float, float, float]]]:
    """path_norm -> rows (video_path, src_t, score, ref_t)."""
    buckets: Dict[str, List[Tuple[str, float, float, float]]] = {}
    for video_path, src_t, score, ref_t in points:
        key = normalize_match_path(str(video_path))
        buckets.setdefault(key, []).append((str(video_path), float(src_t), float(score), float(ref_t)))
    return buckets


def _dedupe_best_score_per_ref(rows: List[Tuple[str, float, float, float]]) -> List[Tuple[float, float, float, str]]:
    """One sample per remix time per path: keep highest CLIP score. -> (ref, src, score, path)."""
    best: Dict[float, Tuple[float, float, str]] = {}
    for path, src_t, score, ref_t in rows:
        r = float(ref_t)
        sc = float(score)
        t = (float(src_t), sc, str(path))
        prev = best.get(r)
        if prev is None or sc > prev[1]:
            best[r] = t
    out: List[Tuple[float, float, float, str]] = []
    for r in sorted(best):
        src_t, score, p = best[r]
        out.append((r, src_t, score, p))
    return out


def _inliers_for_line(
    pts: List[Tuple[float, float, float, str]],
    k: float,
    b: float,
    residual_sec: float,
) -> List[Tuple[float, float, float, str]]:
    out: List[Tuple[float, float, float, str]] = []
    for ref, src, score, path in pts:
        if abs(float(src) - (k * float(ref) + b)) <= float(residual_sec):
            out.append((ref, src, score, path))
    return out


def _ols_line(pts: List[Tuple[float, float, float, str]]) -> Optional[Tuple[float, float]]:
    if len(pts) < 2:
        return None
    rs = [p[0] for p in pts]
    ss = [p[1] for p in pts]
    n = len(rs)
    mr = sum(rs) / n
    ms = sum(ss) / n
    var = sum((r - mr) ** 2 for r in rs)
    if var < 1e-12:
        return None
    k = sum((r - mr) * (s - ms) for r, s in zip(rs, ss)) / var
    b = ms - k * mr
    return k, b


def _ransac_best_line(
    pts: List[Tuple[float, float, float, str]],
    *,
    residual_sec: float,
    speed_min: float,
    speed_max: float,
    iterations: int,
    rng: random.Random,
    min_inliers: int,
) -> Optional[Tuple[float, float, List[Tuple[float, float, float, str]]]]:
    if len(pts) < min_inliers:
        return None
    n = len(pts)
    best_inliers: List[Tuple[float, float, float, str]] = []
    best_k, best_b = 0.0, 0.0

    for _ in range(max(1, int(iterations))):
        i = rng.randrange(n)
        j = rng.randrange(n)
        if i == j:
            continue
        ref_i, src_i, _, _ = pts[i]
        ref_j, src_j, _, _ = pts[j]
        dr = ref_j - ref_i
        if abs(dr) < 1e-6:
            continue
        k = (src_j - src_i) / dr
        if k < speed_min or k > speed_max or not math.isfinite(k):
            continue
        b = src_i - k * ref_i
        inl = _inliers_for_line(pts, k, b, residual_sec)
        refined = _ols_line(inl)
        if refined is not None:
            k2, b2 = refined
            if k2 >= speed_min and k2 <= speed_max and math.isfinite(k2):
                k, b = k2, b2
                inl = _inliers_for_line(pts, k, b, residual_sec)
        if len(inl) > len(best_inliers):
            best_inliers = inl
            best_k, best_b = k, b

    if len(best_inliers) < min_inliers:
        return None
    return best_k, best_b, best_inliers


def _split_by_remix_gap(
    inliers: List[Tuple[float, float, float, str]],
    remix_chain_gap_sec: float,
) -> List[List[Tuple[float, float, float, str]]]:
    if not inliers:
        return []
    s = sorted(inliers, key=lambda x: x[0])
    chains: List[List[Tuple[float, float, float, str]]] = [[s[0]]]
    for item in s[1:]:
        prev_ref = chains[-1][-1][0]
        if float(item[0]) - float(prev_ref) > float(remix_chain_gap_sec):
            chains.append([item])
        else:
            chains[-1].append(item)
    return chains


def _segment_from_chain(
    chain: List[Tuple[float, float, float, str]],
    *,
    k: float,
    min_segment_sec: float,
    min_points: int,
    sample_fps: float,
) -> Optional[RemixSearchHit]:
    if len(chain) < min_points:
        return None
    path = chain[0][3]
    refs = [c[0] for c in chain]
    srcs = [c[1] for c in chain]
    scores = [c[2] for c in chain]
    remix_start = min(refs)
    remix_end = max(refs)
    src_start = min(srcs)
    src_end = max(srcs)
    span = src_end - src_start
    if span < float(min_segment_sec):
        return None
    mean_score = float(sum(scores) / max(1, len(scores)))
    remix_span = max(1e-6, float(remix_end - remix_start))
    expected_hits = max(1.0, remix_span * max(0.05, float(sample_fps)))
    density = float(len(chain)) / expected_hits
    match_confidence = max(0.0, min(1.0, density * mean_score))
    end_display = src_end if span > 1e-3 else src_start + 0.25
    return RemixSearchHit(
        float(src_start),
        max(float(src_start) + 0.05, float(end_display)),
        mean_score,
        path,
        remix_start_sec=float(remix_start),
        remix_end_sec=float(remix_end),
        speed_k=float(k),
        match_confidence=float(match_confidence),
    )


def aggregate_match_points_to_segments(
    points: Sequence[Tuple[str, float, float, float]],
    *,
    merge_gap_sec: float,
    min_segment_sec: float,
    min_points: int = 2,
    sample_fps: float = 1.0,
    remix_cluster_gap_sec: Optional[float] = None,
    speed_min: float = 0.25,
    speed_max: float = 4.0,
    ransac_iterations: int = 384,
    random_seed: Optional[int] = None,
) -> List[RemixSearchHit]:
    """
    ``merge_gap_sec`` — max |src - (k*ref + b)| for RANSAC inliers (line residual, seconds).

    ``remix_cluster_gap_sec`` — max gap on the remix axis between consecutive inliers to stay
    in one segment chain (defaults to ``2.5 / sample_fps``).

    ``speed_min`` / ``speed_max`` — bounds on k in t_src ≈ k * t_remix + b.
    """
    if merge_gap_sec <= 0 or min_segment_sec < 0:
        raise ValueError("invalid merge_gap_sec or min_segment_sec")
    if min_points < 1:
        raise ValueError("invalid min_points")
    if speed_min <= 0 or speed_max < speed_min:
        raise ValueError("invalid speed bounds")

    chain_gap = (
        float(remix_cluster_gap_sec)
        if remix_cluster_gap_sec is not None
        else _default_remix_chain_gap_sec(sample_fps)
    )
    if chain_gap <= 0:
        raise ValueError("invalid remix_cluster_gap_sec")

    flat = [
        (str(video_path), float(src_t), float(score), float(ref_t))
        for video_path, src_t, score, ref_t in points
    ]
    if not flat:
        return []

    rng = random.Random(random_seed) if random_seed is not None else random.Random()

    hits: List[RemixSearchHit] = []
    for _, rows in sorted(_group_points_by_path(flat).items(), key=lambda kv: kv[0]):
        pts = _dedupe_best_score_per_ref(list(rows))
        if len(pts) < min_points:
            continue
        pool = list(pts)
        iters = max(ransac_iterations, 32)
        while len(pool) >= min_points:
            fit = _ransac_best_line(
                pool,
                residual_sec=float(merge_gap_sec),
                speed_min=float(speed_min),
                speed_max=float(speed_max),
                iterations=iters,
                rng=rng,
                min_inliers=min_points,
            )
            if fit is None:
                break
            k, b, inliers = fit
            inlier_refs = {round(float(p[0]), 5) for p in inliers}
            pool = [p for p in pool if round(float(p[0]), 5) not in inlier_refs]
            for chain in _split_by_remix_gap(inliers, chain_gap):
                seg = _segment_from_chain(
                    chain,
                    k=k,
                    min_segment_sec=min_segment_sec,
                    min_points=min_points,
                    sample_fps=float(sample_fps),
                )
                if seg is not None:
                    hits.append(seg)

    hits.sort(
        key=lambda h: (float(h.remix_start_sec), normalize_match_path(h.video_path), float(h.start_sec))
    )
    return hits
