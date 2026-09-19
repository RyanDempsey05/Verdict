import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import card, discover, igdb, mail, media, tmdb
from app.auth import _set_session, get_current_user, require_user
from app.db import get_db
from app.friends import friend_ids
from app.limiter import limiter
from app.models import Friendship, Item, ListEntry, PasswordReset, Rating, User
from app.limiter import limiter
from app.security import SESSION_COOKIE, hash_password, verify_password

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

SORTS = {
    "recent": ("Recently rated", Rating.updated_at.desc()),
    "oldest": ("Oldest first", Rating.updated_at.asc()),
    "score_desc": ("Highest rated", Rating.score.desc(), Rating.updated_at.desc()),
    "score_asc": ("Lowest rated", Rating.score.asc(), Rating.updated_at.desc()),
    "title": ("Title A-Z", Item.title.asc()),
    "year_desc": ("Newest release", Item.year.desc().nullslast()),
    "year_asc": ("Oldest release", Item.year.asc().nullslast()),
}


def _order(sort: str):
    return SORTS.get(sort, SORTS["recent"])[1:]



@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: User | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse(url="/feed", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, user: User | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse(url="/feed", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"user": None})


@router.post("/ui/register")
@limiter.limit("4/hour")
def ui_register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if len(password) < 12:
        return templates.TemplateResponse(
            request, "register.html",
            {"user": None, "error": "Password must be at least 12 characters"},
            status_code=400,
        )

    new_user = User(
        username=username.strip(),
        email=email.strip().lower(),
        password_hash=hash_password(password),
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            request, "register.html",
            {"user": None, "error": "Username or email already taken"},
            status_code=400,
        )

    invite = request.cookies.get("pending_invite")
    landed_on = "/"
    if invite and re.fullmatch(r"[A-Za-z0-9_-]{1,16}", invite):
        inviter = db.scalar(select(User).where(User.invite_code == invite))
        if inviter is not None and inviter.id != new_user.id:
            _link_friendship(db, new_user, inviter)
            landed_on = f"/u/{inviter.username}"

    response = RedirectResponse(url=landed_on, status_code=303)
    _set_session(response, new_user.id)
    response.delete_cookie(
        "pending_invite", path="/", secure=True, httponly=True, samesite="lax"
    )
    return response


@router.post("/ui/login")
@limiter.limit("8/minute")
def ui_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    found = db.scalar(select(User).where(User.email == email.strip().lower()))
    if found is None or not verify_password(found.password_hash, password):
        return templates.TemplateResponse(
            request, "login.html",
            {"user": None, "error": "Invalid email or password"},
            status_code=401,
        )

    invite = request.cookies.get("pending_invite")
    landed_on = "/"
    if invite and re.fullmatch(r"[A-Za-z0-9_-]{1,16}", invite):
        inviter = db.scalar(select(User).where(User.invite_code == invite))
        if inviter is not None and inviter.id != found.id:
            _link_friendship(db, found, inviter)
            landed_on = f"/u/{inviter.username}"

    response = RedirectResponse(url=landed_on, status_code=303)
    _set_session(response, found.id)
    response.delete_cookie(
        "pending_invite", path="/", secure=True, httponly=True, samesite="lax"
    )
    return response


@router.get("/feed", response_class=HTMLResponse)
def feed_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    ids = friend_ids(db, user.id)
    rows = []
    if ids:
        rows = db.execute(
            select(
                Rating.score, Rating.review, User.username,
                Item.title, Item.year, Item.image_url, Item.type,
            )
            .join(User, User.id == Rating.user_id)
            .join(Item, Item.id == Rating.item_id)
            .where(Rating.user_id.in_(ids))
            .order_by(Rating.updated_at.desc())
            .limit(50)
        ).all()

    pending = db.scalar(
        select(Friendship).where(
            Friendship.addressee_id == user.id, Friendship.status == "pending"
        )
    )

    return templates.TemplateResponse(
        request, "feed.html",
        {"user": user, "feed": rows, "has_requests": pending is not None},
    )


