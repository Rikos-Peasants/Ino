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


def test_button_finds_the_image_on_attachment_or_embed():
    attached = FakeMessage(attachments=[FakeAttachment()])
    assert AlertActionView._alert_image_url(attached) == attached.attachments[0].url

    # After a restart the alert comes back with the copy resolved into the embed.
    resolved = FakeMessage(embeds=[FakeEmbed("https://cdn.discordapp.com/attachments/1/2/x.png")])
    assert AlertActionView._alert_image_url(resolved) == "https://cdn.discordapp.com/attachments/1/2/x.png"

    assert AlertActionView._alert_image_url(FakeMessage()) is None
    assert AlertActionView._alert_image_url(None) is None
    # A stale attachment:// reference is not a usable URL.
    assert AlertActionView._alert_image_url(FakeMessage(embeds=[FakeEmbed("attachment://x.png")])) is None
    # Non-image attachments are ignored.
    text_file = FakeAttachment(filename="notes.txt", content_type="text/plain")
    assert AlertActionView._alert_image_url(FakeMessage(attachments=[text_file])) is None


def test_image_button_offers_the_blocklist_action():
    controller = build_controller()
    view = AlertActionView(FakeBot(controller))
    interaction = FakeInteraction(FakeMessage(attachments=[FakeAttachment()]))

    asyncio.run(view.image_button.callback(interaction))

    sent = interaction.sent[0]
    assert sent["embed"].image.url == interaction.message.attachments[0].url
    assert isinstance(sent["view"], AlertImagePreviewView)
    assert sent["view"].image_url == interaction.message.attachments[0].url


def test_image_button_without_an_image_or_without_detection():
    # No kept copy: still offer the add button, which asks for a URL instead.
    view = AlertActionView(FakeBot(build_controller()))
    empty = FakeInteraction(FakeMessage())
    asyncio.run(view.image_button.callback(empty))
    assert "kept no copy" in empty.sent[0]["embed"].description
    assert empty.sent[0]["embed"].image.url is None
    assert isinstance(empty.sent[0]["view"], AlertImagePreviewView)
    assert empty.sent[0]["view"].image_url is None

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
    view = AlertImagePreviewView(build_controller(), "https://example.com/a.png", invoker_id=99)
    assert asyncio.run(view.interaction_check(FakeInteraction(FakeMessage(), user_id=99))) is True

    stranger = FakeInteraction(FakeMessage(), user_id=100)
    assert asyncio.run(view.interaction_check(stranger)) is False
    assert "not yours" in stranger.sent[0]["content"]


if __name__ == "__main__":
    test_alert_keeps_a_copy_of_the_image()
    test_bytes_already_in_hand_are_not_re_downloaded()
    test_uncopyable_images_fall_back_to_the_original_url()
    test_burst_embed_points_at_the_attached_copy()
    test_button_finds_the_image_on_attachment_or_embed()
    test_image_button_offers_the_blocklist_action()
    test_image_button_without_an_image_or_without_detection()
    test_owner_keeps_their_timeout_exemption_but_not_their_spam()
    test_everyone_else_is_timed_out_and_cleaned_up()
    test_a_multi_chunk_body_is_read_whole()
    test_oversized_bodies_are_refused()
    test_preview_is_scoped_to_whoever_opened_it()
    print("alert image button test passed")
