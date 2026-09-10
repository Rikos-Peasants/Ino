"""The Image button on a burst alert, and the blocklist path behind it.

Covers the two halves separately: the alert keeps a copy of the flagged image
(so the picture survives the burst response deleting the originals), and the
button finds that copy again later to hand to the "Add to scam list" modal.
"""

import asyncio
import io
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord

from controllers.scam_image_controller import ScamImageController
from views.mod_action_view import AlertActionView
from views.scam_image_view import AlertImagePreviewView, image_burst_alert_embed


def png_bytes(color=(200, 40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeAttachment:
    def __init__(self, filename="scam.png", body=None, content_type="image/png", fail=False):
        self.filename = filename
        self.body = body if body is not None else png_bytes()
        self.size = len(self.body)
        self.content_type = content_type
        self.url = "https://cdn.discordapp.com/attachments/1/2/" + filename
        self.fail = fail
        self.reads = []

    async def read(self, *, use_cached=False):
        self.reads.append(use_cached)
        if self.fail:
            raise discord.NotFound(_FakeResponse(), "gone")
        return self.body


class _FakeResponse:
    status = 404
    reason = "Not Found"


class FakeEmbedImage:
    def __init__(self, url):
        self.url = url


class FakeEmbed:
    def __init__(self, image_url=None):
        self.image = FakeEmbedImage(image_url) if image_url else None


class FakeMessage:
    def __init__(self, attachments=None, embeds=None):
        self.attachments = attachments or []
        self.embeds = embeds or []


class FakeUser:
    def __init__(self, user_id=99):
        self.id = user_id


class FakeInteraction:
    def __init__(self, message, user_id=99):
        self.message = message
        self.user = FakeUser(user_id)
        self.sent = []
        self.response = self

    async def send_message(self, content=None, *, embed=None, view=None, ephemeral=False):
        self.sent.append({"content": content, "embed": embed, "view": view})


class FakeBot:
    def __init__(self, controller=None):
        self.scam_image_controller = controller


def build_controller() -> ScamImageController:
    controller = ScamImageController.__new__(ScamImageController)
    controller.max_attachment_bytes = 8 * 1024 * 1024
    controller.max_alert_images = 4

    class Manager:
        @staticmethod
        def is_supported_image(filename):
            return Path(filename).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    controller.manager = Manager()
    return controller


def test_alert_keeps_a_copy_of_the_image():
    controller = build_controller()
    attachment = FakeAttachment()

    image_file, image_url = asyncio.run(controller._build_alert_image_file(attachment))

    assert image_url == "attachment://flagged-image.png", image_url
    assert isinstance(image_file, discord.File)
    assert image_file.fp.read() == attachment.body


def test_bytes_already_in_hand_are_not_re_downloaded():
    controller = build_controller()
    attachment = FakeAttachment(fail=True)  # a second download would raise

    image_file, image_url = asyncio.run(
        controller._build_alert_image_file(attachment, b"already-read")
    )

    assert image_url == "attachment://flagged-image.png"
    assert image_file.fp.read() == b"already-read"
    assert attachment.reads == []


def test_every_image_on_the_spam_message_is_copied():
    """Four images in one message means four copies on the alert."""
    controller = build_controller()
    controller.max_alert_images = 4
    trigger = FakeAttachment(filename="a.png")
    others = [FakeAttachment(filename=f"{n}.png") for n in "bcd"]
    for i, a in enumerate([trigger] + others):
        a.id = i

    message = FakeMessage(attachments=[trigger] + others)
    files, image_url = asyncio.run(
        controller._build_alert_image_files(message, trigger, trigger.body)
    )

    assert image_url == "attachment://flagged-image.png"
    # Distinct names, or they would collide on the one message.
    assert [f.filename for f in files] == [
        "flagged-image.png",
        "flagged-image-2.png",
        "flagged-image-3.png",
        "flagged-image-4.png",
    ]
    # The trigger's bytes were already in hand; only the others are downloaded.
    assert trigger.reads == []
    assert all(a.reads == [False] for a in others)


def test_the_copied_image_count_is_capped():
    controller = build_controller()
    controller.max_alert_images = 2
    attachments = [FakeAttachment(filename=f"{i}.png") for i in range(6)]
    for i, a in enumerate(attachments):
        a.id = i

    files, _ = asyncio.run(
        controller._build_alert_image_files(FakeMessage(attachments=attachments), attachments[0])
    )
    assert len(files) == 2


def test_a_single_image_message_copies_one():
    controller = build_controller()
    attachment = FakeAttachment()
    attachment.id = 1

    files, image_url = asyncio.run(
        controller._build_alert_image_files(FakeMessage(attachments=[attachment]), attachment)
    )
    assert len(files) == 1
    assert image_url == "attachment://flagged-image.png"


def test_uncopyable_images_fall_back_to_the_original_url():
    """No copy is not the same as no picture: the CDN link still works."""
    controller = build_controller()

    oversized = FakeAttachment()
    oversized.size = controller.max_attachment_bytes + 1
    assert asyncio.run(controller._build_alert_image_file(oversized)) == (None, oversized.url)

    unsupported = FakeAttachment(filename="scam.gif")
    assert asyncio.run(controller._build_alert_image_file(unsupported)) == (None, unsupported.url)

    vanished = FakeAttachment(fail=True)
    assert asyncio.run(controller._build_alert_image_file(vanished)) == (None, vanished.url)
    # The signed URL and the cached proxy are both tried before giving up.
    assert vanished.reads == [False, True]

    # Nothing to fall back to when there is no attachment at all.
    assert asyncio.run(controller._build_alert_image_file(None)) == (None, None)


def test_burst_embed_points_at_the_attached_copy():
    class Author:
        id = 4242
        mention = "<@4242>"

        def __str__(self):
            return "spammer#0001"

    class Message:
        author = Author()
        jump_url = "https://discord.com/channels/1/2/3"

    entries = [
        {"channel_id": "1", "attachment_name": "a.png", "attachment_size": 10},
        {"channel_id": "2", "attachment_name": "a.png", "attachment_size": 10},
        {"channel_id": "3", "attachment_name": "a.png", "attachment_size": 10},
    ]

    embed = image_burst_alert_embed(
        Message(),
        entries,
        threshold=3,
        window_seconds=70,
        match_kind="sha256",
        image_url="attachment://flagged-image.png",
    )
    assert embed.image.url == "attachment://flagged-image.png"

    without = image_burst_alert_embed(
        Message(), entries, threshold=3, window_seconds=70, match_kind="sha256"
    )
    assert without.image.url is None


def test_button_finds_every_image_on_attachment_or_embed():
    attached = FakeMessage(attachments=[FakeAttachment(), FakeAttachment(filename="b.png")])
    assert AlertActionView._alert_image_urls(attached) == [a.url for a in attached.attachments]

    # After a restart the alert comes back with the copy resolved into the embed.
    resolved = FakeMessage(embeds=[FakeEmbed("https://cdn.discordapp.com/attachments/1/2/x.png")])
    assert AlertActionView._alert_image_urls(resolved) == ["https://cdn.discordapp.com/attachments/1/2/x.png"]

    assert AlertActionView._alert_image_urls(FakeMessage()) == []
    assert AlertActionView._alert_image_urls(None) == []
    # A stale attachment:// reference is not a usable URL.
    assert AlertActionView._alert_image_urls(FakeMessage(embeds=[FakeEmbed("attachment://x.png")])) == []
    # Non-image attachments are ignored.
    text_file = FakeAttachment(filename="notes.txt", content_type="text/plain")
    assert AlertActionView._alert_image_urls(FakeMessage(attachments=[text_file])) == []


def test_image_button_shows_every_image_in_a_gallery():
    controller = build_controller()
    view = AlertActionView(FakeBot(controller))
    attachments = [FakeAttachment(filename=f"scam{i}.png") for i in range(4)]
    interaction = FakeInteraction(FakeMessage(attachments=attachments))

    asyncio.run(view.image_button.callback(interaction))

    sent = interaction.sent[0]
    # Components V2 rejects a message carrying both a layout and an embed.
    assert sent["embed"] is None and sent["content"] is None
    assert isinstance(sent["view"], AlertImagePreviewView)
    assert sent["view"].image_urls == [a.url for a in attachments]

    payload = sent["view"].to_components()
    text, gallery, row = payload
    assert text["type"] == 10 and "4 flagged images" in text["content"]
    assert gallery["type"] == 12
    assert [item["media"]["url"] for item in gallery["items"]] == [a.url for a in attachments]
    assert row["components"][0]["label"] == "Add to scam list"


def test_image_button_without_an_image_or_without_detection():
    # No kept copy: still offer the add button, which asks for a URL instead.
    view = AlertActionView(FakeBot(build_controller()))
    empty = FakeInteraction(FakeMessage())
    asyncio.run(view.image_button.callback(empty))
    preview = empty.sent[0]["view"]
    assert isinstance(preview, AlertImagePreviewView)
    assert preview.image_urls == []
    types = [c["type"] for c in preview.to_components()]
    assert types == [10, 1]  # caption and button, no gallery
    assert "kept no copy" in preview.to_components()[0]["content"]

    # Detection offline: nothing to add it to, so say so.
    view = AlertActionView(FakeBot(None))
    interaction = FakeInteraction(FakeMessage(attachments=[FakeAttachment()]))
    asyncio.run(view.image_button.callback(interaction))
    assert "not available" in interaction.sent[0]["content"]


class FakeBurstMessage:
    def __init__(self, author):
        self.author = author
        self.deleted = False
        self.guild = type("G", (), {"name": "Riko's Place", "id": 1})()

    async def delete(self):
        self.deleted = True


class FakeAuthor:
    # Class attributes, not instance ones: discord.Member exposes id/mention as
    # read-only properties, and FakeMember below inherits from it.
    id = 742066956194152449
    mention = "<@742066956194152449>"

    def __init__(self):
        self.dms = []
        self.timed_out_until = None

    def __str__(self):
        return "seikadev."

    async def edit(self, *, timed_out_until=None, reason=None):
        self.timed_out_until = timed_out_until

    async def send(self, *, embed=None):
        self.dms.append(embed)


class FakeMember(FakeAuthor, discord.Member):
    """The timeout branch checks ``isinstance(author, discord.Member)``."""


def build_burst_controller(is_owner: bool):
    controller = build_controller()
    controller.image_burst_timeout_enabled = True
    controller.image_burst_timeout_seconds = 180
    controller.image_burst_delete_messages = True
    controller.image_burst_dm_security_notice = True

    class Bot:
        async def is_owner(self, _user):
            return is_owner

    controller.bot = Bot()
    return controller


def run_burst_actions(is_owner: bool):
    controller = build_burst_controller(is_owner)
    author = FakeMember()
    message = FakeBurstMessage(author)
    entries = [
        {"message": FakeBurstMessage(author), "message_id": str(i)} for i in range(3)
    ]
    results = asyncio.run(controller._apply_repeated_image_burst_actions(message, entries))
    return results, author, entries


def test_owner_keeps_their_timeout_exemption_but_not_their_spam():
    """A compromised owner account is the scam vector, not an exception to it."""
    results, author, entries = run_burst_actions(is_owner=True)

    assert "Timeout skipped: bot owner" in results
    assert author.timed_out_until is None
    # The images still go.
    assert "Deleted 3 burst messages" in results
    assert all(entry["message"].deleted for entry in entries)
    assert not any("deletion skipped" in r for r in results)
    assert len(author.dms) == 1


def test_everyone_else_is_timed_out_and_cleaned_up():
    results, author, entries = run_burst_actions(is_owner=False)

    assert "Timed out for 180 seconds" in results
    assert author.timed_out_until is not None
    assert "Deleted 3 burst messages" in results
    assert all(entry["message"].deleted for entry in entries)


class FakeStream:
    """A body that arrives in several chunks, as any real one does."""

    def __init__(self, payload, chunk=16 * 1024):
        self.payload = payload
        self.chunk = chunk

    async def iter_chunked(self, _size):
        for i in range(0, len(self.payload), self.chunk):
            yield self.payload[i : i + self.chunk]


class FakeResponse:
    def __init__(self, payload):
        self.content = FakeStream(payload)


def test_a_multi_chunk_body_is_read_whole():
    """content.read(limit) stopped at the first chunk, and PIL rejects those."""
    controller = build_controller()
    payload = png_bytes() * 4000  # comfortably more than one chunk

    body = asyncio.run(controller._read_limited(FakeResponse(payload)))

    assert body == payload
    assert len(body) > 16 * 1024


def test_oversized_bodies_are_refused():
    controller = build_controller()
    controller.max_attachment_bytes = 1024

    assert asyncio.run(controller._read_limited(FakeResponse(b"x" * 5000))) is None
    assert asyncio.run(controller._read_limited(FakeResponse(b"x" * 1024))) == b"x" * 1024


def test_preview_is_scoped_to_whoever_opened_it():
    view = AlertImagePreviewView(build_controller(), ["https://example.com/a.png"], invoker_id=99)
    assert asyncio.run(view.interaction_check(FakeInteraction(FakeMessage(), user_id=99))) is True

    stranger = FakeInteraction(FakeMessage(), user_id=100)
    assert asyncio.run(view.interaction_check(stranger)) is False
    assert "not yours" in stranger.sent[0]["content"]


if __name__ == "__main__":
    test_alert_keeps_a_copy_of_the_image()
    test_bytes_already_in_hand_are_not_re_downloaded()
    test_every_image_on_the_spam_message_is_copied()
    test_the_copied_image_count_is_capped()
    test_a_single_image_message_copies_one()
    test_uncopyable_images_fall_back_to_the_original_url()
    test_burst_embed_points_at_the_attached_copy()
    test_button_finds_every_image_on_attachment_or_embed()
    test_image_button_shows_every_image_in_a_gallery()
    test_image_button_without_an_image_or_without_detection()
    test_owner_keeps_their_timeout_exemption_but_not_their_spam()
    test_everyone_else_is_timed_out_and_cleaned_up()
    test_a_multi_chunk_body_is_read_whole()
    test_oversized_bodies_are_refused()
    test_preview_is_scoped_to_whoever_opened_it()
    print("alert image button test passed")
