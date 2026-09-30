"""Scam alerts about one user fold into one message.

A spam run across four channels used to leave four alerts in the moderation
log. Now the first posts, the rest edit it, and it pings once: a quiet alert
that later needs a ping is reposted with one, since edits notify nobody.
"""

import asyncio
import copy
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord

from controllers.scam_image_controller import ScamImageController
from models.scam_image_manager import ScamImageMatch
from views.mod_action_view import (
    DISMISSED_FIELD,
    GOOD,
    RESOLVED_FIELD,
    AlertActionView,
    alert_is_closed,
)
from views.scam_image_view import merged_alert_embed

USER_ID = 1502683358809952517
REVIEW_ROLE_ID = 777


def png_bytes(color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, format="PNG")
    return buffer.getvalue()


SCAM_IMAGE = png_bytes((200, 40, 40))
BURST_IMAGE = png_bytes((40, 200, 40))


class _NotFoundResponse:
    status = 404
    reason = "Not Found"


# --- the moderation log -----------------------------------------------------


class PostedAttachment:
    """An attachment as Discord hands it back on a posted alert."""

    def __init__(self, message_id, filename, data):
        self.filename = filename
        self.data = data
        self.content_type = "image/png"
        self.url = f"https://cdn.discordapp.com/attachments/555/{message_id}/{filename}"

    async def to_file(self):
        return discord.File(io.BytesIO(self.data), filename=self.filename)


class PostedMessage:
    def __init__(self, channel, message_id, *, content, embed, files, view):
        self.channel = channel
        self.id = message_id
        self.content = content
        self.view = view
        self.edits = 0
        self.attachments = [self._attach(f) for f in files or []]
        self.embeds = [self._resolve(embed)]

    def _attach(self, image_file):
        return PostedAttachment(self.id, image_file.filename, image_file.fp.read())

    def _resolve(self, embed):
        """Discord turns attachment:// into the attachment's own link.

        Deep, as a round trip through Discord is: Embed.copy() would share
        the fields list with the embed the controller keeps.
        """
        embed = discord.Embed.from_dict(copy.deepcopy(embed.to_dict()))
        url = embed.image.url if embed.image else None
        if url and url.startswith("attachment://"):
            name = url[len("attachment://"):]
            match = next((a for a in self.attachments if a.filename == name), None)
            embed.set_image(url=match.url if match else None)
        return embed

    async def edit(self, *, embed=None, attachments=None, view=None, content=None):
        await asyncio.sleep(0)
        self.edits += 1
        if attachments is not None:
            self.attachments = [
                a if isinstance(a, PostedAttachment) else self._attach(a) for a in attachments
            ]
        if embed is not None:
            self.embeds = [self._resolve(embed)]
        if view is not None:
            self.view = view
        return self

    async def delete(self):
        self.channel.messages.pop(self.id, None)


class LogChannel:
    id = 555
    mention = "<#555>"

    def __init__(self):
        self.messages = {}
        self.sent = []
        self._next_id = 9000

    async def send(self, content=None, *, embed=None, view=None, files=None):
        await asyncio.sleep(0)
        self._next_id += 1
        posted = PostedMessage(self, self._next_id, content=content, embed=embed, files=files, view=view)
        self.messages[posted.id] = posted
        self.sent.append(posted)
        return posted

    async def fetch_message(self, message_id):
        await asyncio.sleep(0)
        if message_id not in self.messages:
            raise discord.NotFound(_NotFoundResponse(), "Unknown Message")
        return self.messages[message_id]

    def only_alert(self):
        assert len(self.messages) == 1, f"{len(self.messages)} alerts in the log"
        return next(iter(self.messages.values()))


# --- the spam being reported ------------------------------------------------


class Author:
    id = USER_ID
    mention = f"<@{USER_ID}>"

    def __str__(self):
        return "ren_alt23448"


class Guild:
    id = 1278117138909102170
    name = "Riko's Place"


