"""The cast, and everything they say.

All copy lives in phrases.json next to this file so it can be swapped without
touching code. This module only loads it and picks the right line.

Voices, for anyone editing the JSON:

- Ino   shrine maiden, and the bot itself. Warm, gentle, a little formal.
        Keeps the records and thanks people properly. InoRep is hers.
- Riko  tsundere. Bratty, stammers when flustered, says "dummy", insists she
        does not care while very obviously caring.
- Yura  obsessive yandere, fixated on Rayen. Outwardly sweet, quietly
        unsettling, forever offering to pay you a "visit".
"""

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
STATIC_IMG = BASE / "static" / "img"
PHRASES_PATH = BASE / "phrases.json"


def _load() -> Dict[str, Any]:
    try:
        return json.loads(PHRASES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        # A broken edit to phrases.json should not take the site down.
        logger.error(f"Could not read phrases.json ({e}); falling back to empty copy")
        return {}


_P = _load()


def reload_phrases() -> bool:
    """Re-read phrases.json at runtime. Returns False if it failed to parse."""
    global _P
    fresh = _load()
    if not fresh:
        return False
    _P = fresh
    return True


CHARACTERS: Dict[str, Dict[str, Any]] = _P.get("characters", {})
SITE: Dict[str, str] = _P.get("site", {})
BIOS: Dict[str, str] = _P.get("bios", {})


def text(key: str, default: str = "") -> str:
    """One-off site string from phrases.json -> site."""
    return SITE.get(key, default)


def portrait(key: str) -> Optional[str]:
    """URL for a character's art, or None when the file is not there yet.

    Callers fall back to a monogram rather than a broken image, so dropping a
    new file into web/static/img is all it takes to light one up.
    """
    meta = CHARACTERS.get(key)
    if not meta:
        return None
    filename = meta.get("img") or ""
    return f"/static/img/{filename}" if filename and (STATIC_IMG / filename).is_file() else None


def _band(bands: List[Dict[str, Any]], value: float) -> str:
    """Highest band at or below `value`. Bands are sorted ascending by 'at'."""
    chosen = ""
    for band in bands:
        if value >= band.get("at", 0):
            chosen = band.get("text", "")
    return chosen or (bands[0].get("text", "") if bands else "")


def reaction_for(character: str, percent: float) -> str:
    """The line this character says at the given funding percentage."""
    return _band(_P.get("goal_reactions", {}).get(character) or [], percent)


def board_line(ranked_members: int) -> str:
    """Riko on the state of the leaderboard."""
    return _band(_P.get("board") or [], ranked_members)


def rep_line(rep: int) -> str:
    """Ino on your standing with her."""
    return _band(_P.get("rep") or [], rep)


def error_copy(status: int) -> Dict[str, str]:
    """Title, blurb and one line per character for an error page."""
    errors = _P.get("errors", {})
    return errors.get(str(status)) or errors.get("500") or {}


def email_copy() -> Dict[str, str]:
    return _P.get("email", {})


def _voiced(entry: Dict[str, str]) -> Dict[str, str]:
    key = entry.get("key", "ino")
    meta = CHARACTERS.get(key, {})
    return {"key": key, "name": meta.get("name", key.title()), "text": entry.get("text", "")}


def footer_quip(seed: Optional[int] = None) -> Dict[str, str]:
    """A random footer line, with whose voice it is."""
    quips = _P.get("footer_quips") or [{"key": "ino", "text": ""}]
    rng = random.Random(seed) if seed is not None else random
    return _voiced(rng.choice(quips))


def thank_you(name: str, amount: str) -> Dict[str, str]:
    """A donation thank-you, in a rotating voice."""
    options = _P.get("thank_you") or [{"key": "ino", "text": "Thank you, {name}."}]
    spoken = _voiced(random.choice(options))
    spoken["text"] = spoken["text"].format(name=name, amount=amount)
    return spoken


def card(key: str, line: str) -> Dict[str, Any]:
    """One character's speech card, ready to render."""
    meta = CHARACTERS.get(key, {})
    return {
        "key": key,
        "name": meta.get("name", key.title()),
        "role": meta.get("role", ""),
        "accent": meta.get("accent", "#ad1457"),
        "monogram": meta.get("monogram", key[:1].upper()),
        "img": portrait(key),
        "text": line,
    }


def all_reactions(percent: float) -> List[Dict[str, Any]]:
    """Every character's current line, in display order."""
    return [card(key, reaction_for(key, percent)) for key in CHARACTERS]
