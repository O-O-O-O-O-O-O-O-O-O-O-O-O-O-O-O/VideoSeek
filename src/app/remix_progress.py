"""Structured remix-match progress payloads for UI formatting."""

from __future__ import annotations

import os
import time

PREFIX = "remix_progress"


def build_progress_token(
    *,
    stage: str,
    video_name: str = "",
    done: int = 0,
    total: int = 0,
) -> str:
    name = os.path.basename(str(video_name or ""))
    return "|".join(
        [
            PREFIX,
            str(stage or "").strip().lower(),
            str(max(0, int(done))),
            str(max(0, int(total))),
            name,
        ]
    )


def parse_progress_token(text: str):
    raw = str(text or "").strip()
    if not raw.startswith(f"{PREFIX}|"):
        return None
    parts = raw.split("|")
    if len(parts) < 5:
        return None
    return {
        "stage": parts[1],
        "done": int(parts[2]) if parts[2].isdigit() else 0,
        "total": int(parts[3]) if parts[3].isdigit() else 0,
        "video_name": parts[4],
    }


def _count_label(done: int, total: int) -> str:
    if total > 0:
        return f"{done}/{total}"
    if done > 0:
        return str(done)
    return ""


def format_progress_text(text: str, texts: dict) -> str:
    payload = parse_progress_token(text)
    if not payload:
        legacy = str(text or "").strip()
        if legacy == "remix_progress_cache_hit":
            return texts.get("remix_progress_cache_hit", legacy)
        if legacy == "remix_progress_embed_done":
            return texts.get("remix_progress_embed_done", legacy)
        if legacy == "remix_progress_aggregate":
            return texts.get("remix_progress_aggregate", legacy)
        if legacy.startswith("remix_progress_frames:"):
            count = legacy.split(":", 1)[-1].strip()
            tpl = texts.get("remix_progress_embed_open", "{name}: embedded {count} frames")
            name = texts.get("remix_progress_unknown_video", "mix")
            return tpl.format(name=name, count=count)
        return legacy or texts.get("remix_progress", "")

    stage = payload["stage"]
    name = payload["video_name"] or texts.get("remix_progress_unknown_video", "mix")
    done = payload["done"]
    total = payload["total"]
    count = _count_label(done, total)

    if stage == "prepare":
        return texts.get("remix_progress_prepare", texts.get("remix_progress", ""))
    if stage == "cache_hit":
        return texts.get("remix_progress_cache_hit", texts.get("remix_progress", ""))
    if stage == "extract":
        key = "remix_progress_extract" if total > 0 else "remix_progress_extract_open"
        return texts.get(key, "{name}: extracting {count}").format(name=name, count=count or done)
    if stage == "embed":
        key = "remix_progress_embed" if total > 0 else "remix_progress_embed_open"
        return texts.get(key, "{name}: embedding {count}").format(name=name, count=count or done)
    if stage == "embed_done":
        return texts.get("remix_progress_embed_done", texts.get("remix_progress", ""))
    if stage == "search":
        key = "remix_progress_search" if total > 0 else "remix_progress_search_open"
        return texts.get(key, "{name}: searching library {count}").format(name=name, count=count or done)
    if stage == "aggregate":
        return texts.get("remix_progress_aggregate", texts.get("remix_progress", ""))

    return text


def compute_remix_percent(stage: str, done: int = 0, total: int = 0, *, cap: int = 99) -> int:
    bands = {
        "prepare": (0, 6),
        "cache_hit": (6, 14),
        "extract": (14, 44),
        "embed": (44, 74),
        "embed_done": (74, 78),
        "search": (78, 92),
        "aggregate": (92, cap),
    }
    lo, hi = bands.get(str(stage or "").lower(), (0, 50))
    if total > 0 and done > 0:
        ratio = min(1.0, float(done) / float(total))
        return int(max(0, min(cap, round(lo + (hi - lo) * ratio))))
    return int(max(0, min(cap, lo)))


class RemixProgressReporter:
    """Throttle remix-match progress emissions."""

    def __init__(
        self,
        callback,
        *,
        video_name: str,
        min_interval_sec: float = 0.35,
    ):
        self._callback = callback
        self._video_name = video_name
        self._min_interval = max(0.1, float(min_interval_sec))
        self._last_emit = 0.0
        self._last_stage = ""

    def emit(
        self,
        stage: str,
        done: int = 0,
        total: int = 0,
        *,
        force: bool = False,
        percent_cap: int = 99,
    ):
        if not callable(self._callback):
            return
        stage = str(stage or "").strip().lower()
        done = max(0, int(done))
        total = max(0, int(total))
        now = time.monotonic()
        if (
            not force
            and stage == self._last_stage
            and now - self._last_emit < self._min_interval
            and total > 0
            and done < total
            and done > 1
        ):
            return
        self._last_emit = now
        self._last_stage = stage
        token = build_progress_token(
            stage=stage,
            video_name=self._video_name,
            done=done,
            total=total,
        )
        percent = compute_remix_percent(stage, done, total, cap=percent_cap)
        self._callback(percent, token)
