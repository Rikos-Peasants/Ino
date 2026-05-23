#!/usr/bin/env python3
"""
Manual command sync script for Riko Discord Bot
Use this if slash commands aren't working properly
"""
import asyncio
import discord
from discord.ext import commands
from config import Config

async def sync_commands():
    """Manually sync commands and check bot status"""
    print("🔄 Manual Command Sync Script")
    print("=" * 40)
    
    try:
        # Create bot instance
        intents = discord.Intents.default()
        intents.members = not Config.SANDBOX_MODE
        intents.message_content = True
        
        bot = commands.Bot(command_prefix='R!', intents=intents)
        
        # Add test commands for sync verification
        @bot.hybrid_command(name="test", description="Test command for sync verification")
        async def test_command(ctx):
            await ctx.send("✅ Hybrid commands are working!")
        
        @bot.hybrid_command(name="uptime", description="Check how long the bot has been running")
        async def uptime_command(ctx):
            await ctx.send("✅ Uptime command working! Use this in the main bot.")
        
        @bot.hybrid_command(name="patreon", description="Support Rayen on Patreon and get exclusive perks!")
        async def patreon_command(ctx):
            await ctx.send("✅ Patreon command working!")
        
        @bot.hybrid_command(name="pointsleaderboard", description="View the points leaderboard")
        async def pointsleaderboard_command(ctx):
            await ctx.send("✅ Points leaderboard command working!")
        
        @bot.hybrid_command(name="quests", description="View your daily quests")
        async def quests_command(ctx):
            await ctx.send("✅ Quests command working!")
        
        @bot.hybrid_command(name="achievements", description="View your achievements")
        async def achievements_command(ctx):
            await ctx.send("✅ Achievements command working!")
        
        @bot.hybrid_command(name="streaks", description="View your streaks and consistency stats")
        async def streaks_command(ctx):
            await ctx.send("✅ Streaks command working!")
        
        @bot.event
        async def on_ready():
            print(f"✅ Connected as {bot.user}")
            
            # Generate invite URL with proper permissions and applications.commands scope
            bot_id = bot.user.id
            permissions = 352670538909696 if Config.SANDBOX_MODE else 268437568
            invite_url = f"https://discord.com/api/oauth2/authorize?client_id={bot_id}&permissions={permissions}&scope=bot%20applications.commands"
            
            print(f"\n🔗 IMPORTANT: Use this invite URL to add applications.commands scope:")
            print(f"{invite_url}")
            print("\n⚠️  Current bot is missing 'applications.commands' scope!")
            print("⚠️  Slash commands will show 'Unknown integration' without this scope!")
            print("\n📋 Required Scopes:")
            print("   ✅ bot (existing)")
            print("   ❌ applications.commands (MISSING - needed for slash commands)")
            
            # Check current guilds
            print(f"\n📊 Bot is currently in {len(bot.guilds)} servers:")
            for guild in bot.guilds:
                print(f"   - {guild.name} (ID: {guild.id})")
            
            # Try to sync commands
            print(f"\n🔄 Attempting to sync commands...")
            
            try:
                # Try guild sync first
                guild = discord.Object(id=Config.GUILD_ID)
                synced_guild = await bot.tree.sync(guild=guild)
                print(f"✅ Guild sync: {len(synced_guild)} commands")
                for cmd in synced_guild:
                    print(f"   - /{cmd.name}")
                
                if Config.SANDBOX_MODE:
                    synced_global = []
                    print("🛡️ Sandbox mode enabled; skipped global command sync")
                else:
                    # Try global sync
                    synced_global = await bot.tree.sync()
                    print(f"✅ Global sync: {len(synced_global)} commands")
                    for cmd in synced_global:
                        print(f"   - /{cmd.name}")

                if not Config.SANDBOX_MODE and len(synced_global) == 0:
                    print("\n❌ NO COMMANDS SYNCED!")
                    print("❌ This is because the bot lacks 'applications.commands' scope")
                    print("❌ Please use the invite URL above to re-add the bot")
                else:
                    print(f"\n✅ Successfully synced {len(synced_global)} commands!")
                
            except discord.Forbidden as e:
                print(f"❌ Forbidden: {e}")
                print("❌ Bot missing 'applications.commands' scope!")
                print("❌ Use the invite URL above to fix this")
            except Exception as e:
                print(f"❌ Sync error: {e}")
            
            print(f"\n📝 Next Steps:")
            print(f"1. Use the invite URL above to re-invite the bot")
            print(f"2. Make sure to include 'applications.commands' scope")
            print(f"3. Test with /test or /uptime commands")
            print(f"4. Text commands should still work with R!test or R!uptime")
            
            await bot.close()
        
        # Connect to Discord
        await bot.start(Config.TOKEN)
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("🤖 Starting manual sync...")
    asyncio.run(sync_commands())