class Channel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.mention = f"<#{channel_id}>"


class SpamMessage:
    _next_id = 1554678184811692052

    def __init__(self, channel_id):
        SpamMessage._next_id += 1
        self.id = SpamMessage._next_id
        self.author = Author()
        self.guild = Guild()
        self.channel = Channel(channel_id)
        self.jump_url = f"https://discord.com/channels/{Guild.id}/{channel_id}/{self.id}"


class SpamAttachment:
    filename = "image.jpg"
    size = 94174


class Manager:
    def __init__(self):
        self.marked = []
        self.released = []

    def reserve_cross_channel_alert(self, **_kwargs):
        return "token"

    def mark_cross_channel_alert_sent(self, _guild, _user, token, alert_kind=None):
        self.marked.append(token)

    def release_cross_channel_alert_reservation(self, _guild, _user, token, alert_kind=None):
        self.released.append(token)


class Bot:
    mod_actions = None  # no buttons; the merge is what is under test

    def __init__(self):
        self.scam_image_controller = None


def build_controller(log_channel):
    controller = ScamImageController.__new__(ScamImageController)
    controller.bot = Bot()
    controller.bot.scam_image_controller = controller
    controller.manager = Manager()
    controller.cross_channel_threshold = 3
    controller.cross_channel_alert_cooldown_minutes = 10
    controller.image_burst_window_seconds = 70
    controller.alert_merge_minutes = 30
    controller.max_merged_alert_images = 10
    controller._alert_incidents = {}
    controller._alert_locks = {}

    async def moderation_log_channel(_guild):
        return log_channel

    async def review_role_id(_guild):
        return REVIEW_ROLE_ID

    controller._get_moderation_log_channel = moderation_log_channel
    controller._get_review_role_id = review_role_id
    return controller


MATCH = ScamImageMatch(
    kind="dhash",
    label="fake scammy scammer (1/3)",
    detail="1c9f69a7a929aea9 distance=0",
)


async def detect(controller, channel_id, image=SCAM_IMAGE):
    message = SpamMessage(channel_id)
    await controller._send_detection_log(
        message,
        SpamAttachment(),
        MATCH,
        deleted=True,
        delete_error=None,
        image_files=[discord.File(io.BytesIO(image), filename="flagged-image.png")],
        image_url="attachment://flagged-image.png",
    )


async def burst(controller, channel_ids, image=BURST_IMAGE):
    message = SpamMessage(channel_ids[-1])
    now = datetime.now(timezone.utc)
    entries = [
        {
            "channel_id": str(channel_id),
            "created_at": now,
            "attachment_name": "image.jpg",
            "attachment_size": 93954,
            "message_id": str(index),
        }
        for index, channel_id in enumerate(channel_ids)
    ]
    await controller._send_image_burst_alert(
        message,
        entries,
        [str(channel_id) for channel_id in channel_ids],
        match_kind="Exact SHA-256",
        action_results=["Timed out for 180 seconds", "Deleted 3 burst messages", "Security DM sent"],
        image_files=[discord.File(io.BytesIO(image), filename="flagged-image.png")],
        image_url="attachment://flagged-image.png",
        subject="abc",
    )


def timeline(alert):
    field = next(f for f in alert.embeds[0].fields if f.name.startswith("Timeline"))
    return field.name, field.value.split("\n")


INTRODUCTION, LOUNGE, LOUNGE_2, BETA_BUGS = 1521305658530594996, 1278117139428933651, 1282209710002540584, 1494509100233654382


# --- tests ------------------------------------------------------------------


