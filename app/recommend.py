import datetime
import json
import logging
import os
import re

import httpx

log = logging.getLogger("verdict.recommend")

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
MAX_HISTORY = 40
ASK_FOR = 16

_key = os.environ.get("ANTHROPIC_API_KEY", "")

SYSTEM = """You suggest films, TV shows, and video games based on what someone \
describes they're in the mood for.

Return ONLY a JSON array. No preamble, no markdown fences, no trailing text.
Each element must be an object with exactly these keys:
  "title"  - the exact, commonly-used English title
  "year"   - release year as an integer
  "type"   - one of "movie", "tv", "game"
  "why"    - one short sentence, under 18 words, on why it fits their request

Rules:
- Only suggest real, released titles you are confident exist. Never invent one.
- Use the title as it is most commonly listed, not a subtitle or regional variant.
- Suggest a mix of types only if the request doesn't specify one.
- Do not suggest anything already in the user's rating history.
- Prefer well-known titles unless they ask for obscure ones.
- Write "why" in plain, direct language. No marketing copy."""


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def suggest(query: str, history: list | None = None) -> list:
    """Ask the model for titles. Returns [] on any failure."""
    if not _key:
        return []

    query = query.strip()[:400]
    if not query:
        return []

    parts = [f"They're looking for: {query}"]
    if history:
        lines = [
            f"- {h['title']} ({h['year'] or 'n/a'}) - rated {h['score']}/5"
            for h in history[:MAX_HISTORY]
        ]
        parts.append(
            "Their recent ratings, for taste calibration:\n" + "\n".join(lines)
        )
    parts.append(f"Give {ASK_FOR} suggestions as a JSON array.")

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                API_URL,
                headers={
                    "x-api-key": _key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MODEL,
                    "max_tokens": 1500,
                    "system": SYSTEM,
                    "messages": [{"role": "user", "content": "\n\n".join(parts)}],
                },
            )
            resp.raise_for_status()
            body = resp.json()
    except Exception:
        return []

    text = "".join(
        block.get("text", "")
        for block in body.get("content", [])
        if block.get("type") == "text"
    )

    try:
        rows = json.loads(_strip_fences(text))
    except Exception:
        return []

    if not isinstance(rows, list):
        return []

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()
        kind = str(row.get("type", "")).strip()
        if not title or kind not in ("movie", "tv", "game"):
            continue
        year = row.get("year")
        out.append(
            {
                "title": title[:200],
                "year": int(year) if isinstance(year, int) else None,
                "type": kind,
                "why": str(row.get("why", "")).strip()[:200] or None,
            }
        )
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _best_match(row: dict, hits: list):
    """Pick the hit that's actually the title the model named.

    Search APIs happily return DLC, mods and remasters for a base-game
    query, so an exact-ish title match beats search ranking."""
    target = _norm(row["title"])
    want_year = row.get("year")

    exact, loose = [], []
    for h in hits:
        name = _norm(h["title"])
        if name == target:
            exact.append(h)
        elif name.startswith(target + " ") or target.startswith(name + " "):
            loose.append(h)

    for pool in (exact, loose):
        if not pool:
            continue
        if want_year:
            for h in pool:
                if h.get("year") and abs(h["year"] - want_year) <= 1:
                    return h
        return pool[0]

    # nothing resembled the title — treat it as unresolved rather than
    # showing the user something they didn't ask for
    return None


def resolve(rows: list, want: int = 8) -> list:
    """Look each suggestion up in the real APIs. Anything that doesn't
    resolve was probably hallucinated, so it's dropped."""
    from app import igdb, tmdb

    out = []
    seen = set()

    for row in rows:
        if len(out) >= want:
            break

        kind = row["type"]
        found = None
        try:
            if kind == "game":
                hits = igdb.search(row["title"], limit=6)
            else:
                hits = [h for h in tmdb.search(row["title"]) if h["type"] == kind][:6]
        except Exception:
            continue

        if not hits:
            continue

        found = _best_match(row, hits)
        if found is None:
            continue

        key = (found["source"], found["source_id"])
        if key in seen:
            continue
        seen.add(key)

        found = dict(found)
        found["why"] = row.get("why")
        out.append(found)

    return out


