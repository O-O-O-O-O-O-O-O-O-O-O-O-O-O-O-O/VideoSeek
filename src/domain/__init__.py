from src.domain.remote_search_hit import RemoteSearchHit, coerce_remote_search_hit, coerce_remote_search_hits
from src.domain.remix_search_hit import RemixSearchHit, coerce_remix_search_hit
from src.domain.search_hit import SearchHit, coerce_search_hit, coerce_search_hits

__all__ = [
    "SearchHit",
    "coerce_search_hit",
    "coerce_search_hits",
    "RemixSearchHit",
    "coerce_remix_search_hit",
    "RemoteSearchHit",
    "coerce_remote_search_hit",
    "coerce_remote_search_hits",
]
