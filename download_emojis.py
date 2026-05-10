import discord
import asyncio
import os
import aiohttp
from config import Config

async def download_emojis():
    """Download all emojis from the guild to ./emojis folder"""
    
    # Create emojis and stickers directories if they don't exist
    emojis_dir = "./emojis"
    stickers_dir = "./stickers"
    os.makedirs(emojis_dir, exist_ok=True)
    os.makedirs(stickers_dir, exist_ok=True)
    
    # Create intents (minimal for this task)
    intents = discord.Intents.default()
    intents.guilds = True
    
    # Create client
    client = discord.Client(intents=intents)
    
    @client.event
    async def on_ready():
        print(f"✅ Logged in as {client.user} (ID: {client.user.id})")
        
        # Get the guild
        guild = client.get_guild(Config.GUILD_ID)
        if not guild:
            print(f"❌ Could not find guild with ID {Config.GUILD_ID}")
            await client.close()
            return
        
        print(f"📥 Downloading emojis from guild: {guild.name}")
        
        # Get all emojis
        emojis = guild.emojis
        print(f"Found {len(emojis)} emojis")
        
        # Download each emoji
        downloaded = 0
        failed = 0
        
        async with aiohttp.ClientSession() as session:
            for emoji in emojis:
                try:
                    # Get emoji URL
                    url = emoji.url
                    
                    # Determine file extension
                    if emoji.animated:
                        ext = ".gif"
                    else:
                        ext = ".png"
                    
                    # Create filename
                    filename = f"{emoji.name}{ext}"
                    filepath = os.path.join(emojis_dir, filename)
                    
                    # Download the emoji
                    async with session.get(url) as response:
                        if response.status == 200:
                            with open(filepath, 'wb') as f:
                                f.write(await response.read())
                            print(f"  ✅ Downloaded: {filename}")
                            downloaded += 1
                        else:
                            print(f"  ❌ Failed to download {filename}: HTTP {response.status}")
                            failed += 1
                            
                except Exception as e:
                    print(f"  ❌ Error downloading {emoji.name}: {e}")
                    failed += 1
        
        print(f"\n✅ Emoji download complete: {downloaded} emojis downloaded, {failed} failed")
        
        # Download stickers
        print(f"\n📥 Downloading stickers from guild: {guild.name}")
        stickers = guild.stickers
        print(f"Found {len(stickers)} stickers")
        
        stickers_downloaded = 0
        stickers_failed = 0
        
        async with aiohttp.ClientSession() as session:
            for sticker in stickers:
                try:
                    # Get sticker URL
                    url = sticker.url
                    
                    # Determine file extension based on format
                    format_exts = {
                        discord.StickerFormatType.png: ".png",
                        discord.StickerFormatType.apng: ".png",
                        discord.StickerFormatType.lottie: ".json",
                        discord.StickerFormatType.gif: ".gif"
                    }
                    ext = format_exts.get(sticker.format, ".png")
                    
                    # Create filename
                    filename = f"{sticker.name}{ext}"
                    filepath = os.path.join(stickers_dir, filename)
                    
                    # Download the sticker
                    async with session.get(url) as response:
                        if response.status == 200:
                            with open(filepath, 'wb') as f:
                                f.write(await response.read())
                            print(f"  ✅ Downloaded: {filename}")
                            stickers_downloaded += 1
                        else:
                            print(f"  ❌ Failed to download {filename}: HTTP {response.status}")
                            stickers_failed += 1
                            
                except Exception as e:
                    print(f"  ❌ Error downloading {sticker.name}: {e}")
                    stickers_failed += 1
        
        print(f"\n✅ Sticker download complete: {stickers_downloaded} stickers downloaded, {stickers_failed} failed")
        print(f"\n🎉 Total: {downloaded} emojis, {stickers_downloaded} stickers downloaded")
        await client.close()
    
    # Start the bot
    if Config.TOKEN:
        await client.start(Config.TOKEN)
    else:
        print("❌ Discord token is not configured")

if __name__ == "__main__":
    asyncio.run(download_emojis())
