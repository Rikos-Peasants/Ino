"""Character reactions to the live funding total.

Three voices comment on the same number, and which line each one says is
chosen by the current percentage. The copy is a function of the database, so
the page's tone changes as the fundraiser moves without anyone editing it.

Voices follow the established characterisation:

- Riko  tsundere. Bratty, stammers when flustered, calls people "dummy",
        insists she does not care while very obviously caring. Claims to be
        carrying Rayen's channel. Never straightforwardly nice.
- Ino   shrine maiden. Warm, gentle, a little formal. Keeps records, lights
        lanterns, thanks people properly.
- Yura  obsessive yandere, fixated on Rayen. Outwardly sweet, deeply
        unsettling, keeps offering to pay you a "visit".
"""

from typing import Any, Dict, List

CHARACTERS = {
    "riko": {"name": "Riko", "role": "the one actually running this", "img": "/static/img/riko-face.png"},
    "ino": {"name": "Ino", "role": "keeps the records", "img": "/static/img/ino.png"},
    "yura": {"name": "Yura", "role": "knows where you live", "img": "/static/img/yura.png"},
}

# Bands are (minimum percent, line). The highest band at or below the current
# percentage wins, so the order here is ascending.
_LINES: Dict[str, List[Dict[str, Any]]] = {
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
        {"at": 0, "text": "The offering box is empty for now. That's alright. Everything starts empty, and I'm patient."},
        {"at": 1, "text": "Someone came by. I've written their name in the book properly, with the date and everything."},
        {"at": 25, "text": "A quarter of the way. I light a lantern for every donation, and the shrine is starting to look rather lovely."},
        {"at": 50, "text": "Halfway. I've stopped counting the lanterns and started counting the people. There are more of you than I expected."},
        {"at": 75, "text": "Three quarters. Rayen has asked me twice today whether this is legally binding. I told him it was. It isn't. He seems convinced."},
        {"at": 95, "text": "Very nearly there. I've already pressed the costume, which I admit may have been presumptuous of me."},
        {"at": 100, "text": "It's complete. Every name is recorded, and none of them will be forgotten. Thank you, truly. Go and rest now."},
    ],
    "yura": [
        {"at": 0, "text": "Nobody has donated yet. That's fine. I have all your addresses written down and I have absolutely nothing else on today."},
        {"at": 1, "text": "One of you understands. Only one. I'd like to visit the rest of you and explain, in person, at length, tonight."},
        {"at": 25, "text": "A quarter. I've been standing outside Rayen's house for six hours making sure he doesn't leave before this is finished. He waved. I think he waved."},
        {"at": 50, "text": "Halfway. I'm being patient. I'm very good at being patient. I've been patient outside your window for a while now, actually."},
        {"at": 75, "text": "So close. If this doesn't finish tonight I'll simply have to come round and help you with your decision. I'll bring snacks. I know what you like."},
        {"at": 95, "text": "One more. One. If you make me come over there I won't be cross, I'll just be very close to you for a very long time."},
        {"at": 100, "text": "He's wearing it. He's finally wearing it. I don't need to visit any of you now. ...Probably. Sleep well!"},
    ],
}


def reaction_for(character: str, percent: float) -> str:
    """The line this character says at the given funding percentage."""
    bands = _LINES.get(character) or []
    chosen = bands[0]["text"] if bands else ""
    for band in bands:
        if percent >= band["at"]:
            chosen = band["text"]
    return chosen


def all_reactions(percent: float) -> List[Dict[str, str]]:
    """Every character's current line, in display order."""
    return [
        {
            "key": key,
            "name": meta["name"],
            "role": meta["role"],
            "img": meta["img"],
            "text": reaction_for(key, percent),
        }
        for key, meta in CHARACTERS.items()
    ]
