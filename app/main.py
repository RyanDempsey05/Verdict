from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from slowapi.errors import RateLimitExceeded

from fastapi.staticfiles import StaticFiles

from fastapi.staticfiles import StaticFiles

from app.limiter import limiter

from app import auth, friends, items, ratings, views

app = FastAPI()
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return PlainTextResponse("Too many requests. Slow down.", status_code=429)

app.include_router(auth.router)
app.include_router(items.router, prefix="/api")
app.include_router(ratings.router)
app.include_router(friends.router)
app.include_router(views.router)

import os
os.makedirs("/media", exist_ok=True)
app.mount("/media", StaticFiles(directory="/media"), name="media")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

import os
os.makedirs("/media", exist_ok=True)
app.mount("/media", StaticFiles(directory="/media"), name="media")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.on_event("startup")
def _make_og_card() -> None:
    from app import discover as _discover, ogcard as _ogcard

    if os.path.exists(_ogcard.OUT_PATH):
        return
    posters = []
    try:
        data = _discover.trending()
        for key in ("movies", "shows", "games"):
            posters += [r["image_url"] for r in data.get(key, []) if r.get("image_url")]
    except Exception:
        pass
    _ogcard.ensure(posters)
