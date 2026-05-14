"""Disk cache for remix-video CLIP embeddings (same file + FPS + model → skip re-encoding)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile

from typing import Any, Dict, Optional, Tuple

import numpy as np

from src.app.config import get_data_storage_paths, load_config
from src.app.logging_utils import get_logger
from src.storage.config_store import get_active_model_profile

logger = get_logger("remix_embedding_cache")

_CACHE_VERSION = 2


def _norm_mix_path(mix_video_path: str) -> str:
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(mix_video_path))))
    except OSError:
        return os.path.normcase(os.path.normpath(os.fspath(mix_video_path)))


def _mix_stat(mix_video_path: str) -> Tuple[float, int]:
    st = os.stat(mix_video_path)
    return float(st.st_mtime), int(getattr(st, "st_size", 0) or 0)


def _cache_key_dict(
    mix_video_path: str,
    *,
    sample_fps: float,
    model_profile_id: str,
    index_dim: int,
) -> Dict[str, Any]:
    """Stable cache identity: path + size + fps + model + dim (mtime excluded: it can drift on Windows/cloud sync when only reading the file)."""
    _mtime, size = _mix_stat(mix_video_path)
    return {
        "v": _CACHE_VERSION,
        "path": _norm_mix_path(mix_video_path),
        "size": int(size),
        "sample_fps": round(float(sample_fps), 6),
        "model_profile_id": str(model_profile_id or "").strip(),
        "index_dim": int(index_dim),
    }


def get_remix_embed_cache_dir(config: Optional[dict] = None) -> str:
    """Root for remix CLIP caches: ``<data_dir>/cache/remix_embed`` (``data_dir`` = dirname(meta.json)).

    Resolved from the active data tree (``data_root`` → ``data``), not from any stale ``preview_cache_dir``
    string that might still exist in an older config file.
    """
    cfg = dict(config or load_config())
    paths = get_data_storage_paths(config=cfg)
    data_dir = str(paths.get("data_dir") or "").strip()
    if data_dir:
        base = os.path.join(data_dir, "cache")
    else:
        base = str(paths.get("preview_cache_dir", "") or "").strip()
    if not base:
        from src.utils import get_app_data_dir

        base = os.path.join(get_app_data_dir(), "cache")
    sub = os.path.join(base, "remix_embed")
    os.makedirs(sub, exist_ok=True)
    return sub


def _cache_file_path(config: dict, key: Dict[str, Any]) -> str:
    raw = json.dumps(key, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    sub = get_remix_embed_cache_dir(config)
    return os.path.join(sub, f"{digest}.npz")


def try_load_remix_embedding_cache(
    mix_video_path: str,
    *,
    sample_fps: float,
    model_profile_id: str,
    index_dim: int,
    config: Optional[dict] = None,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    cfg = dict(config or load_config())
    key = _cache_key_dict(
        mix_video_path,
        sample_fps=sample_fps,
        model_profile_id=model_profile_id,
        index_dim=index_dim,
    )
    path = _cache_file_path(cfg, key)
    if not os.path.isfile(path):
        logger.info("Remix embed cache miss: no file digest=%s", os.path.basename(path)[:16])
        return None
    try:
        _, cur_size = _mix_stat(mix_video_path)
        if int(cur_size) != int(key["size"]):
            logger.info("Remix embed cache miss: size changed %s -> %s", key["size"], cur_size)
            return None
        with np.load(path, allow_pickle=False) as data:
            vectors = np.ascontiguousarray(np.array(data["vectors"], dtype=np.float32, copy=True))
            ref_times = np.ascontiguousarray(np.array(data["ref_times"], dtype=np.float64, copy=True))
            if vectors.ndim != 2 or vectors.shape[1] != index_dim:
                logger.info("Remix embed cache miss: bad shape %s", getattr(vectors, "shape", None))
                return None
            if ref_times.ndim != 1 or ref_times.shape[0] != vectors.shape[0]:
                return None
            if int(np.asarray(data["cache_version"]).reshape(-1)[0]) != _CACHE_VERSION:
                return None
            if abs(float(np.asarray(data["sample_fps"]).reshape(-1)[0]) - key["sample_fps"]) > 1e-9:
                return None
            if int(np.asarray(data["index_dim"]).reshape(-1)[0]) != int(index_dim):
                return None
            mid = data["model_profile_id"]
            if isinstance(mid, np.ndarray) and mid.dtype == np.uint8:
                mid_s = mid.tobytes().decode("utf-8")
            else:
                mid_s = str(mid)
            if mid_s != key["model_profile_id"]:
                return None
            stored_size = int(np.asarray(data["mix_size"]).reshape(-1)[0])
            if stored_size != int(key["size"]):
                logger.info("Remix embed cache miss: npz size %s != key %s", stored_size, key["size"])
                return None
    except Exception as exc:
        logger.warning("Remix embed cache load failed: %s", exc)
        return None
    logger.info("Remix embed cache hit: frames=%s path=%s", vectors.shape[0], mix_video_path)
    return vectors, ref_times


def save_remix_embedding_cache(
    mix_video_path: str,
    *,
    sample_fps: float,
    model_profile_id: str,
    index_dim: int,
    vectors: np.ndarray,
    ref_times: np.ndarray,
    config: Optional[dict] = None,
) -> None:
    if vectors.size == 0:
        return
    cfg = dict(config or load_config())
    key = _cache_key_dict(
        mix_video_path,
        sample_fps=sample_fps,
        model_profile_id=model_profile_id,
        index_dim=index_dim,
    )
    path = _cache_file_path(cfg, key)
    v = np.asarray(vectors, dtype=np.float32)
    t = np.asarray(ref_times, dtype=np.float64)
    if v.shape[0] != t.shape[0]:
        return
    staging_dir = tempfile.mkdtemp(prefix="remix_embed_")
    staging = os.path.join(staging_dir, "payload.npz")
    try:
        np.savez_compressed(
            staging,
            cache_version=np.int32(_CACHE_VERSION),
            vectors=v,
            ref_times=t,
            sample_fps=np.float64(key["sample_fps"]),
            mix_mtime=np.float64(_mix_stat(mix_video_path)[0]),
            mix_size=np.int64(key["size"]),
            index_dim=np.int32(index_dim),
            model_profile_id=np.frombuffer(key["model_profile_id"].encode("utf-8"), dtype=np.uint8),
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.move(staging, path)
    except Exception as exc:
        logger.warning("Remix embed cache save failed: %s", exc)
    finally:
        try:
            shutil.rmtree(staging_dir, ignore_errors=True)
        except Exception:
            pass


def active_profile_id_for_cache(config: Optional[dict] = None) -> str:
    try:
        profile = get_active_model_profile(config=config)
        return str(profile.get("id", "") or "").strip()
    except Exception:
        return ""
