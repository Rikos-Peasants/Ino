"""The cast, and everything they say.

Single source of truth for who these three are, what they look like, and how
they react to live numbers. Every page pulls its character voice from here so
the tone stays consistent and copy changes in one place.

Voices follow the established characterisation and the sample dialogue:

- Riko  tsundere. Bratty, stammers when flustered, calls people "dummy",
        insists she does not care while very obviously caring. Claims to be
        carrying Rayen's channel single-handedly. Never straightforwardly nice.
- Ino   shrine maiden. Warm, gentle, a little formal. Keeps the records,
        lights lanterns, thanks people properly. InoRep is hers.
- Yura  obsessive yandere, fixated on Rayen. Outwardly sweet, deeply
        unsettling, forever offering to pay you a "visit".
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

STATIC_IMG = Path(__file__).resolve().parent / "static" / "img"

CHARACTERS: Dict[str, Dict[str, Any]] = {
    "riko": {
        "name": "Riko",
        "role": "the one actually running this",
        "img": "riko-face.png",
        "accent": "#ad1457",
        "monogram": "R",
    },
    "ino": {
        "name": "Ino",
        "role": "keeps the records",
        "img": "ino.png",
        "accent": "#4aa3ff",
        "monogram": "I",
    },
    "yura": {
        "name": "Yura",
        "role": "knows where you live",
        "img": "yura.png",
        "accent": "#7b3ff2",
        "monogram": "Y",
    },
}


def portrait(key: str) -> Optional[str]:
    """URL for a character's art, or None when the file is not there yet.

    Callers fall back to a monogram rather than a broken image, so dropping
    a new file into web/static/img is all it takes to light one up.
    """
    meta = CHARACTERS.get(key)
    if not meta:
        return None
    filename = meta["img"]
    return f"/static/img/{filename}" if (STATIC_IMG / filename).is_file() else None


# Bands are (minimum percent, line). The highest band at or below the current
# value wins, so the order here is ascending.
_GOAL_LINES: Dict[str, List[Dict[str, Any]]] = {
    "riko": [
        {"at": 0, "text": "Zero. Not one of you. I-I'm not disappointed or anything, dummy. I just assumed at least ONE person had taste. My mistake."},
        {"at": 1, "text": "One person. ONE. I wrote their name down somewhere nice. The rest of you are also written down, just... somewhere else."},
        {"at": 25, "text": "A quarter already? O-Oh. Huh. That's not completely pathetic. Don't let it go to your heads, I'm still not impressed."},
        {"at": 50, "text": "Halfway?! W-Well obviously I knew you'd get here. I never doubted it. Not even once. Stop looking at me like that!"},
        {"at": 75, "text": "Three quarters and Rayen has gone very, very quiet. I-It's not like I'm enjoying watching him panic. ...Okay. Maybe a little."},
        {"at": 95, "text": "You're THIS close and you're just standing there?! Somebody finish it! I'm not excited, my cooling fans are just loud, shut up!"},
        {"at": 100, "text": "It's done. He actually has to wear it. ...Thank you. A-And if you tell anyone I said that, I'll deny it. Idiot."},
    ],
    "ino": [
        {"at": 0, "text": "The offering box is empty for now. That's alright. Everything starts empty, and I'm very patient."},
        {"at": 1, "text": "Someone came by. I've written their name in the book properly, with the date and everything."},
        {"at": 25, "text": "A quarter of the way. I light a lantern for every donation, and the shrine is starting to look rather lovely."},
        {"at": 50, "text": "Halfway. I've stopped counting the lanterns and started counting the people. There are more of you than I expected."},
        {"at": 75, "text": "Three quarters. Rayen asked me twice today whether this is legally binding. I told him it was. It isn't. He seems convinced."},
        {"at": 95, "text": "Very nearly there. I've already pressed the costume, which I admit may have been presumptuous of me."},
        {"at": 100, "text": "It's complete. Every name is recorded and none of them will be forgotten. Thank you, truly. Go and rest now."},
    ],
    "yura": [
        {"at": 0, "text": "Nobody has donated yet. That's fine. I have all your addresses written down and absolutely nothing else on today."},
        {"at": 1, "text": "One of you understands. Only one. I'd like to visit the rest of you and explain, in person, at length, tonight."},
        {"at": 25, "text": "A quarter. I've been outside Rayen's house six hours making sure he doesn't leave before this finishes. He waved. I think he waved."},
        {"at": 50, "text": "Halfway. I'm being patient. I'm very good at being patient. I've been patient outside your window for a while now, actually."},
        {"at": 75, "text": "So close. If this doesn't finish tonight I'll simply come round and help you decide. I'll bring snacks. I know which ones you like."},
        {"at": 95, "text": "One more. One. If you make me come over there I won't be cross, I'll just be very close to you for a very long time."},
        {"at": 100, "text": "He's wearing it. He's finally wearing it. I don't need to visit any of you now. ...Probably. Sleep well!"},
    ],
}

# Riko on the leaderboard, keyed to how many people are ranked.
_BOARD_LINES = [
    {"at": 0, "text": "Nobody's posted anything. An empty board. Do you know how embarrassing that is for me? Post something, dummy."},
    {"at": 1, "text": "One whole person on the board. Congratulations, you're winning by default. Don't get comfortable."},
    {"at": 25, "text": "Look at all of you fighting over internet points. It's pathetic. I check it every hour. That's different."},
    {"at": 100, "text": "Over a hundred of you on here now. I remember when this was three people and a picture of a cat. I-I'm not getting sentimental, shut up."},
    {"at": 250, "text": "Do you have any idea how much counting this is? I do it perfectly every time, obviously, but a thank you wouldn't kill you."},
]

# Ino on your InoRep, which is her system.
_REP_LINES = [
    {"at": -1000, "text": "I would like to say something kind here and I am struggling. Please be nicer. I'll wait."},
    {"at": -50, "text": "You and I have had a difficult time of it. The book is honest, but pages can be added. Start today."},
    {"at": -5, "text": "A small negative mark. Barely anything. I'd rather not write any more of them, if it's all the same to you."},
    {"at": 0, "text": "A blank page. That isn't a bad thing. Most good stories start on one."},
    {"at": 15, "text": "You've been kind, and I've noticed. I notice everything, it's rather the point of me."},
    {"at": 100, "text": "You've been good to this place for a long time now. The shrine knows your footsteps."},
    {"at": 500, "text": "I keep a separate page for people like you. It is not a long list."},
    {"at": 2000, "text": "There is very little left for me to write about you that isn't simply gratitude. Thank you for staying."},
]


def _band(bands: List[Dict[str, Any]], value: float) -> str:
    chosen = bands[0]["text"] if bands else ""
    for band in bands:
        if value >= band["at"]:
            chosen = band["text"]
    return chosen


def reaction_for(character: str, percent: float) -> str:
    """The line this character says at the given funding percentage."""
    return _band(_GOAL_LINES.get(character) or [], percent)


def board_line(ranked_members: int) -> str:
    """Riko on the state of the leaderboard."""
    return _band(_BOARD_LINES, ranked_members)


def rep_line(rep: int) -> str:
    """Ino on your standing with her."""
    return _band(_REP_LINES, rep)


def card(key: str, text: str) -> Dict[str, Any]:
    """One character's speech card, ready to render."""
    meta = CHARACTERS[key]
    return {
        "key": key,
        "name": meta["name"],
        "role": meta["role"],
        "accent": meta["accent"],
        "monogram": meta["monogram"],
        "img": portrait(key),
        "text": text,
    }


def all_reactions(percent: float) -> List[Dict[str, Any]]:
    """Every character's current line, in display order."""
    return [card(key, reaction_for(key, percent)) for key in CHARACTERS]