CONVERSE_SYSTEM = """You help someone decide what film, TV show, or game to \
watch or play next. You reply with JSON only — no prose, no markdown fences.

You have two possible replies.

1. If the request is too vague to give good suggestions, ask for what's missing:
{"mode": "ask", "note": "<one short sentence>", "questions": ["<question>", "<question>"]}
   - At most 2 questions. One is better.
   - Ask only what would genuinely change your answer: mood, whether they want
     a film or a show or a game, how much time they have, what they liked recently.
   - Never ask something they already told you.
   - "note" is a brief conversational line, under 15 words.

2. Otherwise, give suggestions:
{"mode": "results", "note": "<one short sentence>", "suggestions": [
  {"title": "<exact common English title>", "year": <int>, "type": "movie|tv|game",
   "why": "<under 18 words on why it fits>"}
]}
   - Give 14 suggestions.
   - Only real, released titles you are confident exist. Never invent one.
   - Use the base title, not a subtitle, DLC, expansion or regional variant.
   - Don't suggest anything in their rating history.
   - "note" introduces the list in plain language, under 15 words.

Prefer answering over asking. Only ask when the request is genuinely too thin —
a request with a clear mood, genre, or reference point is enough to work with.
Write plainly. No marketing language, no enthusiasm padding.

Today is {today}. When someone asks for something recent, new, or current, they
mean the last year or two from that date. Your knowledge of releases may end
earlier than today — if you are not confident about what came out recently,
say so in "note" rather than passing off older titles as new."""


def _system() -> str:
    today = datetime.date.today().strftime("%B %d, %Y")
    return CONVERSE_SYSTEM.replace("{today}", today)


def converse(turns: list, history: list | None = None) -> dict:
    """turns is [{"role": "user"|"assistant", "content": str}, ...].

    Returns {"mode": "ask"|"results"|"error", ...}."""
    if not _key or not turns:
        return {"mode": "error"}

    context = ""
    if history:
        lines = [
            f"- {h['title']} ({h['year'] or 'n/a'}) - rated {h['score']}/5"
            for h in history[:MAX_HISTORY]
        ]
        context = (
            "For taste calibration, here is what they have rated recently. "
            "Do not suggest these again:\n" + "\n".join(lines) + "\n\n"
        )

    messages = []
    for i, turn in enumerate(turns[:8]):
        role = "assistant" if turn.get("role") == "assistant" else "user"
        content = str(turn.get("content", ""))[:600]
        if not content.strip():
            continue
        if role == "user" and i == 0 and context:
            content = context + "They said: " + content
        messages.append({"role": role, "content": content})

    if not messages or messages[0]["role"] != "user":
        return {"mode": "error"}

    try:
        with httpx.Client(timeout=40.0) as client:
            resp = client.post(
                API_URL,
                headers={
                    "x-api-key": _key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MODEL,
                    "max_tokens": 2000,
                    "system": _system(),
                    "messages": messages,
                },
            )
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        log.warning("converse failed: %s", exc)
        return {"mode": "error"}

    text = "".join(
        b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"
    )
    try:
        data = json.loads(_strip_fences(text))
    except Exception as exc:
        log.warning("converse returned unparseable json: %s | %s", exc, text[:200])
        return {"mode": "error"}

    if not isinstance(data, dict):
        return {"mode": "error"}

    note = str(data.get("note", "")).strip()[:200] or None
    mode = data.get("mode")

    if mode == "ask":
        qs = [str(q).strip()[:200] for q in data.get("questions", []) if str(q).strip()]
        if not qs:
            return {"mode": "error"}
        return {"mode": "ask", "note": note, "questions": qs[:2], "raw": text}

    if mode == "results":
        rows = []
        for row in data.get("suggestions", []):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "")).strip()
            kind = str(row.get("type", "")).strip()
            if not title or kind not in ("movie", "tv", "game"):
                continue
            year = row.get("year")
            rows.append(
                {
                    "title": title[:200],
                    "year": int(year) if isinstance(year, int) else None,
                    "type": kind,
                    "why": str(row.get("why", "")).strip()[:200] or None,
                }
            )
        return {"mode": "results", "note": note, "suggestions": rows, "raw": text}

    return {"mode": "error"}