def test_the_reported_spam_run_is_one_alert_that_pings_once():
    """Two matches, a burst, one more match: what used to be four alerts."""
    log = LogChannel()
    controller = build_controller(log)

    async def run():
        await detect(controller, INTRODUCTION)
        quiet = log.only_alert()
        assert quiet.content is None  # a lone match does not ping

        await detect(controller, LOUNGE)
        assert log.only_alert() is quiet and quiet.edits == 1

        await burst(controller, [INTRODUCTION, LOUNGE, LOUNGE_2])
        await detect(controller, BETA_BUGS)

    asyncio.run(run())

    alert = log.only_alert()
    # Reposted once, for the ping, and the quiet copy removed.
    assert len(log.sent) == 2
    assert [m.content for m in log.sent] == [None, f"<@&{REVIEW_ROLE_ID}> Repeated image burst detected"]
    assert alert is log.sent[1]
    # The burst heads it, and every alert is on the timeline, oldest first.
    embed = alert.embeds[0]
    assert embed.title == "Repeated Image Burst Alert"
    assert embed.footer.text == f"User ID: {USER_ID}"
    name, lines = timeline(alert)
    assert name == "Timeline · 4 alerts"
    assert len(lines) == 4
    # One timeline, not one left behind per merge.
    assert sum(f.name.startswith("Timeline") for f in embed.fields) == 1
    assert f"<#{INTRODUCTION}>" in lines[0] and "fake scammy scammer" in lines[0]
    assert f"<#{LOUNGE}>" in lines[1]
    assert "Same image in 3 channels (Exact SHA-256)" in lines[2] and "Timed out for 180 seconds" in lines[2]
    assert f"<#{BETA_BUGS}>" in lines[3]
    # The scam image four times over is one copy; the burst image is another.
    assert [a.filename for a in alert.attachments] == ["flagged-image.png", "flagged-image-2.png"]
    assert [a.data for a in alert.attachments] == [SCAM_IMAGE, BURST_IMAGE]
    assert embed.image.url == alert.attachments[0].url
    assert controller.manager.marked == ["token"] and controller.manager.released == []


def test_an_alert_that_already_pinged_is_only_edited():
    log = LogChannel()
    controller = build_controller(log)

    async def run():
        await burst(controller, [INTRODUCTION, LOUNGE, LOUNGE_2])
        await burst(controller, [LOUNGE, LOUNGE_2, BETA_BUGS])
        await detect(controller, BETA_BUGS)

    asyncio.run(run())

    alert = log.only_alert()
    assert len(log.sent) == 1 and alert.edits == 2
    assert timeline(alert)[0] == "Timeline · 3 alerts"
    # The latest burst heads it: only it reached the bug channel.
    affected = next(f for f in alert.embeds[0].fields if f.name == "Affected Channels")
    assert f"<#{BETA_BUGS}>" in affected.value


def test_after_thirty_minutes_a_new_alert_is_posted():
    log = LogChannel()
    controller = build_controller(log)

    async def run():
        await detect(controller, INTRODUCTION)
        incident = next(iter(controller._alert_incidents.values()))
        incident.started_at -= timedelta(minutes=31)
        await detect(controller, LOUNGE)

    asyncio.run(run())

    assert len(log.sent) == 2 and len(log.messages) == 2
    assert all(m.edits == 0 for m in log.sent)


def test_a_deleted_alert_is_not_merged_into():
    log = LogChannel()
    controller = build_controller(log)

    async def run():
        await detect(controller, INTRODUCTION)
        await log.sent[0].delete()
        await detect(controller, LOUNGE)

    asyncio.run(run())

    assert len(log.sent) == 2
    assert log.only_alert() is log.sent[1]


def test_simultaneous_alerts_still_land_on_one_message():
    """Each spam message is scanned concurrently; without the lock, each posted."""
    log = LogChannel()
    controller = build_controller(log)

    async def run():
        await asyncio.gather(*(detect(controller, c) for c in (INTRODUCTION, LOUNGE, LOUNGE_2, BETA_BUGS)))

    asyncio.run(run())

    alert = log.only_alert()
    assert len(log.sent) == 1
    assert timeline(alert)[0] == "Timeline · 4 alerts"


# --- closing an alert -------------------------------------------------------


class ModGuild:
    id = Guild.id


