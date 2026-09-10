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

    async def read(self):
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

    image_file, filename = asyncio.run(controller._build_alert_image_file(attachment))

    assert filename == "flagged-image.png", filename
    assert isinstance(image_file, discord.File)
    assert image_file.fp.read() == attachment.body


def test_no_copy_for_oversized_unsupported_or_vanished_images():
    controller = build_controller()

    oversized = FakeAttachment()
    oversized.size = controller.max_attachment_bytes + 1
    assert asyncio.run(controller._build_alert_image_file(oversized)) == (None, None)

    unsupported = FakeAttachment(filename="scam.gif")
    assert asyncio.run(controller._build_alert_image_file(unsupported)) == (None, None)

    vanished = FakeAttachment(fail=True)
    assert asyncio.run(controller._build_alert_image_file(vanished)) == (None, None)

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
        image_filename="flagged-image.png",
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
    view = AlertActionView(FakeBot(build_controller()))
    empty = FakeInteraction(FakeMessage())
    asyncio.run(view.image_button.callback(empty))
    assert "did not keep a copy" in empty.sent[0]["content"]

    # Detection offline: still show the picture, just without the add button.
    view = AlertActionView(FakeBot(None))
    interaction = FakeInteraction(FakeMessage(attachments=[FakeAttachment()]))
    asyncio.run(view.image_button.callback(interaction))
    assert interaction.sent[0]["view"] is None
    assert interaction.sent[0]["embed"].image.url


def test_preview_is_scoped_to_whoever_opened_it():
    view = AlertImagePreviewView(build_controller(), "https://example.com/a.png", invoker_id=99)
    assert asyncio.run(view.interaction_check(FakeInteraction(FakeMessage(), user_id=99))) is True

    stranger = FakeInteraction(FakeMessage(), user_id=100)
    assert asyncio.run(view.interaction_check(stranger)) is False
    assert "not yours" in stranger.sent[0]["content"]


if __name__ == "__main__":
    test_alert_keeps_a_copy_of_the_image()
    test_no_copy_for_oversized_unsupported_or_vanished_images()
    test_burst_embed_points_at_the_attached_copy()
    test_button_finds_the_image_on_attachment_or_embed()
    test_image_button_offers_the_blocklist_action()
    test_image_button_without_an_image_or_without_detection()
    test_preview_is_scoped_to_whoever_opened_it()
    print("alert image button test passed")