@router.get("/friends", response_class=HTMLResponse)
def friends_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    incoming = db.execute(
        select(Friendship.id, User.username)
        .join(User, User.id == Friendship.requester_id)
        .where(Friendship.addressee_id == user.id, Friendship.status == "pending")
    ).all()

    outgoing = db.execute(
        select(Friendship.id, User.username)
        .join(User, User.id == Friendship.addressee_id)
        .where(Friendship.requester_id == user.id, Friendship.status == "pending")
    ).all()

    ids = friend_ids(db, user.id)
    friends = []
    if ids:
        friends = db.execute(
            select(User.username).where(User.id.in_(ids)).order_by(User.username)
        ).all()

    return templates.TemplateResponse(
        request, "friends.html",
        {"user": user, "incoming": incoming, "outgoing": outgoing, "friends": friends},
    )


@router.post("/ui/friends/request")
def ui_friend_request(
    friend_handle: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    target = db.scalar(select(User).where(User.username == friend_handle.strip()))
    if target is None or target.id == user.id:
        return RedirectResponse(url="/friends", status_code=303)

    existing = db.scalar(
        select(Friendship).where(
            or_(
                (Friendship.requester_id == user.id) & (Friendship.addressee_id == target.id),
                (Friendship.requester_id == target.id) & (Friendship.addressee_id == user.id),
            )
        )
    )
    if existing is not None:
        if existing.requester_id == target.id and existing.status == "pending":
            existing.status = "accepted"
            db.commit()
        return RedirectResponse(url="/friends", status_code=303)

    db.add(Friendship(requester_id=user.id, addressee_id=target.id, status="pending"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse(url="/friends", status_code=303)


@router.post("/ui/friends/{friendship_id}/accept")
def ui_accept(
    friendship_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    friendship = db.scalar(
        select(Friendship).where(
            Friendship.id == friendship_id,
            Friendship.addressee_id == user.id,
            Friendship.status == "pending",
        )
    )
    if friendship is not None:
        friendship.status = "accepted"
        db.commit()
    return RedirectResponse(url="/friends", status_code=303)


@router.post("/ui/friends/{friendship_id}/reject")
def ui_reject(
    friendship_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    friendship = db.scalar(
        select(Friendship).where(
            Friendship.id == friendship_id,
            Friendship.addressee_id == user.id,
            Friendship.status == "pending",
        )
    )
    if friendship is not None:
        db.delete(friendship)
        db.commit()
    return RedirectResponse(url="/friends", status_code=303)


@router.post("/ui/friends/{username}/remove")
def ui_unfriend(
    username: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    target = db.scalar(select(User).where(User.username == username.strip()))
    if target is not None:
        friendship = db.scalar(
            select(Friendship).where(
                Friendship.status == "accepted",
                or_(
                    (Friendship.requester_id == user.id) & (Friendship.addressee_id == target.id),
                    (Friendship.requester_id == target.id) & (Friendship.addressee_id == user.id),
                ),
            )
        )
        if friendship is not None:
            db.delete(friendship)
            db.commit()
    return RedirectResponse(url="/friends", status_code=303)


@router.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str = "",
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    results = []
    if q.strip():
        term = q[:100]
        try:
            results.extend(tmdb.search(term))
        except Exception:
            pass
        try:
            results.extend(igdb.search(term))
        except Exception:
            pass

    mine = {}
    if user is not None:
        rows = db.execute(
            select(Item.source, Item.source_id, Rating.score)
            .join(Rating, Rating.item_id == Item.id)
            .where(Rating.user_id == user.id)
        ).all()
        mine = {(r.source, r.source_id): float(r.score) for r in rows}

    return templates.TemplateResponse(
        request, "search.html",
        {"user": user, "q": q, "results": results, "mine": mine},
    )


def _safe_next(raw: str | None) -> str:
    if not raw:
        return "/me"
    if not raw.startswith("/") or raw.startswith("//"):
        return "/me"
    return raw[:200]


@router.post("/rate")
def ui_rate(
    request: Request,
    media_type: str = Form(...),
    source_id: str = Form(...),
    score: float = Form(...),
    review: str | None = Form(None),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    dest = _safe_next(request.headers.get("referer", "").split("verdictapp.app", 1)[-1] or None)
    dest = dest.split("#", 1)[0]
    anchor = re.sub(r"[^A-Za-z0-9_-]", "", f"{media_type}-{source_id}")
    if anchor:
        dest = f"{dest}#i-{anchor}"

    if score < 0.5 or score > 5 or (score * 2) % 1 != 0:
        return RedirectResponse(url=dest, status_code=303)

    review = (review or "").strip()[:2000] or None

    source = "igdb" if media_type == "game" else "tmdb"

    item = db.scalar(
        select(Item).where(Item.source == source, Item.source_id == source_id)
    )
    if item is None:
        if source == "igdb":
            data = igdb.fetch_one(source_id)
        else:
            data = tmdb.fetch_one(media_type, source_id)
        if data is None:
            return RedirectResponse(url=dest, status_code=303)
        item = Item(**data)
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            item = db.scalar(
                select(Item).where(Item.source == source, Item.source_id == source_id)
            )

    existing = db.scalar(
        select(Rating).where(Rating.user_id == user.id, Rating.item_id == item.id)
    )
    if existing is not None:
        existing.score = score
        existing.review = review
    else:
        db.add(Rating(user_id=user.id, item_id=item.id, score=score, review=review))
    db.commit()

    return RedirectResponse(url=dest, status_code=303)


@router.get("/me", response_class=HTMLResponse)
def my_ratings_page(
    request: Request,
    type: str = "all",
    sort: str = "recent",
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    if type not in ("all", "movie", "tv", "game"):
        type = "all"
    if sort not in SORTS:
        sort = "recent"

    counts_rows = db.execute(
        select(Item.type, func.count(Rating.id))
        .join(Item, Item.id == Rating.item_id)
        .where(Rating.user_id == user.id)
        .group_by(Item.type)
    ).all()
    counts = {t: c for t, c in counts_rows}
    counts["all"] = sum(counts.values())

    q = (
        select(
            Rating.id.label("rating_id"), Rating.score, Rating.review,
            Item.title, Item.year, Item.image_url, Item.type,
        )
        .join(Item, Item.id == Rating.item_id)
        .where(Rating.user_id == user.id)
    )
    if type != "all":
        q = q.where(Item.type == type)

    rows = db.execute(q.order_by(*_order(sort))).all()

    return templates.TemplateResponse(
        request, "me.html",
        {"user": user, "ratings": rows, "active": type,
         "counts": counts, "sort": sort, "sorts": SORTS},
    )


@router.post("/ratings/{rating_id}/delete")
def ui_delete_rating(
    rating_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    rating = db.scalar(
        select(Rating).where(Rating.id == rating_id, Rating.user_id == user.id)
    )
    if rating is not None:
        db.delete(rating)
        db.commit()
    return RedirectResponse(url="/me", status_code=303)


@router.post("/ui/logout")
def ui_logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/ui/logout")
def ui_logout_get():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/u/{username}", response_class=HTMLResponse)
def profile_page(
    request: Request,
    username: str,
    type: str = "all",
    sort: str = "recent",
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    if type not in ("all", "movie", "tv", "game"):
        type = "all"
    if sort not in SORTS:
        sort = "recent"

    profile = db.scalar(select(User).where(User.username == username.strip()))
    if profile is None:
        raise HTTPException(status_code=404, detail="User not found")

    is_self = profile.id == user.id
    is_friend = is_self or profile.profile_public or profile.id in friend_ids(db, user.id)

    if not is_friend:
        return templates.TemplateResponse(
            request, "profile.html",
            {"user": user, "profile": profile, "is_friend": False, "is_self": False},
            status_code=403,
        )

    counts_rows = db.execute(
        select(Item.type, func.count(Rating.id))
        .join(Item, Item.id == Rating.item_id)
        .where(Rating.user_id == profile.id)
        .group_by(Item.type)
    ).all()
    counts = {t: c for t, c in counts_rows}
    counts["all"] = sum(counts.values())

    q = (
        select(
            Rating.score, Rating.review,
            Item.title, Item.year, Item.image_url, Item.type,
        )
        .join(Item, Item.id == Rating.item_id)
        .where(Rating.user_id == profile.id)
    )
    if type != "all":
        q = q.where(Item.type == type)

    rows = db.execute(q.order_by(*_order(sort))).all()

    return templates.TemplateResponse(
        request, "profile.html",
        {
            "user": user, "profile": profile,
            "is_friend": True, "is_self": is_self,
            "ratings": rows, "active": type, "counts": counts,
            "sort": sort, "sorts": SORTS,
            "lists": _lists_for(db, profile.id), "list_types": LIST_TYPES,
        },
    )


@router.get("/api/suggest")
def suggest(
    q: str = "",
    user: User = Depends(require_user),
):
    term = q.strip()[:100]
    if len(term) < 2:
        return {"results": []}

    results = []
    try:
        results.extend(tmdb.search(term, limit=6))
    except Exception:
        pass
    try:
        results.extend(igdb.search(term, limit=6))
    except Exception:
        pass
    return {"results": results}


@router.get("/", response_class=HTMLResponse)
def discover_page(
    request: Request,
    guest: int = 0,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None and not guest:
        return templates.TemplateResponse(request, "landing.html", {"user": None})

    data = discover.get()

    ratings_by_key = {}
    if user is not None:
        ids = friend_ids(db, user.id) + [user.id]
        rows = db.execute(
            select(Item.source, Item.source_id, Rating.score, User.username)
            .join(Rating, Rating.item_id == Item.id)
            .join(User, User.id == Rating.user_id)
            .where(Rating.user_id.in_(ids))
        ).all()
        for r in rows:
            ratings_by_key.setdefault((r.source, r.source_id), []).append(
                {"username": r.username, "score": r.score}
            )

    return templates.TemplateResponse(
        request, "discover.html",
        {"user": user, "data": data, "ratings": ratings_by_key},
    )


BROWSE_LABELS = {"movie": "Films", "tv": "Shows", "game": "Games"}


@router.get("/browse/{kind}", response_class=HTMLResponse)
def browse_page(
    request: Request,
    kind: str,
    page: int = 1,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    if kind not in BROWSE_LABELS:
        raise HTTPException(status_code=404, detail="Not found")

    page = max(1, min(page, 100))

    rows = []
    try:
        if kind == "game":
            rows = igdb.browse(page)
        else:
            rows = tmdb.browse(kind, page)
    except Exception:
        pass

    ratings_by_key = {}
    ids = (friend_ids(db, user.id) + [user.id]) if user is not None else []
    if ids and rows:
        seen = db.execute(
            select(Item.source, Item.source_id, Rating.score, User.username)
            .join(Rating, Rating.item_id == Item.id)
            .join(User, User.id == Rating.user_id)
            .where(Rating.user_id.in_(ids))
        ).all()
        for r in seen:
            ratings_by_key.setdefault((r.source, r.source_id), []).append(
                {"username": r.username, "score": r.score}
            )

    return templates.TemplateResponse(
        request, "browse.html",
        {
            "user": user, "kind": kind, "label": BROWSE_LABELS[kind],
            "rows": rows, "page": page, "ratings": ratings_by_key,
        },
    )


RENAME_DAYS = 90


def _can_rename(u: User) -> tuple[bool, int]:
    if u.username_changed_at is None:
        return True, 0
    elapsed = datetime.now(timezone.utc) - u.username_changed_at
    left = RENAME_DAYS - elapsed.days
    return (left <= 0), max(0, left)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    user: User | None = Depends(get_current_user),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    ok, left = _can_rename(user)
    return templates.TemplateResponse(
        request, "settings.html",
        {"user": user, "can_rename": ok, "days_left": left},
    )


@router.post("/ui/settings/profile")
async def ui_settings_profile(
    bio: str = Form(""),
    avatar: UploadFile | None = File(None),
    backdrop: UploadFile | None = File(None),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    user.bio = bio.strip()[:280] or None

    for field, upload in (("avatar", avatar), ("backdrop", backdrop)):
        if upload is None or not upload.filename:
            continue
        raw = await upload.read(media.MAX_BYTES + 1)
        name = media.save_image(raw, field)
        if name:
            media.delete_image(getattr(user, field))
            setattr(user, field, name)

    db.commit()
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/ui/settings/username")
def ui_settings_username(
    request: Request,
    new_handle: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    ok, left = _can_rename(user)
    new = new_handle.strip()

    if not ok or not new or new == user.username:
        return RedirectResponse(url="/settings", status_code=303)

    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", new):
        return templates.TemplateResponse(
            request, "settings.html",
            {"user": user, "can_rename": ok, "days_left": left,
             "error": "Use 3-32 letters, numbers, dots, dashes or underscores."},
            status_code=400,
        )

    user.username = new
    user.username_changed_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            request, "settings.html",
            {"user": user, "can_rename": ok, "days_left": left,
             "error": "That name is taken."},
            status_code=400,
        )

    return RedirectResponse(url="/settings", status_code=303)


@router.post("/ui/settings/password")
@limiter.limit("6/hour")
def ui_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    ok, left = _can_rename(user)
    ctx = {"user": user, "can_rename": ok, "days_left": left}

    if not verify_password(user.password_hash, current_password):
        ctx["error"] = "Current password is incorrect."
        return templates.TemplateResponse(request, "settings.html", ctx, status_code=401)

    if len(new_password) < 12:
        ctx["error"] = "New password must be at least 12 characters."
        return templates.TemplateResponse(request, "settings.html", ctx, status_code=400)

    user.password_hash = hash_password(new_password)
    db.commit()

    response = RedirectResponse(url="/settings", status_code=303)
    _set_session(response, user.id)
    return response


@router.post("/ui/settings/privacy")
def ui_change_privacy(
    public: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    user.profile_public = public == "on"
    db.commit()
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/ui/settings/delete")
@limiter.limit("3/hour")
def ui_delete_account(
    request: Request,
    confirm_password: str = Form(...),
    confirm_text: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    ok, left = _can_rename(user)
    ctx = {"user": user, "can_rename": ok, "days_left": left}

    if not verify_password(user.password_hash, confirm_password):
        ctx["error"] = "Password is incorrect."
        return templates.TemplateResponse(request, "settings.html", ctx, status_code=401)

    if confirm_text.strip() != "DELETE":
        ctx["error"] = 'Type DELETE exactly to confirm.'
        return templates.TemplateResponse(request, "settings.html", ctx, status_code=400)

    media.delete_image(user.avatar)
    media.delete_image(user.backdrop)
    db.delete(user)
    db.commit()

    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


LIST_TYPES = {"movie": "Films", "tv": "Shows", "game": "Games"}


def _lists_for(db: Session, user_id: int) -> dict:
    rows = db.execute(
        select(
            ListEntry.type, ListEntry.position,
            Item.title, Item.year, Item.image_url,
        )
        .join(Item, Item.id == ListEntry.item_id)
        .where(ListEntry.user_id == user_id)
        .order_by(ListEntry.type, ListEntry.position)
    ).all()
    out = {k: [] for k in LIST_TYPES}
    for r in rows:
        if r.type in out:
            out[r.type].append(r)
    return out


@router.get("/lists", response_class=HTMLResponse)
def lists_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    rated = db.execute(
        select(Item.id, Item.title, Item.year, Item.type, Item.image_url)
        .join(Rating, Rating.item_id == Item.id)
        .where(Rating.user_id == user.id)
        .order_by(Item.title)
    ).all()

    options = {k: [] for k in LIST_TYPES}
    for r in rated:
        if r.type in options:
            options[r.type].append(r)

    current = {}
    rows = db.scalars(
        select(ListEntry).where(ListEntry.user_id == user.id)
    ).all()
    for e in rows:
        current[(e.type, e.position)] = e.item_id

    return templates.TemplateResponse(
        request, "lists.html",
        {"user": user, "options": options, "current": current,
         "types": LIST_TYPES, "slots": range(1, 6)},
    )


@router.post("/ui/lists/{kind}")
async def ui_save_list(
    kind: str,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if kind not in LIST_TYPES:
        raise HTTPException(status_code=404, detail="Not found")

    form = await request.form()

    owned = set(
        db.scalars(
            select(Item.id)
            .join(Rating, Rating.item_id == Item.id)
            .where(Rating.user_id == user.id, Item.type == kind)
        ).all()
    )

    picks = {}
    for pos in range(1, 6):
        raw = form.get(f"slot{pos}", "")
        if not raw:
            continue
        try:
            item_id = int(raw)
        except ValueError:
            continue
        if item_id not in owned:
            continue
        if item_id in picks.values():
            continue
        picks[pos] = item_id

    db.execute(
        delete(ListEntry).where(
            ListEntry.user_id == user.id, ListEntry.type == kind
        )
    )
    for pos, item_id in picks.items():
        db.add(
            ListEntry(user_id=user.id, item_id=item_id, type=kind, position=pos)
        )
    db.commit()

    return RedirectResponse(url="/lists", status_code=303)


@router.get("/item/{source}/{source_id}", response_class=HTMLResponse)
def item_page(
    request: Request,
    source: str,
    source_id: str,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if source not in ("tmdb", "igdb"):
        raise HTTPException(status_code=404, detail="Not found")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source_id):
        raise HTTPException(status_code=404, detail="Not found")

    cached = db.scalar(
        select(Item).where(Item.source == source, Item.source_id == source_id)
    )

    data = None
    try:
        if source == "igdb":
            data = igdb.details(source_id)
        else:
            kind = cached.type if cached else "movie"
            data = tmdb.details(kind, source_id)
            if data is None and not cached:
                data = tmdb.details("tv", source_id)
    except Exception:
        pass

    if data is None:
        if cached is None:
            raise HTTPException(status_code=404, detail="Not found")
        data = {
            "source": cached.source, "source_id": cached.source_id,
            "type": cached.type, "title": cached.title, "year": cached.year,
            "image_url": cached.image_url, "overview": None,
            "genres": [], "runtime": None, "extra": None,
        }

    mine = None
    friends_ratings = []
    avg = None

    if user is not None and cached is not None:
        mine = db.scalar(
            select(Rating).where(
                Rating.user_id == user.id, Rating.item_id == cached.id
            )
        )

        ids = friend_ids(db, user.id)
        if ids:
            friends_ratings = db.execute(
                select(User.username, Rating.score, Rating.review, User.avatar)
                .join(Rating, Rating.user_id == User.id)
                .where(Rating.item_id == cached.id, Rating.user_id.in_(ids))
                .order_by(Rating.score.desc())
            ).all()

        scores = [r.score for r in friends_ratings]
        if mine:
            scores.append(mine.score)
        if len(scores) > 1:
            avg = round(sum(scores) / len(scores), 1)

    return templates.TemplateResponse(
        request, "item.html",
        {
            "user": user, "item": data, "mine": mine,
            "friends_ratings": friends_ratings, "avg": avg,
        },
    )


@router.get("/card/{username}/{kind}.png")
@limiter.limit("20/minute")
def share_card(
    request: Request,
    username: str,
    kind: str,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if kind not in LIST_TYPES:
        raise HTTPException(status_code=404, detail="Not found")

    profile = db.scalar(select(User).where(User.username == username.strip()))
    if profile is None:
        raise HTTPException(status_code=404, detail="Not found")

    is_self = user is not None and user.id == profile.id
    visible = (
        is_self
        or profile.profile_public
        or (user is not None and profile.id in friend_ids(db, user.id))
    )
    if not visible:
        raise HTTPException(status_code=404, detail="Not found")

    rows = db.execute(
        select(Item.title, Item.year, Item.image_url, Rating.score)
        .join(ListEntry, ListEntry.item_id == Item.id)
        .outerjoin(
            Rating,
            (Rating.item_id == Item.id) & (Rating.user_id == profile.id),
        )
        .where(ListEntry.user_id == profile.id, ListEntry.type == kind)
        .order_by(ListEntry.position)
    ).all()

    entries = [
        {"title": r.title, "year": r.year, "image_url": r.image_url, "score": r.score}
        for r in rows
    ]

    avatar_path = None
    if profile.avatar and "/" not in profile.avatar and ".." not in profile.avatar:
        candidate = os.path.join("/media", profile.avatar)
        if os.path.exists(candidate):
            avatar_path = candidate

    png = card.build(kind, profile.username, entries, avatar_path)
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="verdict-{profile.username}-{kind}.png"',
            "Cache-Control": "no-cache, must-revalidate",
        },
    )


@router.get("/share/{username}/{kind}", response_class=HTMLResponse)
def share_page(
    request: Request,
    username: str,
    kind: str,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if kind not in LIST_TYPES:
        raise HTTPException(status_code=404, detail="Not found")

    profile = db.scalar(select(User).where(User.username == username.strip()))
    if profile is None:
        raise HTTPException(status_code=404, detail="Not found")

    is_self = user is not None and user.id == profile.id
    visible = (
        is_self
        or profile.profile_public
        or (user is not None and profile.id in friend_ids(db, user.id))
    )
    if not visible:
        raise HTTPException(status_code=404, detail="Not found")

    return templates.TemplateResponse(
        request, "share.html",
        {
            "user": user, "profile": profile, "kind": kind,
            "label": LIST_TYPES[kind], "is_self": is_self,
        },
    )


def _ensure_invite_code(db: Session, user: User) -> str:
    if user.invite_code:
        return user.invite_code
    for _ in range(6):
        code = secrets.token_urlsafe(6)[:8]
        exists = db.scalar(select(User.id).where(User.invite_code == code))
        if exists is None:
            user.invite_code = code
            db.commit()
            return code
    raise HTTPException(status_code=500, detail="Could not generate invite code")


@router.get("/i/{code}")
def invite_landing(
    code: str,
    response: Response,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", code):
        return RedirectResponse(url="/", status_code=303)

    inviter = db.scalar(select(User).where(User.invite_code == code))
    if inviter is None:
        return RedirectResponse(url="/", status_code=303)

    # already signed in: send the friend request straight away
    if user is not None:
        if user.id != inviter.id:
            _link_friendship(db, user, inviter)
        return RedirectResponse(url=f"/u/{inviter.username}", status_code=303)

    resp = RedirectResponse(url="/register", status_code=303)
    resp.set_cookie(
        "pending_invite",
        code,
        max_age=1800,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return resp


def _link_friendship(db: Session, a: User, b: User) -> None:
    """Create an accepted friendship between a and b, or accept a pending one."""
    existing = db.scalar(
        select(Friendship).where(
            or_(
                and_(Friendship.requester_id == a.id, Friendship.addressee_id == b.id),
                and_(Friendship.requester_id == b.id, Friendship.addressee_id == a.id),
            )
        )
    )
    if existing is not None:
        if existing.status == "pending":
            existing.status = "accepted"
            db.commit()
        return

    db.add(
        Friendship(requester_id=b.id, addressee_id=a.id, status="accepted")
    )
    db.commit()


@router.get("/invite", response_class=HTMLResponse)
def invite_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    code = _ensure_invite_code(db, user)
    return templates.TemplateResponse(
        request, "invite.html", {"user": user, "code": code}
    )


RESET_TTL_MINUTES = 60


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@router.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request, user: User | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "forgot.html", {"user": None})


@router.post("/ui/forgot", response_class=HTMLResponse)
@limiter.limit("5/hour")
def ui_forgot(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    found = db.scalar(select(User).where(User.email == email.strip().lower()))

    if found is not None:
        db.execute(
            delete(PasswordReset).where(
                PasswordReset.user_id == found.id, PasswordReset.used_at.is_(None)
            )
        )
        raw = secrets.token_urlsafe(32)
        db.add(
            PasswordReset(
                user_id=found.id,
                token_hash=_hash_token(raw),
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=RESET_TTL_MINUTES),
            )
        )
        db.commit()
        mail.send_password_reset(
            found.email, found.username, f"https://verdictapp.app/reset/{raw}"
        )

    # same response either way, so the form can't be used to discover accounts
    return templates.TemplateResponse(request, "forgot.html", {"user": None, "sent": True})


@router.get("/reset/{token}", response_class=HTMLResponse)
def reset_page(
    request: Request,
    token: str,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(PasswordReset).where(
            PasswordReset.token_hash == _hash_token(token),
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > datetime.now(timezone.utc),
        )
    )
    if row is None:
        return templates.TemplateResponse(
            request, "reset.html", {"user": None, "invalid": True}, status_code=400
        )
    return templates.TemplateResponse(
        request, "reset.html", {"user": None, "token": token}
    )


@router.post("/ui/reset", response_class=HTMLResponse)
@limiter.limit("10/hour")
def ui_reset(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(PasswordReset).where(
            PasswordReset.token_hash == _hash_token(token),
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > datetime.now(timezone.utc),
        )
    )
    if row is None:
        return templates.TemplateResponse(
            request, "reset.html", {"user": None, "invalid": True}, status_code=400
        )

    if len(password) < 12:
        return templates.TemplateResponse(
            request, "reset.html",
            {"user": None, "token": token, "error": "Password must be at least 12 characters"},
            status_code=400,
        )

    target = db.get(User, row.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")

    target.password_hash = hash_password(password)
    row.used_at = datetime.now(timezone.utc)
    db.commit()

    response = RedirectResponse(url="/", status_code=303)
    _set_session(response, target.id)
    return response
