import discord


def signature_embed(title: str, signature) -> discord.Embed:
    embed = discord.Embed(title=title, color=discord.Color.green())
    embed.add_field(name="Label", value=signature.label, inline=False)
    embed.add_field(name="SHA-256", value=f"`{signature.sha256}`", inline=False)
    embed.add_field(name="Size", value=f"{signature.bytes} bytes", inline=True)
    embed.add_field(name="Dimensions", value=f"{signature.width}x{signature.height}", inline=True)
    embed.add_field(name="dHash", value=f"`{signature.dhash}`", inline=True)
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
