"""Manual repeated-image burst tester.

Uses a normal Discord bot token to post local images into configured channels.
This is intentionally not a user-token/selfbot runner.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import discord
from dotenv import load_dotenv


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def parse_channel_ids(raw: str) -> list[int]:
    channel_ids = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if item:
            channel_ids.append(int(item))
    return channel_ids


def image_files(image_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(image_dir.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Post test image bursts with a normal Discord bot token.")
    parser.add_argument("--channels", default=os.getenv("DISCORD_TEST_CHANNEL_IDS", ""))
    parser.add_argument("--image-dir", default=os.getenv("DISCORD_TEST_IMAGE_DIR", "."))
    parser.add_argument("--delay", type=float, default=float(os.getenv("DISCORD_TEST_DELAY_SECONDS", "2")))
    parser.add_argument("--rounds", type=int, default=int(os.getenv("DISCORD_TEST_ROUNDS", "1")))
    parser.add_argument("--message", default=os.getenv("DISCORD_TEST_MESSAGE", "repeated image burst test"))
    parser.add_argument("--send", action="store_true", help="Actually send messages. Default is dry-run.")
    return parser


async def run(args: argparse.Namespace) -> int:
    token = os.getenv("DISCORD_TEST_BOT_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_TEST_BOT_TOKEN.")

    channel_ids = parse_channel_ids(args.channels)
    if len(channel_ids) < 2:
        raise SystemExit("Set DISCORD_TEST_CHANNEL_IDS to at least two comma-separated channel IDs.")

    images = image_files(Path(args.image_dir))
    if not images:
        raise SystemExit(f"No supported images found in {args.image_dir}.")

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            print(f"Logged in as {client.user} ({client.user.id})")
            print(
                f"{'Sending' if args.send else 'Dry-run'} {args.rounds} round(s), "
                f"{len(channel_ids)} channel(s), {len(images)} image(s), {args.delay}s delay"
            )
            started_at = discord.utils.utcnow()
            sent = 0
            for round_index in range(args.rounds):
                image = images[round_index % len(images)]
                for channel_id in channel_ids:
                    channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
                    elapsed = (discord.utils.utcnow() - started_at).total_seconds()
                    print(f"+{elapsed:.1f}s -> #{getattr(channel, 'name', channel_id)} {image.name}")
                    if args.send:
                        await channel.send(args.message, file=discord.File(image))
                        sent += 1
                    if args.delay > 0:
                        await asyncio.sleep(args.delay)
            print(f"Done. {'Sent' if args.send else 'Would send'} {sent if args.send else args.rounds * len(channel_ids)} messages.")
        finally:
            await client.close()

    await client.start(token)
    return 0


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
