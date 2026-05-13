from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

from src.domain.search_hit import SearchHit


@dataclass(frozen=True)
class RemixSearchHit:
    """Local remix match row: source time range + corresponding remix timeline range."""

    start_sec: float
    end_sec: float
    score: float
    video_path: str
    remix_start_sec: float
    remix_end_sec: float
    speed_k: float = 1.0
    match_confidence: float = 1.0

    def as_search_hit(self) -> SearchHit:
        return SearchHit(self.start_sec, self.end_sec, self.score, self.video_path)


RowLike = Union[RemixSearchHit, SearchHit]


def coerce_remix_search_hit(row: Any) -> RemixSearchHit:
    if isinstance(row, RemixSearchHit):
        return row
    if isinstance(row, SearchHit):
        return RemixSearchHit(
            row.start_sec,
            row.end_sec,
            row.score,
            row.video_path,
            remix_start_sec=float(row.start_sec),
            remix_end_sec=float(row.end_sec),
            speed_k=1.0,
            match_confidence=float(row.score),
        )
    raise TypeError(f"Expected RemixSearchHit or SearchHit, got {type(row).__name__}")
