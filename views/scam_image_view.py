import discord
from datetime import datetime


def signature_embed(title: str, signature) -> discord.Embed:
    embed = discord.Embed(title=title, color=discord.Color.green())
    embed.add_field(name="Label", value=signature.label, inline=False)
    embed.add_field(name="SHA-256", value=f"`{signature.sha256}`", inline=False)
    embed.add_field(name="Size", value=f"{signature.bytes} bytes", inline=True)
    embed.add_field(name="Dimensions", value=f"{signature.width}x{signature.height}", inline=True)
    embed.add_field(name="dHash", value=f"`{signature.dhash}`", inline=True)
    return embed


def scam_detection_embed(message, attachment, match, *, deleted: bool, delete_error: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="Scam Image Detected",
        description="A message attachment matched a known scam image signature.",
        color=discord.Color.red(),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="User", value=f"{message.author.mention}\n`{message.author}`", inline=True)
    embed.add_field(name="Channel", value=message.channel.mention, inline=True)
    embed.add_field(name="Action", value="Deleted" if deleted else f"Not deleted ({delete_error or 'not configured'})", inline=True)
    embed.add_field(name="Attachment", value=f"`{attachment.filename}`\n{attachment.size} bytes", inline=False)
    embed.add_field(name="Match", value=f"`{match.kind}` {match.label}\n{match.detail}", inline=False)
    embed.add_field(name="Jump", value=f"[Open message]({message.jump_url})", inline=True)
    embed.set_footer(text=f"Message ID: {message.id}")
    return embed


def scam_cross_channel_alert_embed(message, detections, *, threshold: int, window_seconds: int) -> discord.Embed:
    channel_ids = []
    for detection in detections:
        channel_id = detection.get("channel_id")
        if channel_id and channel_id not in channel_ids:
            channel_ids.append(channel_id)

    embed = discord.Embed(
        title="Scam Image Burst Alert",
        description=(
            f"{message.author.mention} posted matched scam images in "
            f"{len(channel_ids)} channels within {window_seconds} seconds."
        ),
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="User", value=f"{message.author.mention}\n`{message.author}`", inline=True)
    embed.add_field(name="Threshold", value=f"{threshold}+ channels", inline=True)
    embed.add_field(name="Channels", value="\n".join(f"<#{channel_id}>" for channel_id in channel_ids[:10]), inline=False)

    recent = []
    for detection in detections[:5]:
        recent.append(
            f"<#{detection.get('channel_id')}> - `{detection.get('match_kind')}` {detection.get('match_label')}"
        )
    if recent:
        embed.add_field(name="Recent Matches", value="\n".join(recent), inline=False)

    embed.add_field(name="Latest Message", value=f"[Open message]({message.jump_url})", inline=True)
    embed.set_footer(text=f"User ID: {message.author.id}")
    return embed


def image_burst_alert_embed(
    message,
    entries,
    *,
    threshold: int,
    window_seconds: int,
    match_kind: str,
    actions: list[str] | None = None,
) -> discord.Embed:
    channel_ids = []
    for entry in entries:
        channel_id = entry.get("channel_id")
        if channel_id and channel_id not in channel_ids:
            channel_ids.append(channel_id)
    created_times = sorted(entry.get("created_at") for entry in entries if entry.get("created_at"))
    first_seen = created_times[0] if created_times else None
    last_seen = created_times[-1] if created_times else None
    span_seconds = int((last_seen - first_seen).total_seconds()) if first_seen and last_seen else 0

    embed = discord.Embed(
        title="Repeated Image Burst Alert",
        description=(
            f"{message.author.mention} posted the same or visually similar image in "
            f"{len(channel_ids)} channels within {window_seconds} seconds."
        ),
        color=discord.Color.dark_orange(),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="User", value=f"{message.author.mention}\n`{message.author}`", inline=True)
    embed.add_field(name="Threshold", value=f"{threshold}+ channels", inline=True)
    embed.add_field(name="Match", value=match_kind, inline=True)
    embed.add_field(name="Images", value=str(len(entries)), inline=True)
    embed.add_field(name="Channels", value=str(len(channel_ids)), inline=True)
    embed.add_field(name="Span", value=f"{span_seconds}s", inline=True)
    if first_seen and last_seen:
        embed.add_field(
            name="Timing",
            value=(
                f"First: <t:{int(first_seen.timestamp())}:T>\n"
                f"Latest: <t:{int(last_seen.timestamp())}:T>"
            ),
            inline=True,
        )
    if actions:
        embed.add_field(name="Actions", value="\n".join(actions), inline=False)
    embed.add_field(name="Affected Channels", value="\n".join(f"<#{channel_id}>" for channel_id in channel_ids[:10]), inline=False)

    recent = []
    for entry in entries[:5]:
        recent.append(
            f"<#{entry.get('channel_id')}> - `{entry.get('attachment_name')}` ({entry.get('attachment_size')} bytes)"
        )
    if recent:
        embed.add_field(name="Recent Images", value="\n".join(recent), inline=False)

    embed.add_field(name="Latest Message", value=f"[Open message]({message.jump_url})", inline=True)
    embed.set_footer(text=f"User ID: {message.author.id}")
    return embed


class ScamImageStatusView(discord.ui.View):
    def __init__(self, controller):
        super().__init__(timeout=180)
        self.controller = controller

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await self.controller.can_manage_scam_images(interaction):
            return True
        await interaction.response.send_message(
            "You need moderation permissions to manage scam image detection.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="List", style=discord.ButtonStyle.secondary)
    async def list_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.controller.send_signature_list(interaction)

    @discord.ui.button(label="Recent", style=discord.ButtonStyle.secondary)
    async def recent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.controller.send_recent_detections(interaction)


class ScamImageAddUrlModal(discord.ui.Modal, title="Add Scam Image URL"):
    url = discord.ui.TextInput(
        label="Image URL",
        placeholder="https://cdn.discordapp.com/attachments/...",
        max_length=2000,
    )
    label = discord.ui.TextInput(
        label="Label",
        placeholder="fake mrbeast crypto scam",
        max_length=120,
    )

    def __init__(self, controller):
        super().__init__(timeout=180)
        self.controller = controller

    async def on_submit(self, interaction: discord.Interaction):
        await self.controller.add_url_from_modal(interaction, str(self.url), str(self.label))