class ModUser:
    id = 42
    mention = "<@42>"


class CloseInteraction:
    def __init__(self, message):
        self.message = message
        self.guild = ModGuild()
        self.user = ModUser()


def close(controller, alert, name):
    view = AlertActionView(controller.bot)
    asyncio.run(view._close_alert(CloseInteraction(alert), name=name, value="by <@42>", color=GOOD))
    return view


def test_closing_an_alert_leaves_image_and_history_usable():
    log = LogChannel()
    controller = build_controller(log)
    asyncio.run(detect(controller, INTRODUCTION))
    alert = log.only_alert()

    view = close(controller, alert, RESOLVED_FIELD)

    states = {item.custom_id: item.disabled for item in view.children}
    assert states == {
        "alert:ban": True,
        "alert:kick": True,
        "alert:timeout": True,
        "alert:dismiss": True,
        "alert:image": False,
        "alert:history": False,
    }
    assert alert.view is view
    assert alert_is_closed(alert)


def test_a_closed_alert_is_not_merged_into():
    for field_name in (RESOLVED_FIELD, DISMISSED_FIELD):
        log = LogChannel()
        controller = build_controller(log)
        asyncio.run(detect(controller, INTRODUCTION))
        close(controller, log.sent[0], field_name)

        asyncio.run(detect(controller, LOUNGE))

        assert len(log.sent) == 2, field_name
        closed = log.sent[0]
        # Left exactly as the moderator closed it.
        assert [f.name for f in closed.embeds[0].fields][-1] == field_name
        assert not any(f.name.startswith("Timeline") for f in closed.embeds[0].fields)


def test_closing_stamps_the_latest_copy_of_the_alert():
    """A merge after the click must not be undone by the stamp."""
    log = LogChannel()
    controller = build_controller(log)
    asyncio.run(detect(controller, INTRODUCTION))
    stale = log.sent[0]
    stale_snapshot = PostedMessage(log, stale.id, content=None, embed=stale.embeds[0], files=[], view=None)
    asyncio.run(detect(controller, LOUNGE))

    view = AlertActionView(controller.bot)
    asyncio.run(
        view._close_alert(CloseInteraction(stale_snapshot), name=RESOLVED_FIELD, value="by <@42>", color=GOOD)
    )

    names = [f.name for f in log.only_alert().embeds[0].fields]
    assert "Timeline · 2 alerts" in names and names[-1] == RESOLVED_FIELD


# --- the timeline field -----------------------------------------------------


def test_a_long_timeline_keeps_the_newest_lines():
    headline = discord.Embed(title="Scam Image Detected")
    lines = [f"<t:{1_700_000_000 + i}:T> Scam image in <#{i}> · `dhash` {'x' * 60}" for i in range(40)]

    embed = merged_alert_embed(headline, lines, image_url=None, updated_at=datetime.now(timezone.utc))

    field = embed.fields[-1]
    assert field.name == "Timeline · 40 alerts"
    assert len(field.value) <= 1024
    shown = field.value.split("\n")
    assert shown[0].startswith("+") and shown[0].endswith("earlier")
    assert shown[-1] == lines[-1]
    assert int(shown[0][1:].split()[0]) + len(shown) - 1 == 40
    # The headline embed itself is untouched.
    assert headline.fields == []


if __name__ == "__main__":
    test_the_reported_spam_run_is_one_alert_that_pings_once()
    test_an_alert_that_already_pinged_is_only_edited()
    test_after_thirty_minutes_a_new_alert_is_posted()
    test_a_deleted_alert_is_not_merged_into()
    test_simultaneous_alerts_still_land_on_one_message()
    test_closing_an_alert_leaves_image_and_history_usable()
    test_a_closed_alert_is_not_merged_into()
    test_closing_stamps_the_latest_copy_of_the_alert()
    test_a_long_timeline_keeps_the_newest_lines()
    print("alert merge test passed")
