from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Union


@dataclass(frozen=True)
class RemoteSearchHit:
    """One ranked match from remote (link) vector search."""

    title: str
    time_sec: float
    score: float
    source_link: str


RowLike = Union[RemoteSearchHit, Mapping[str, Any]]


def coerce_remote_search_hit(row: RowLike) -> RemoteSearchHit:
    if isinstance(row, RemoteSearchHit):
        return row
    if isinstance(row, Mapping):
        return RemoteSearchHit(
            title=str(row.get("title", "") or ""),
            time_sec=float(row.get("time_sec", 0.0) or 0.0),
            score=float(row.get("score", 0.0) or 0.0),
            source_link=str(row.get("source_link", "") or ""),
        )
    raise TypeError(f"Expected RemoteSearchHit or mapping, got {type(row).__name__}")


def coerce_remote_search_hits(rows: Iterable[RowLike]) -> List[RemoteSearchHit]:
    return [coerce_remote_search_hit(r) for r in rows]
