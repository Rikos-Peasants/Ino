"""Grouping of InoRep history into the /inorep changes timeline."""

from datetime import datetime, timedelta

from models.rep_changes import classify, group_changes, summarize

BASE = datetime(2026, 10, 20, 15, 0, 0)


def entry(reason, amount, minutes_ago, new_rep=100, moderator_id="0", moderator_name="Ino's Shrine"):
    return {
        "reason": reason,
        "amount": amount,
        "new_rep": new_rep,
        "moderator_id": moderator_id,
        "moderator_name": moderator_name,
        "created_at": BASE - timedelta(minutes=minutes_ago),
    }


def test_consecutive_runs_fold_but_keep_order():
    # Newest first: chat x3, spam penalty, chat x2.
    history = [
        entry("Chatting in #general", 1, 1, new_rep=103),
        entry("Chatting in #art", 1, 2, new_rep=102),
        entry("Chatting in #general", 1, 3, new_rep=101),
        entry("Repeated same-message spam", -5, 4, new_rep=100),
        entry("Chatting in #general", 1, 5, new_rep=105),
        entry("Chatting in #general", 1, 6, new_rep=104),
    ]
    groups = group_changes(history)

    assert [g.key for g in groups] == ["chat", "spam", "chat"]
    assert [g.count for g in groups] == [3, 1, 2]
    assert groups[0].total == 3
    assert groups[0].rep_after == 103
    assert groups[0].details == ["#general", "#art"]
    assert groups[0].newest == (BASE - timedelta(minutes=1)).replace(tzinfo=groups[0].newest.tzinfo)
    assert groups[0].oldest < groups[0].newest
    assert summarize(groups) == (5, -5)


def test_runs_break_at_utc_midnight():
    history = [
        entry("Chatting in #general", 1, 0),
        entry("Chatting in #general", 1, 16 * 60),  # previous day
    ]
    assert len(group_changes(history)) == 2


def test_staff_changes_only_merge_with_identical_reason_and_moderator():
    history = [
        entry("Being rude to Ino", -1, 1, moderator_id="7", moderator_name="Mod A"),
        entry("Being rude to Ino", -1, 2, moderator_id="7", moderator_name="Mod A"),
        entry("Being rude to Ino", -1, 3, moderator_id="8", moderator_name="Mod B"),
        entry("Helped out", 5, 4, moderator_id="8", moderator_name="Mod B"),
    ]
    groups = group_changes(history)
    assert [(g.label, g.count, g.staff) for g in groups] == [
        ("Being rude to Ino", 2, "Mod A"),
        ("Being rude to Ino", 1, "Mod B"),
        ("Helped out", 1, "Mod B"),
    ]


def test_classify_known_reasons():
    cases = {
        "Chatting in image-only channel (not allowed)": "image_channel_chat",
        "Someone reacted to your post": "reaction",
        "Voice chat (10 minutes)": "voice",
        "Daily check-in (day 4 streak)": "daily",
        "Thanked by Riko: for the help": "thanked",
        "Tried to thank themselves": "self_thank",
        "Posted an image in image channel": "image",
        "Shared an image": "image",
        "Completed quest: Post 3 images": "quest",
        "Ping spam: 6 pings in 10s": "ping_spam",
        "Harmful content flagged (93% confidence)": "flagged",
        "Said something nice about Ino: 'cute'": "nice",
    }
    for reason, key in cases.items():
        _, kind, _, _ = classify({"reason": reason, "moderator_id": "0"})
        assert kind.key == key, reason


def test_thanks_list_who_thanked_without_the_note():
    groups = group_changes([
        entry("Thanked by Riko: for the help", 5, 1),
        entry("Thanked by Yura", 5, 2),
    ])
    assert len(groups) == 1
    assert groups[0].details == ["Riko", "Yura"]


def test_details_are_capped():
    history = [entry(f"Chatting in #c{i}", 1, i) for i in range(7)]
    group = group_changes(history)[0]
    assert len(group.details) == 4
    assert group.detail_text.endswith("+3 more")


def test_unknown_reasons_do_not_merge_with_each_other():
    groups = group_changes([entry("Something new", 2, 1), entry("Something else", 2, 2)])
    assert len(groups) == 2
