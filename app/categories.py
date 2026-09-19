import threading
import time

from app import igdb, tmdb

# slug -> label, kind, and the filter that defines it
CATEGORIES = {
    # films
    "horror-films": {
        "label": "Horror", "kind": "movie", "group": "Films",
        "params": {"with_genres": "27", "sort_by": "popularity.desc", "vote_count.gte": "300"},
    },
    "comedy-films": {
        "label": "Comedy", "kind": "movie", "group": "Films",
        "params": {"with_genres": "35", "sort_by": "popularity.desc", "vote_count.gte": "300"},
    },
    "scifi-films": {
        "label": "Sci-Fi", "kind": "movie", "group": "Films",
        "params": {"with_genres": "878", "sort_by": "popularity.desc", "vote_count.gte": "300"},
    },
    "animation-films": {
        "label": "Animation", "kind": "movie", "group": "Films",
        "params": {"with_genres": "16", "sort_by": "popularity.desc", "vote_count.gte": "300"},
    },
    "documentaries": {
        "label": "Documentaries", "kind": "movie", "group": "Films",
        "params": {"with_genres": "99", "sort_by": "popularity.desc", "vote_count.gte": "100"},
    },
    "top-films": {
        "label": "Highest Rated", "kind": "movie", "group": "Films",
        "params": {"sort_by": "vote_average.desc", "vote_count.gte": "3000"},
    },
    # shows
    "comedy-shows": {
        "label": "Comedy", "kind": "tv", "group": "Shows",
        "params": {"with_genres": "35", "sort_by": "popularity.desc", "vote_count.gte": "150"},
    },
    "drama-shows": {
        "label": "Drama", "kind": "tv", "group": "Shows",
        "params": {"with_genres": "18", "sort_by": "popularity.desc", "vote_count.gte": "150"},
    },
    "crime-shows": {
        "label": "Crime", "kind": "tv", "group": "Shows",
        "params": {"with_genres": "80", "sort_by": "popularity.desc", "vote_count.gte": "150"},
    },
    "reality-shows": {
        "label": "Reality", "kind": "tv", "group": "Shows",
        "params": {"with_genres": "10764", "sort_by": "popularity.desc", "vote_count.gte": "20"},
    },
    "complete-series": {
        "label": "Complete Series", "kind": "tv", "group": "Shows",
        "params": {"with_status": "3", "sort_by": "vote_average.desc", "vote_count.gte": "800"},
    },
    "top-shows": {
        "label": "Highest Rated", "kind": "tv", "group": "Shows",
        "params": {"sort_by": "vote_average.desc", "vote_count.gte": "1200"},
    },
    # games
    "rpg-games": {
        "label": "RPG", "kind": "game", "group": "Games",
        "where": "genres = (12)",
    },
    "shooter-games": {
        "label": "Shooters", "kind": "game", "group": "Games",
        "where": "genres = (5)",
    },
    "story-games": {
        "label": "Story-Driven", "kind": "game", "group": "Games",
        "where": "game_modes = (1) & themes = (31)",
    },
    "horror-games": {
        "label": "Horror", "kind": "game", "group": "Games",
        "where": "themes = (19)",
    },
    "indie-games": {
        "label": "Indie", "kind": "game", "group": "Games",
        "where": "genres = (32)",
    },
    "openworld-games": {
        "label": "Open World", "kind": "game", "group": "Games",
        "where": "themes = (38)",
    },
}

GROUPS = ["Films", "Shows", "Games"]

_lock = threading.Lock()
_previews: dict = {"data": None, "at": 0.0}
PREVIEW_TTL = 6 * 60 * 60


def fetch(slug: str, page: int = 1) -> list[dict]:
    """Full result set for one category."""
    spec = CATEGORIES.get(slug)
    if spec is None:
        return []
    try:
        if spec["kind"] == "game":
            return igdb.discover(spec["where"], page=page)
        return tmdb.discover(spec["kind"], spec["params"], page=page)
    except Exception:
        return []


def previews() -> dict:
    """Four poster URLs per category, cached hard — this is a lot of API calls."""
    now = time.time()
    with _lock:
        if _previews["data"] is not None and now - _previews["at"] < PREVIEW_TTL:
            return _previews["data"]

    out = {}
    for slug in CATEGORIES:
        rows = fetch(slug, page=1)
        posters = [r["image_url"] for r in rows if r.get("image_url")][:4]
        out[slug] = posters

    with _lock:
        # only cache if most of it worked
        filled = sum(1 for v in out.values() if v)
        if filled >= len(CATEGORIES) * 0.7:
            _previews["data"] = out
            _previews["at"] = now
    return out
