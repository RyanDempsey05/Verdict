import threading
import time

from app import igdb, tmdb

TTL = 3600
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}


def _build() -> dict:
    out = {"movies": [], "shows": [], "games": []}
    try:
        out["movies"] = tmdb.trending("movie")
    except Exception:
        pass
    try:
        out["shows"] = tmdb.trending("tv")
    except Exception:
        pass
    try:
        out["games"] = igdb.popular()
    except Exception:
        pass
    return out


def get() -> dict:
    with _lock:
        now = time.time()
        if _cache["data"] is not None and now - _cache["at"] < TTL:
            return _cache["data"]
        data = _build()
        if all(data.values()):
            _cache["data"] = data
            _cache["at"] = now
        elif _cache["data"] is not None:
            merged = dict(_cache["data"])
            for k, v in data.items():
                if v:
                    merged[k] = v
            return merged
        return data
