import discord
from datetime import datetime
from typing import Optional
import asyncio
import logging

logger = logging.getLogger(__name__)

class EmbedViews:
    """Handles creation of Discord embeds"""
    
    @staticmethod
    def access_denied_embed() -> discord.Embed:
        """Create an embed for access denied message"""
        embed = discord.Embed(
            title="🚫 Access Denied",
            description="You are banned from accessing this role/channel.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Contact an administrator if you believe this is an error")
        return embed
    
    @staticmethod
    def nsfwban_success_embed(user: discord.Member, reason: str, banned_by: discord.Member) -> discord.Embed:
        """Create an embed for successful NSFWBAN"""
        embed = discord.Embed(
            title="🔨 NSFWBAN Applied",
            description=f"**{user.display_name}** has been NSFWBAN'd",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="👤 User", value=f"{user.mention} ({user.id})", inline=True)
        embed.add_field(name="👮 Banned by", value=f"{banned_by.mention}", inline=True)
        embed.add_field(name="📝 Reason", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        return embed
    
    @staticmethod
    def nsfwunban_success_embed(user: discord.Member, unbanned_by: discord.Member) -> discord.Embed:
        """Create an embed for successful NSFWUNBAN"""
        embed = discord.Embed(
            title="✅ NSFWBAN Removed",
            description=f"**{user.display_name}** has been unbanned from NSFW content",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="👤 User", value=f"{user.mention} ({user.id})", inline=True)
        embed.add_field(name="👮 Unbanned by", value=f"{unbanned_by.mention}", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        return embed
    
    @staticmethod
    def nsfwban_dm_embed(reason: str, guild_name: str) -> discord.Embed:
        """Create an embed for NSFWBAN DM notification"""
        embed = discord.Embed(
            title="🔨 You have been NSFWBAN'd",
            description=f"You have been banned from accessing NSFW content in **{guild_name}**",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📝 Reason", value=reason, inline=False)
        embed.add_field(
            name="ℹ️ What this means",
            value="• You cannot access NSFW channels\n• This restriction will persist if you leave and rejoin\n• Contact an administrator to appeal",
            inline=False
        )
        embed.set_footer(text="Contact server administrators if you believe this is an error")
        return embed
    
    @staticmethod
    def nsfwunban_dm_embed(guild_name: str) -> discord.Embed:
        """Create an embed for NSFWUNBAN DM notification"""
        embed = discord.Embed(
            title="✅ NSFWBAN Removed",
            description=f"Your NSFW ban has been removed in **{guild_name}**",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(
            name="🎉 You can now",
            value="• Access NSFW channels again\n• Participate in age-restricted content",
            inline=False
        )
        return embed
    
    @staticmethod
    def uptime_embed(uptime_str: str) -> discord.Embed:
        """Create an embed for uptime command"""
        embed = discord.Embed(
            title="🟢 Bot Uptime",
            description=f"Bot has been running for: **{uptime_str}**",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        return embed
    
    @staticmethod
    def error_embed(message: str) -> discord.Embed:
        """Create a generic error embed"""
        embed = discord.Embed(
            title="❌ Error",
            description=message,
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        return embed
    
    @staticmethod
    def patreon_embed() -> discord.Embed:
        """Create an embed for the Patreon command"""
        from config import Config
        embed = discord.Embed(
            title="💖 Support Rayen on Patreon!",
            description=(
                "Love what Rayen does? Support him on Patreon and get exclusive perks!\n\n"
                "**🎁 Patreon Benefits:**\n"
                "• **1.5x Quest Points** - Earn 50% more points on all quests!\n"
                "• **Exclusive Role** - Get the \"Riko's Agent\" role\n"
                "• **Early Access** - Be the first to see new content\n"
                "• **Direct Support** - Help Rayen create more amazing content\n\n"
                f"[**👉 Become a Patron Now!**]({Config.PATREON_URL})"
            ),
            color=0xff424d,  # Patreon red color
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Thank you for your support! ❤️")
        embed.set_thumbnail(url="https://c5.patreon.com/external/logo/become_a_patron_button.png")
        return embed
    
    @staticmethod
    async def best_image_embed(message: discord.Message, period: str, score: int) -> discord.Embed:
        """Create an embed for the best image of the week/month"""
        # Determine color and emojis based on period
        if period == "week":
            color = discord.Color.gold()
            trophy_emoji = "🥇"
            title = "Best Image of the Week!"
        elif period == "month":
            color = discord.Color.purple()
            trophy_emoji = "👑"
            title = "Best Image of the Month!"
        else:  # year
            color = discord.Color.red()
            trophy_emoji = "🏆"
            title = "Best Image of the Year!"
        
        embed = discord.Embed(
            title=f"{trophy_emoji} {title}",
            description=f"Congratulations to **{message.author.display_name}** for the most upvoted image!\n\n"
                       f"**Net Score:** {score} upvotes (👍 - 👎)\n"
                       f"**Channel:** #{message.channel.name}\n"
                       f"**Posted:** {message.created_at.strftime('%B %d, %Y at %I:%M %p')}",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        # Add the winning image
        image_url = None
        
        # Check for attachments first
        for attachment in message.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                image_url = attachment.url
                break
        
        # Check for embedded images if no attachment
        if not image_url:
            for embed_obj in message.embeds:
                if embed_obj.image:
                    image_url = embed_obj.image.url
                    break
                elif embed_obj.thumbnail:
                    image_url = embed_obj.thumbnail.url
                    break
        
        if image_url:
            # Display all images the same way (no NSFW spoilers)
            embed.set_image(url=image_url)
        
        # Add original message link
        embed.add_field(
            name="🔗 Original Post",
            value=f"[Click here to see the original]({message.jump_url})",
            inline=False
        )
        
        # Add author info
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url if message.author.display_avatar else None
        )
        
        embed.set_footer(text=f"🎉 Winner of the {period}!")
        
        return embed
    
    @staticmethod
    def no_winner_embed(period: str) -> discord.Embed:
        """Create an embed when no images are found for the period"""
        embed = discord.Embed(
            title=f"📭 No Best Image of the {period.title()}",
            description=f"No images were posted in this channel during the past {period}.\n\n"
                       f"Keep sharing your amazing images here for a chance to win next {period}!",
            color=discord.Color.light_grey(),
            timestamp=datetime.utcnow()
        )
        
        embed.set_footer(text=f"Better luck next {period} in this channel!")
        
        return embed
    
    @staticmethod
    def warning_embed(user: discord.Member, moderator: discord.Member, reason: str, warning_count: int, action: str) -> discord.Embed:
        """Create an embed for a user warning"""
        # Determine color based on warning count
        if warning_count == 1:
            color = discord.Color.orange()
            title = "⚠️ Warning Issued"
        elif warning_count == 2:
            color = discord.Color.red()
            title = "🔴 Second Warning - Timeout Applied"
        elif warning_count == 3:
            color = discord.Color.dark_red()
            title = "🚨 Third Warning - Extended Timeout"
        elif warning_count == 4:
            color = discord.Color.dark_red()
            title = "⛔ Fourth Warning - Long Timeout"
        else:
            color = discord.Color.dark_red()
            title = "🔨 Final Warning - User Kicked"
        
        embed = discord.Embed(
            title=title,
            description=f"**{user.display_name}** has received warning #{warning_count}",
            color=color,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(name="👤 User", value=f"{user.mention} ({user.id})", inline=True)
        embed.add_field(name="👮 Moderator", value=f"{moderator.mention}", inline=True)
        embed.add_field(name="📊 Warning Count", value=f"**{warning_count}**/5", inline=True)
        embed.add_field(name="📝 Reason", value=reason, inline=False)
        
        # Add action taken
        action_text = {
            "warning": "⚠️ Warning logged - no immediate action",
            "timeout_1h": "🔇 User timed out for 1 hour",
            "timeout_4h": "🔇 User timed out for 4 hours", 
            "timeout_1w": "🔇 User timed out for 1 week",
            "kick": "👢 User has been kicked from the server"
        }
        
        embed.add_field(
            name="⚡ Action Taken",
            value=action_text.get(action, "No action taken"),
            inline=False
        )
        
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        embed.set_footer(text="Server Moderation System")
        
        return embed
    
    @staticmethod
    def user_warnings_embed(user: discord.Member, warnings: list, total_count: int) -> discord.Embed:
        """Create an embed showing a user's warnings"""
        embed = discord.Embed(
            title=f"📋 Warnings for {user.display_name}",
            description=f"Showing recent warnings ({len(warnings)} of {total_count} total)",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(name="👤 User", value=f"{user.mention} ({user.id})", inline=True)
        embed.add_field(name="⚠️ Active Warnings", value=f"**{total_count}**/5", inline=True)
        embed.add_field(name="📊 Status", value="❌ At Risk" if total_count >= 3 else "✅ Good Standing", inline=True)
        
        if warnings:
            for i, warning in enumerate(warnings[:5], 1):  # Show max 5 recent warnings
                created_at = warning.get('created_at', datetime.now())
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at)
                    except:
                        created_at = datetime.now()
                
                embed.add_field(
                    name=f"Warning #{i}",
                    value=f"**Reason:** {warning.get('reason', 'No reason')}\n"
                          f"**By:** {warning.get('moderator_name', 'Unknown')}\n"
                          f"**Date:** {created_at.strftime('%m/%d/%Y at %I:%M %p')}",
                    inline=False
                )
        else:
            embed.add_field(name="✅ No Warnings", value="This user has no active warnings.", inline=False)
        
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        embed.set_footer(text="Use /clearwarnings to remove warnings")
        
        return embed
    
    @staticmethod
    def warning_cleared_embed(user: discord.Member, cleared_count: int, moderator: discord.Member) -> discord.Embed:
        """Create an embed for cleared warnings"""
        embed = discord.Embed(
            title="🧹 Warnings Cleared",
            description=f"All warnings have been cleared for **{user.display_name}**",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(name="👤 User", value=f"{user.mention} ({user.id})", inline=True)
        embed.add_field(name="👮 Cleared by", value=f"{moderator.mention}", inline=True)
        embed.add_field(name="📊 Warnings Cleared", value=f"**{cleared_count}** warnings", inline=True)
        
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        embed.set_footer(text="User is now in good standing")
        
        return embed
    
    @staticmethod
    def warning_log_embed(user: discord.Member, moderator: discord.Member, reason: str, warning_count: int, action: str) -> discord.Embed:
        """Create an embed for warning log messages"""
        # Determine color and emoji based on warning count
        if warning_count == 1:
            color = discord.Color.orange()
            emoji = "⚠️"
        elif warning_count == 2:
            color = discord.Color.red()
            emoji = "🔴"
        elif warning_count == 3:
            color = discord.Color.dark_red()
            emoji = "🚨"
        elif warning_count == 4:
            color = discord.Color.dark_red()
            emoji = "⛔"
        else:
            color = discord.Color.dark_red()
            emoji = "🔨"
        
        embed = discord.Embed(
            title=f"{emoji} Warning Issued - #{warning_count}",
            description=f"A warning has been issued to {user.mention}",
            color=color,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(name="👤 User", value=f"{user.mention}\n`{user.name}` ({user.id})", inline=True)
        embed.add_field(name="👮 Moderator", value=f"{moderator.mention}\n`{moderator.name}`", inline=True)
        embed.add_field(name="📊 Warning #", value=f"**{warning_count}**/5", inline=True)
        
        embed.add_field(name="📝 Reason", value=reason, inline=False)
        
        # Add action taken
        action_text = {
            "warning": "⚠️ Warning logged",
            "timeout_1h": "🔇 Timed out for 1 hour",
            "timeout_4h": "🔇 Timed out for 4 hours", 
            "timeout_1w": "🔇 Timed out for 1 week",
            "kick": "👢 User kicked from server"
        }
        
        embed.add_field(
            name="⚡ Action Taken",
            value=action_text.get(action, "No action taken"),
            inline=False
        )
        
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        embed.set_footer(text="Warning System Log", icon_url=moderator.display_avatar.url if moderator.display_avatar else None)
        
        return embed
    
    @staticmethod
    def daily_quests_embed(quests: list, user_name: str) -> discord.Embed:
        """Create a clean, uncluttered embed for daily quests"""
        
        if not quests:
            embed = discord.Embed(
                title="📋 Daily Quests",
                description=f"**{user_name}**, you don't have any quests yet!\n\nClick the button below to generate your daily quests.",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Quest system by Riko Bot")
            return embed
        
        # Calculate stats
        total_points = 0
        potential_points = 0
        completed_count = 0
        patreon_multiplier = quests[0].get('patreon_multiplier', 1.0) if quests else 1.0
        
        for quest in quests:
            points = quest['reward_points']
            if quest.get("completed", False):
                total_points += points
                completed_count += 1
            potential_points += points
        
        # Create embed with gradient color based on completion
        completion_ratio = completed_count / len(quests) if quests else 0
        if completion_ratio == 1.0:
            color = 0x2ecc71  # Green for complete
        elif completion_ratio >= 0.5:
            color = 0x3498db  # Blue for in-progress
        else:
            color = 0x9b59b6  # Purple for starting
        
        embed = discord.Embed(
            title="📋 Daily Quests",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        # Clean header with essential info only
        completion_percentage = int(completion_ratio * 100)
        progress_bar = EmbedViews._create_progress_bar(completion_ratio, 10)
        
        header = f"**{user_name}**'s Progress\n"
        header += f"{progress_bar} **{completion_percentage}%**\n\n"
        
        # Compact stats in one line
        stats_line = f"📊 {completed_count}/{len(quests)} Complete"
        stats_line += f"　•　💎 {total_points:,}/{potential_points:,} Points"
        
        if patreon_multiplier > 1.0:
            stats_line += f"\n💖 **Patreon:** {patreon_multiplier}x points active!"
        
        embed.description = header + stats_line
        
        # Simplified quest display - clean list with concise descriptions
        quest_list = []
        for i, quest in enumerate(quests, 1):
            is_completed = quest.get("completed", False)
            current = quest.get('current_count', 0)
            target = quest['target_count']
            points = quest['reward_points']
            difficulty = quest.get('difficulty', 'medium')
            category = quest.get('category', 'general')
            
            # Status icon
            if is_completed:
                status = "✅"
            elif current > 0:
                status = "🔄"
            else:
                status = "⬜"
            
            # Difficulty and category badges
            diff_badges = {"easy": "🟢", "medium": "🟡", "hard": "🟠", "very_hard": "🔴"}
            diff_badge = diff_badges.get(difficulty, "🟡")
            category_emojis = {"posting": "📸", "rating": "⭐", "community": "👥", "special": "✨", "general": "📋"}
            cat_emoji = category_emojis.get(category, "📋")
            
            # Progress bar (compact 6 blocks)
            quest_progress = current / target if target > 0 else 0
            progress = EmbedViews._create_progress_bar(quest_progress, 6)
            
            # Add short description (trim to avoid clutter)
            description = quest.get('description', '') or ''
            if len(description) > 120:
                description = description[:117] + '…'

            # Clean multi-line format with description
            quest_line = f"{status} {cat_emoji} **{quest['name']}** {diff_badge}\n"
            if description:
                quest_line += f"　📝 _{description}_\n"
            quest_line += f"　{progress} `{current}/{target}` • **{points}** pts"
            
            quest_list.append(quest_line)
        
        # Add all quests in one clean field
        embed.add_field(
            name="📝 Your Quests",
            value="\n\n".join(quest_list),
            inline=False
        )
        
        # Minimal footer
        embed.set_footer(text="💡 Quests reset daily at midnight UTC", icon_url="https://i.imgur.com/vJGfLzH.png")
        
        return embed
    
    @staticmethod
    def _create_progress_bar(progress: float, length: int = 10) -> str:
        """Create a visual progress bar"""
        filled = int(progress * length)
        empty = length - filled
        
        # Use different styles based on progress
        if progress >= 1.0:
            return "🟩" * length
        elif progress >= 0.7:
            return "🟦" * filled + "⬜" * empty
        elif progress >= 0.4:
            return "🟨" * filled + "⬜" * empty
        else:
            return "🟥" * filled + "⬜" * empty
    
    @staticmethod
    def achievements_embed(achievements: list, user_name: str) -> discord.Embed:
        """Create an embed for user achievements"""
        embed = discord.Embed(
            title="🏆 Achievements",
            description=f"**{user_name}'s** earned achievements",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        
        if not achievements:
            embed.add_field(
                name="No Achievements Yet",
                value="Keep posting and rating images to earn achievements!",
                inline=False
            )
        else:
            total_points = sum(a['reward_points'] for a in achievements)
            
            for achievement in achievements[:10]:  # Show latest 10
                icon = achievement.get('icon', '🏆')
                points = achievement['reward_points']
                earned_date = achievement['earned_at'].strftime('%m/%d/%Y')
                
                embed.add_field(
                    name=f"{icon} {achievement['name']} ({points} pts)",
                    value=f"{achievement['description']}\nEarned: {earned_date}",
                    inline=True
                )
            
            if len(achievements) > 10:
                embed.add_field(
                    name="...",
                    value=f"And {len(achievements) - 10} more achievements!",
                    inline=False
                )
            
            embed.set_footer(text=f"Total Achievements: {len(achievements)} • Total Points: {total_points}")
        
        return embed
    
    @staticmethod
    def quest_points_leaderboard_embed(leaderboard: list, current_user_id: int) -> discord.Embed:
        """Create an embed for the quest points leaderboard"""
        embed = discord.Embed(
            title="🏆 Quest Points Leaderboard",
            description="Top users by total quest and achievement points!",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        
        if not leaderboard:
            embed.add_field(
                name="No Data Available",
                value="Be the first to complete quests and earn points!",
                inline=False
            )
        else:
            leaderboard_text = []
            medals = ["🥇", "🥈", "🥉"]
            
            for i, (user_name, user_id, total_points, completed_quests, achievements) in enumerate(leaderboard, 1):
                medal = medals[i-1] if i <= 3 else f"**{i}.**"
                
                # Highlight current user
                if user_id == current_user_id:
                    user_display = f"**{user_name}** ⭐"
                else:
                    user_display = user_name
                
                # Check for Patreon role indicator
                patreon_indicator = ""
                # We can't check role here, but we can show if they have the multiplier in their name
                
                leaderboard_text.append(
                    f"{medal} {user_display} - **{total_points:,}** pts\n"
                    f"　└ {completed_quests} quests • {achievements} achievements"
                )
            
            embed.description = "\n\n".join(leaderboard_text)
            embed.set_footer(text="💖 Patreon supporters get 1.5x points! Use /patreon to learn more")
        
        return embed
    
    @staticmethod
    def quest_completed_embed(quest: dict) -> discord.Embed:
        """Create an embed for quest completion"""
        embed = discord.Embed(
            title="🎉 Quest Completed!",
            description=f"You completed: **{quest['name']}**",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(
            name="Quest", 
            value=quest['description'], 
            inline=False
        )
        embed.add_field(
            name="Reward", 
            value=f"**{quest['reward_points']} points**", 
            inline=True
        )
        
        return embed
    
    @staticmethod
    def achievement_earned_embed(achievement: dict) -> discord.Embed:
        """Create an embed for achievement earned"""
        embed = discord.Embed(
            title="🏆 Achievement Unlocked!",
            description=f"**{achievement['name']}**",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        
        icon = achievement.get('icon', '🏆')
        embed.add_field(
            name=f"{icon} Achievement",
            value=achievement['description'],
            inline=False
        )
        embed.add_field(
            name="Reward",
            value=f"**{achievement['reward_points']} points**",
            inline=True
        )
        
        return embed
    
    @staticmethod
    def event_created_embed(event: dict) -> discord.Embed:
        """Create an embed for event creation"""
        embed = discord.Embed(
            title="🎯 New Image Contest Event!",
            description=f"**{event['name']}**",
            color=discord.Color.purple(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(
            name="📝 Description",
            value=event['description'],
            inline=False
        )
        embed.add_field(
            name="📅 Start Date",
            value=event['start_date'].strftime('%B %d, %Y at %I:%M %p'),
            inline=True
        )
        embed.add_field(
            name="🏁 End Date",
            value=event['end_date'].strftime('%B %d, %Y at %I:%M %p'),
            inline=True
        )
        embed.add_field(
            name="👤 Created by",
            value=event['created_by_name'],
            inline=True
        )
        embed.add_field(
            name="🎮 How to Participate",
            value="Post images in any image channel during the event period to automatically enter!",
            inline=False
        )
        
        embed.set_footer(text="All images posted during the event will compete for the highest score!")
        
        return embed
    
    @staticmethod
    def active_events_embed(events: list) -> discord.Embed:
        """Create an embed for active events"""
        embed = discord.Embed(
            title="🎯 Active Image Contest Events",
            color=discord.Color.purple(),
            timestamp=datetime.utcnow()
        )
        
        if not events:
            embed.description = "No active events at the moment.\nBot owners can create events with `/createevent`"
        else:
            for event in events:
                contestants_count = len(event.get('contestants', []))
                time_left = event['end_date'] - datetime.now()
                days_left = time_left.days
                hours_left = time_left.seconds // 3600
                
                time_text = f"{days_left}d {hours_left}h remaining" if days_left > 0 else f"{hours_left}h remaining"
                
                embed.add_field(
                    name=f"🎯 {event['name']}",
                    value=f"{event['description']}\n"
                          f"**Contestants:** {contestants_count}\n"
                          f"**Time left:** {time_text}",
                    inline=False
                )
        
        return embed
    
    @staticmethod
    def event_winner_embed(event: dict, winner: dict) -> discord.Embed:
        """Create an embed for event winner announcement"""
        embed = discord.Embed(
            title="🏆 Event Winner!",
            description=f"**{event['name']}** has ended!",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        
        if winner:
            embed.add_field(
                name="🥇 Winner",
                value=f"**{winner['user_name']}**",
                inline=True
            )
            embed.add_field(
                name="📊 Final Score",
                value=f"**{winner['score']} points**",
                inline=True
            )
            embed.add_field(
                name="🔗 Winning Image",
                value=f"[View Original](https://discord.com/channels/@me/{winner['message_id']})",
                inline=True
            )
        else:
            embed.add_field(
                name="No Winner",
                value="No valid contestants found for this event.",
                inline=False
            )
        
        embed.set_footer(text="Congratulations to the winner!")
        
        return embed

    @staticmethod
    def streaks_embed(streaks: dict, user_name: str) -> discord.Embed:
        """Create an embed for user streaks"""
        embed = discord.Embed(
            title="🔥 Streaks & Consistency",
            description=f"**{user_name}'s** streak statistics",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        
        # Current streaks
        current_post_streak = streaks.get("post_streak", 0)
        current_quest_streak = streaks.get("quest_streak", 0)
        
        # Max streaks
        max_post_streak = streaks.get("max_post_streak", 0)
        max_quest_streak = streaks.get("max_quest_streak", 0)
        
        # Last dates
        last_post_date = streaks.get("last_post_date")
        last_quest_date = streaks.get("last_quest_date")
        
        # Current streaks section
        embed.add_field(
            name="📷 Current Post Streak",
            value=f"**{current_post_streak}** {'day' if current_post_streak == 1 else 'days'}\n"
                  f"Last post: {last_post_date or 'Never'}",
            inline=True
        )
        
        embed.add_field(
            name="🎯 Current Quest Streak", 
            value=f"**{current_quest_streak}** {'day' if current_quest_streak == 1 else 'days'}\n"
                  f"Last quest: {last_quest_date or 'Never'}",
            inline=True
        )
        
        embed.add_field(name="‎", value="‎", inline=False)  # Spacer
        
        # Record streaks section
        embed.add_field(
            name="🏆 Best Post Streak",
            value=f"**{max_post_streak}** {'day' if max_post_streak == 1 else 'days'}",
            inline=True
        )
        
        embed.add_field(
            name="🏆 Best Quest Streak",
            value=f"**{max_quest_streak}** {'day' if max_quest_streak == 1 else 'days'}",
            inline=True
        )
        
        embed.add_field(name="‎", value="‎", inline=False)  # Spacer
        
        # Tips section
        tips = []
        if current_post_streak == 0:
            tips.append("📷 Post an image to start your posting streak!")
        if current_quest_streak == 0:
            tips.append("🎯 Complete a quest to start your quest streak!")
        if current_post_streak > 0 and current_quest_streak > 0:
            tips.append("🔥 Keep it up! Streaks unlock special achievements!")
        
        if tips:
            embed.add_field(
                name="💡 Tips",
                value="\n".join(tips),
                inline=False
            )
        
        # Streak fire emoji based on longest current streak
        max_current = max(current_post_streak, current_quest_streak)
        if max_current >= 30:
            embed.set_thumbnail(url="https://twemoji.maxcdn.com/v/13.1.0/72x72/1f525.png")  # 🔥
        elif max_current >= 7:
            embed.set_thumbnail(url="https://twemoji.maxcdn.com/v/13.1.0/72x72/2b50.png")  # ⭐
        
        embed.set_footer(text="Post images daily and complete quests to build streaks!")
        
        return embed

    @staticmethod
    def streak_milestone_embed(streak_type: str, streak_count: int, user_name: str) -> discord.Embed:
        """Create an embed for streak milestones"""
        if streak_type == "post_streak":
            title = "📷 Posting Streak Milestone!"
            description = f"**{user_name}** has posted images for **{streak_count}** days in a row!"
            color = discord.Color.blue()
            icon = "📷"
        else:  # quest_streak
            title = "🎯 Quest Streak Milestone!"
            description = f"**{user_name}** has completed quests for **{streak_count}** days in a row!"
            color = discord.Color.green()
            icon = "🎯"
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        
        # Add encouragement based on streak length
        if streak_count >= 100:
            encouragement = f"{icon} LEGENDARY STREAK! You're absolutely unstoppable!"
        elif streak_count >= 30:
            encouragement = f"{icon} Amazing dedication! Keep the momentum going!"
        elif streak_count >= 7:
            encouragement = f"{icon} Great consistency! A week of dedication!"
        else:
            encouragement = f"{icon} Nice streak! Keep it up!"
        
        embed.add_field(
            name="🔥 Keep Going!",
            value=encouragement,
            inline=False
        )
        
        return embed

    @staticmethod
    def leaderboard_embed(leaderboard_data: list, period: str = "all time") -> discord.Embed:
        """Create an embed for the leaderboard"""
        embed = discord.Embed(
            title=f"🏆 Image Leaderboard ({period.title()})",
            description="Top users by total net upvotes on their images",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        
        if not leaderboard_data:
            embed.add_field(
                name="📭 No Data",
                value="No images found for the specified period.",
                inline=False
            )
            return embed
        
        # Add leaderboard entries
        medal_emojis = ["🥇", "🥈", "🥉"]
        
        for i, (user_name, user_id, total_score, image_count) in enumerate(leaderboard_data[:10]):
            position = i + 1
            
            # Use medal emojis for top 3, numbers for others
            if position <= 3:
                position_emoji = medal_emojis[position - 1]
            else:
                position_emoji = f"{position}."
            
            # Calculate average score
            avg_score = total_score / image_count if image_count > 0 else 0
            
            embed.add_field(
                name=f"{position_emoji} {user_name}",
                value=f"**Total Score:** {total_score}\n**Images:** {image_count}\n**Avg:** {avg_score:.1f}",
                inline=True
            )
        
        embed.set_footer(text=f"📊 Based on net upvotes (👍 - 👎) • Showing top 10")
        
        return embed 
    
    @staticmethod
    def moderation_flagged_embed(moderation_data: dict) -> discord.Embed:
        """Create an embed for flagged content requiring review"""
        # Get confidence and severity
        max_confidence = moderation_data.get('max_confidence', 0)
        severity = moderation_data.get('severity', 'unknown')
        should_delete = moderation_data.get('should_delete', False)
        
        # Set color based on severity
        if severity == "high":
            color = discord.Color.red()
            severity_text = "🔴 HIGH (≥75%)"
            action_text = "Message has been deleted"
        else:  # medium
            color = discord.Color.orange()
            severity_text = "🟡 MEDIUM (50-75%)"
            action_text = "Message is still visible"
        
        # Check if dual moderation was used
        moderation_source = moderation_data.get('moderation_source', 'openai_only')
        google_confidence = moderation_data.get('google_nl_confidence', 0)
        
        description = f"AI moderation has flagged this content for manual review.\n**Combined Confidence:** {max_confidence:.1%} | **Severity:** {severity_text}"
        
        if moderation_source == "dual" and google_confidence:
            description += f"\n\n🔍 **Dual-API Check**\n• OpenAI + Google Natural Language\n• Google NL: {google_confidence:.1%}"
        
        embed = discord.Embed(
            title="⚠️ Content Flagged for Review",
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="👤 Author", value=f"<@{moderation_data['author_id']}>\n`{moderation_data['author_name']}`", inline=True)
        embed.add_field(name="📍 Channel", value=f"<#{moderation_data['channel_id']}>", inline=True)
        embed.add_field(name="🗑️ Action", value=action_text, inline=True)
        
        # Show flagged categories
        flagged_categories = []
        for category, flagged in moderation_data.get('categories', {}).items():
            if flagged:
                score = moderation_data.get('category_scores', {}).get(category, 0)
                flagged_categories.append(f"• **{category.replace('_', ' ').title()}** ({score:.2%})")
        
        if flagged_categories:
            embed.add_field(
                name="🚨 Flagged Categories", 
                value="\n".join(flagged_categories), 
                inline=False
            )
        
        # Show content (truncated if too long)
        content = moderation_data.get('content', '')
        if len(content) > 500:
            content = content[:500] + "..."
        embed.add_field(name="📝 Content", value=f"```{content}```", inline=False)
        
        embed.add_field(name="🔗 Jump to Message", value=f"[Click here]({moderation_data['jump_url']})", inline=True)
        
        embed.set_footer(text="Use buttons below to vote • 2+ whitelist = auto-approve • Majority blacklist = auto-reject")
        
        return embed
    
    @staticmethod
    def moderation_approved_embed(log_data: dict, moderator_name: str, whitelisted: bool = False) -> discord.Embed:
        """Create an embed for approved content"""
        title = "✅ Content Approved" + (" & Whitelisted" if whitelisted else "")
        embed = discord.Embed(
            title=title,
            description="The flagged content has been reviewed and approved.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="👤 Original Author", value=f"<@{log_data['author_id']}>", inline=True)
        embed.add_field(name="👮 Reviewed by", value=moderator_name, inline=True)
        embed.add_field(name="🆔 Message ID", value=f"`{log_data['message_id']}`", inline=True)
        
        if whitelisted:
            embed.add_field(name="📝 Note", value="Similar content will be auto-approved in the future.", inline=False)
        
        embed.add_field(name="🔗 Jump to Message", value=f"[Click here]({log_data['jump_url']})", inline=False)
        
        return embed
    
    @staticmethod
    def moderation_rejected_embed(log_data: dict, moderator_name: str, reason: str, blacklisted: bool = False) -> discord.Embed:
        """Create an embed for rejected content"""
        title = "❌ Content Rejected" + (" & Blacklisted" if blacklisted else "")
        embed = discord.Embed(
            title=title,
            description="The flagged content has been reviewed and rejected.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="👤 Original Author", value=f"<@{log_data['author_id']}>", inline=True)
        embed.add_field(name="👮 Reviewed by", value=moderator_name, inline=True)
        embed.add_field(name="🆔 Message ID", value=f"`{log_data['message_id']}`", inline=True)
        
        embed.add_field(name="📝 Reason", value=reason, inline=False)
        
        if blacklisted:
            embed.add_field(name="🚫 Note", value="Similar content will be automatically rejected in the future.", inline=False)
        
        embed.add_field(name="🔗 Jump to Message", value=f"[Click here]({log_data['jump_url']})", inline=False)
        
        return embed
    
    @staticmethod
    def moderation_overruled_embed(log_data: dict, admin_name: str, is_allowed: bool, reason: str) -> discord.Embed:
        """Create an embed for admin overrule"""
        title = f"⚖️ Decision Overruled - {'Approved' if is_allowed else 'Rejected'}"
        color = discord.Color.green() if is_allowed else discord.Color.red()
        
        embed = discord.Embed(
            title=title,
            description="An admin has overruled the moderation decision.",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="👤 Original Author", value=f"<@{log_data['author_id']}>", inline=True)
        embed.add_field(name="👑 Admin", value=admin_name, inline=True)
        embed.add_field(name="🆔 Message ID", value=f"`{log_data['message_id']}`", inline=True)
        
        embed.add_field(name="📝 Reason", value=reason, inline=False)
        embed.add_field(name="🔗 Jump to Message", value=f"[Click here]({log_data['jump_url']})", inline=False)
        
        # Add note about overrule power
        embed.add_field(
            name="⚖️ Admin Override", 
            value="This decision overrides any community votes and sets the final precedent for similar content.", 
            inline=False
        )
        
        return embed
    
    @staticmethod
    def moderation_blacklisted_content_embed(log_data: dict) -> discord.Embed:
        """Create an embed for when blacklisted content is detected"""
        embed = discord.Embed(
            title="🚫 Blacklisted Content Detected",
            description="A user attempted to post content that has been previously blacklisted.",
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="👤 Author", value=f"<@{log_data['author_id']}>\n`{log_data['author_name']}`", inline=True)
        embed.add_field(name="📍 Channel", value=f"<#{log_data['channel_id']}>", inline=True)
        embed.add_field(name="🚫 Action", value="Auto-rejected", inline=True)
        
        embed.add_field(name="🔗 Jump to Message", value=f"[Click here]({log_data['jump_url']})", inline=False)
        
        return embed
    
    @staticmethod
    def moderation_config_embed(guild_id: str, settings: dict) -> discord.Embed:
        """Create an embed showing current moderation configuration"""
        embed = discord.Embed(
            title="⚙️ Moderation Configuration",
            description="Current moderation system settings for this server.",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        # Status
        enabled = settings.get('moderation_enabled', False)
        embed.add_field(name="🔘 Status", value="✅ Enabled" if enabled else "❌ Disabled", inline=True)
        
        # Review role
        review_role_id = settings.get('review_role_id')
        if review_role_id:
            embed.add_field(name="👥 Review Role", value=f"<@&{review_role_id}>", inline=True)
        else:
            embed.add_field(name="👥 Review Role", value="❌ Not configured", inline=True)
        
        # Admin role
        admin_role_id = settings.get('admin_role_id')
        if admin_role_id:
            embed.add_field(name="👑 Admin Role", value=f"<@&{admin_role_id}>", inline=True)
        else:
            embed.add_field(name="👑 Admin Role", value="❌ Not configured", inline=True)
        
        # Log channel
        log_channel_id = settings.get('moderation_log_channel_id')
        if log_channel_id:
            embed.add_field(name="📋 Log Channel", value=f"<#{log_channel_id}>", inline=True)
        else:
            embed.add_field(name="📋 Log Channel", value="❌ Not configured", inline=True)
        
        embed.add_field(name="ℹ️ Note", value="Use `/modconfig` to change these settings.", inline=False)
        embed.set_footer(text=f"Guild ID: {guild_id}")
        
        return embed
    
    @staticmethod
    def moderation_stats_embed(stats: dict, days: int = 30) -> discord.Embed:
        """Create an embed showing moderation statistics"""
        embed = discord.Embed(
            title="📊 Moderation Statistics",
            description=f"Moderation activity for the last {days} days.",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="🚨 Total Flagged", value=str(stats.get('total_flagged', 0)), inline=True)
        embed.add_field(name="⏳ Pending Review", value=str(stats.get('pending_review', 0)), inline=True)
        embed.add_field(name="✅ Approved", value=str(stats.get('approved', 0)), inline=True)
        embed.add_field(name="❌ Rejected", value=str(stats.get('rejected', 0)), inline=True)
        embed.add_field(name="🚫 Blacklisted Hits", value=str(stats.get('blacklisted_hits', 0)), inline=True)
        embed.add_field(name="📝 Auto-approved", value=str(stats.get('auto_approved', 0)), inline=True)
        embed.add_field(name="⚖️ Overruled", value=str(stats.get('overruled', 0)), inline=True)
        
        # Calculate percentages
        total = stats.get('total_flagged', 0)
        if total > 0:
            accuracy = ((stats.get('approved', 0) + stats.get('rejected', 0)) / total) * 100
            embed.add_field(name="🎯 Review Rate", value=f"{accuracy:.1f}%", inline=True)
        
        return embed
    
    @staticmethod
    def inorep_check_embed(user: discord.Member, rep: int) -> discord.Embed:
        """Create an embed for checking InoRep with expanded relationship tiers"""
        
        # Expanded relationship tiers based on rep score
        if rep >= 500:
            color = 0xFFD700  # Bright gold
            status = "👑 Ino's Divine Champion"
            message = "You are a LEGEND! Ino considers you family. Your devotion is unmatched!"
            relationship = "💎 Eternal Bond"
        elif rep >= 250:
            color = 0xFF69B4  # Hot pink
            status = "💖 Ino's Soulmate"
            message = "Incredible! Ino trusts you completely. You're basically married to her at this point!"
            relationship = "💕 True Love"
        elif rep >= 150:
            color = 0xFF1493  # Deep pink
            status = "💝 Ino's Beloved"
            message = "Amazing dedication! Ino thinks about you all the time. You mean the world to her!"
            relationship = "💗 Deep Affection"
        elif rep >= 100:
            color = 0xDA70D6  # Orchid
            status = "💘 Ino's Darling"
            message = "Exceptional! Ino has fallen for you. You're truly special to her!"
            relationship = "💓 Strong Love"
        elif rep >= 75:
            color = 0xBA55D3  # Medium orchid
            status = "🌸 Ino's Precious One"
            message = "Wonderful! Ino cherishes every moment with you. You brighten her day!"
            relationship = "💖 Adoration"
        elif rep >= 50:
            color = 0x9370DB  # Medium purple
            status = "✨ Ino's Favorite Person"
            message = "Fantastic! Ino really, really likes you! You're at the top of her list!"
            relationship = "💝 Special Bond"
        elif rep >= 30:
            color = 0x7B68EE  # Medium slate blue
            status = "🌟 Ino's Trusted Ally"
            message = "Great work! Ino trusts you and enjoys your company!"
            relationship = "🤝 Close Friendship"
        elif rep >= 20:
            color = 0x00CED1  # Dark turquoise
            status = "⭐ Ino's Good Friend"
            message = "You're doing excellent! Ino considers you a real friend!"
            relationship = "😊 Friendship"
        elif rep >= 10:
            color = 0x32CD32  # Lime green
            status = "🌟 Ino's Friend"
            message = "You're doing great! Ino loves you!"
            relationship = "😄 Friendly"
        elif rep >= 5:
            color = 0x3498DB  # Blue
            status = "😊 Good Standing"
            message = "Keep being nice to Ino!"
            relationship = "🙂 Acquaintance"
        elif rep >= 1:
            color = 0xF1C40F  # Yellow
            status = "😐 Positive Neutral"
            message = "Not bad! Ino notices your efforts."
            relationship = "👋 Known"
        elif rep == 0:
            color = 0xBDC3C7  # Gray
            status = "😐 Neutral"
            message = "You're a blank slate. Ino doesn't know what to think of you yet..."
            relationship = "❓ Stranger"
        elif rep >= -5:
            color = 0xE67E22  # Orange
            status = "😕 Slightly Annoying"
            message = "Hmm... Ino is starting to find you a bit irritating."
            relationship = "😒 Annoyed"
        elif rep >= -10:
            color = 0xE74C3C  # Red
            status = "😠 On Thin Ice"
            message = "Ino is getting upset with you. Better watch yourself..."
            relationship = "💢 Irritated"
        elif rep >= -20:
            color = 0xC0392B  # Dark red
            status = "😡 Ino's Irritant"
            message = "You're really pushing it! Ino is NOT happy with you!"
            relationship = "😤 Disliked"
        elif rep >= -30:
            color = 0xA93226  # Darker red
            status = "🤬 Ino's Nuisance"
            message = "Ino really doesn't like you. You've been very rude!"
            relationship = "😠 Hostile"
        elif rep >= -50:
            color = 0x922B21  # Very dark red
            status = "💢 Ino's Nemesis"
            message = "Ino actively dislikes you! You've crossed too many lines!"
            relationship = "🚫 Enemy"
        elif rep >= -75:
            color = 0x7B241C  # Deep crimson
            status = "👿 Ino's Antagonist"
            message = "Terrible! Ino considers you a genuine problem. Why are you so mean?!"
            relationship = "⚔️ Adversary"
        elif rep >= -100:
            color = 0x641E16  # Very deep red
            status = "💀 Ino's Arch-Enemy"
            message = "Absolutely awful! Ino despises you with a passion!"
            relationship = "☠️ Sworn Enemy"
        elif rep >= -150:
            color = 0x4A0E0E  # Nearly black red
            status = "🔥 Ino's Tormentor"
            message = "You're horrible! Ino wants nothing to do with you. Redemption seems impossible!"
            relationship = "👹 Demon"
        elif rep >= -250:
            color = 0x2C0505  # Very dark maroon
            status = "⚰️ Ino's Nightmare"
            message = "Unspeakably bad! Ino has nightmares about you! How do you live with yourself?!"
            relationship = "💀 Cursed"
        else:  # rep < -250
            color = 0x000000  # Pure black
            status = "🗡️ Ino's Eternal Nemesis"
            message = "LEGENDARY LEVELS OF HATRED! Ino will never forgive you. You are beyond redemption!"
            relationship = "⚡ Apocalyptic"
        
        embed = discord.Embed(
            title=f"🎭 InoRep Score",
            description=f"**{user.display_name}'s** reputation with Ino",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="📊 Current Rep", value=f"**{rep:+d}**", inline=True)
        embed.add_field(name="🏷️ Status", value=status, inline=True)
        embed.add_field(name="💕 Relationship", value=relationship, inline=True)
        embed.add_field(name="💭 Message", value=message, inline=False)
        
        # Add progress bar
        if rep > 0:
            next_tier_thresholds = [5, 10, 20, 30, 50, 75, 100, 150, 250, 500]
            current_tier = 0
            next_tier = 5
            
            for threshold in next_tier_thresholds:
                if rep >= threshold:
                    current_tier = threshold
                else:
                    next_tier = threshold
                    break
            
            if rep < 500:
                progress = ((rep - current_tier) / (next_tier - current_tier)) * 100
                bar_length = 10
                filled = int((progress / 100) * bar_length)
                bar = "🟩" * filled + "⬜" * (bar_length - filled)
                embed.add_field(
                    name=f"📈 Progress to Next Tier ({next_tier})",
                    value=f"{bar} {progress:.1f}%",
                    inline=False
                )
        elif rep < 0:
            embed.add_field(
                name="⚠️ Recovery Tip",
                value="Post images, say nice things about Ino, and STOP chatting in image channels!",
                inline=False
            )
        
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        embed.set_footer(text="InoRep System • Track your relationship with Ino!")
        
        return embed
    
    @staticmethod
    def inorep_warned_embed(warned_user: discord.Member, warner: discord.Member, new_rep: int) -> discord.Embed:
        """Create an embed for InoRep warning"""
        embed = discord.Embed(
            title="⚠️ InoRep Warning!",
            description=f"**{warned_user.display_name}** has been warned for being rude to Ino!",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="👤 Warned User", value=f"{warned_user.mention}", inline=True)
        embed.add_field(name="👮 Warned By", value=f"{warner.mention}", inline=True)
        embed.add_field(name="📉 Rep Change", value="**-1**", inline=True)
        embed.add_field(name="📊 New Rep", value=f"**{new_rep:+d}**", inline=True)
        embed.add_field(name="💬 Reason", value="Being rude to Ino", inline=False)
        
        embed.set_thumbnail(url=warned_user.display_avatar.url if warned_user.display_avatar else None)
        embed.set_footer(text="Be nicer to Ino! (This is just for fun)")
        
        return embed
    
    @staticmethod
    def inorep_admin_add_embed(target_user: discord.Member, admin: discord.Member, amount: int, new_rep: int, reason: str) -> discord.Embed:
        """Create an embed for admin adding/removing InoRep"""
        is_positive = amount > 0
        
        embed = discord.Embed(
            title=f"{'✨' if is_positive else '⚖️'} InoRep {'Added' if is_positive else 'Removed'}",
            description=f"**{admin.display_name}** {'rewarded' if is_positive else 'penalized'} **{target_user.display_name}**",
            color=discord.Color.green() if is_positive else discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="👤 Target User", value=f"{target_user.mention}", inline=True)
        embed.add_field(name="👑 Admin", value=f"{admin.mention}", inline=True)
        embed.add_field(name="📈 Rep Change", value=f"**{amount:+d}**", inline=True)
        embed.add_field(name="📊 New Rep", value=f"**{new_rep:+d}**", inline=True)
        embed.add_field(name="📝 Reason", value=reason, inline=False)
        
        embed.set_thumbnail(url=target_user.display_avatar.url if target_user.display_avatar else None)
        embed.set_footer(text="InoRep Management • Just for fun!")
        
        return embed
    
    @staticmethod
    def inorep_leaderboard_embed(leaderboard_data: list, worst: bool = False) -> discord.Embed:
        """Create an embed for InoRep leaderboard"""
        if worst:
            title = "💀 Worst InoRep Offenders"
            description = "The people Ino dislikes the most"
            color = discord.Color.dark_red()
        else:
            title = "🌟 Best InoRep Holders"
            description = "The people Ino loves the most"
            color = discord.Color.gold()
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        
        if not leaderboard_data:
            embed.add_field(
                name="📭 No Data",
                value="No one has any InoRep yet!",
                inline=False
            )
            return embed
        
        # Add leaderboard entries
        medal_emojis = ["🥇", "🥈", "🥉"]
        
        for i, user_data in enumerate(leaderboard_data[:10]):
            position = i + 1
            
            # Use medal emojis for top 3, numbers for others
            if position <= 3:
                position_emoji = medal_emojis[position - 1]
            else:
                position_emoji = f"{position}."
            
            user_name = user_data.get('user_name', 'Unknown')
            rep = user_data.get('rep', 0)
            
            embed.add_field(
                name=f"{position_emoji} {user_name}",
                value=f"**Rep:** {rep:+d}",
                inline=True
            )
        
        embed.set_footer(text="InoRep Leaderboard • Just for fun! • Showing top 10")
        
        return embed


class QuestView(discord.ui.View):
    """Interactive view for quest command with buttons"""
    
    def __init__(self, user_id: int, quest_manager, member):
        super().__init__(timeout=300)  # 5 minute timeout
        self.user_id = user_id
        self.quest_manager = quest_manager
        self.member = member
    
    # Dropdown to view quest details
    @discord.ui.select(placeholder="📜 View quest details", min_values=1, max_values=1, options=[])
    async def quest_details_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Use `/quests` to view your own.", ephemeral=True)
                return

            # Expect value format: quest_id
            quest_id = select.values[0]
            quest_doc = self.quest_manager.user_quests_collection.find_one({
                "user_id": str(self.user_id),
                "quest_id": quest_id
            })
            if not quest_doc:
                await interaction.response.send_message("❌ Quest not found.", ephemeral=True)
                return

            # Build a rich quest detail embed
            difficulty = quest_doc.get('difficulty', 'medium')
            diff_badges = {"easy": "🟢", "medium": "🟡", "hard": "🟠", "very_hard": "🔴"}
            diff_badge = diff_badges.get(difficulty, "🟡")
            category = quest_doc.get('category', 'general')
            category_emojis = {"posting": "📸", "rating": "⭐", "community": "👥", "special": "✨", "general": "📋"}
            cat_emoji = category_emojis.get(category, "📋")

            current = quest_doc.get('current_count', 0)
            target = quest_doc.get('target_count', 0)
            progress = EmbedViews._create_progress_bar((current/target) if target else 0, 12)

            detail = discord.Embed(
                title=f"{cat_emoji} {quest_doc['name']} {diff_badge}",
                description=quest_doc.get('description', 'No description provided.'),
                color=discord.Color.purple(),
                timestamp=datetime.utcnow()
            )
            detail.add_field(name="🎯 Objective", value=f"`{current}/{target}`", inline=True)
            detail.add_field(name="💎 Reward", value=f"**{quest_doc.get('reward_points', 0)}** pts", inline=True)
            detail.add_field(name="🏷️ Type", value=f"`{quest_doc.get('quest_type', 'general')}`", inline=True)
            detail.add_field(name="📅 Date", value=f"`{quest_doc.get('date', '')}`", inline=True)
            detail.add_field(name="📈 Progress", value=progress, inline=False)
            if quest_doc.get('completed'):
                detail.add_field(name="✅ Status", value="Completed", inline=True)
            else:
                detail.add_field(name="📝 Status", value="In Progress", inline=True)

            await interaction.response.send_message(embed=detail, ephemeral=True)

        except Exception as e:
            try:
                await interaction.response.send_message(f"❌ Failed to show details: {str(e)}", ephemeral=True)
            except:
                await interaction.followup.send(f"❌ Failed to show details: {str(e)}", ephemeral=True)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, emoji="🔄")
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh quest display"""
        try:
            # Check if the user clicking is the quest owner
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "❌ These aren't your quests! Use `/quests` to view your own.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            
            # Get updated quests
            quests = await self.quest_manager.get_user_daily_quests(self.user_id)
            
            # Create updated embed
            embed = EmbedViews.daily_quests_embed(quests, interaction.user.display_name)
            
            # Update the message
            await interaction.edit_original_response(embed=embed, view=self)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to refresh: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="Leaderboard", style=discord.ButtonStyle.success, emoji="🏆")
    async def leaderboard_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show points leaderboard"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Get leaderboard
            leaderboard = await self.quest_manager.get_quest_points_leaderboard(limit=10, guild=interaction.guild)
            
            if not leaderboard:
                await interaction.followup.send(
                    "❌ No leaderboard data available yet!",
                    ephemeral=True
                )
                return
            
            # Create leaderboard embed
            embed = EmbedViews.quest_points_leaderboard_embed(leaderboard, interaction.user.id)
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to load leaderboard: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="My Stats", style=discord.ButtonStyle.secondary, emoji="📊")
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show detailed user stats"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Get user's total points
            total_points = await self.quest_manager.get_user_total_quest_points(interaction.user.id)
            
            # Get completed quests count
            completed_quests = list(self.quest_manager.user_quests_collection.find({
                "user_id": str(interaction.user.id),
                "completed": True
            }))
            
            # Get achievements count
            achievements = list(self.quest_manager.user_achievements_collection.find({
                "user_id": str(interaction.user.id)
            }))
            
            # Get current streak
            streak_data = await self.quest_manager.get_user_streaks(interaction.user.id)
            post_streak = streak_data.get('post_streak', 0) if streak_data else 0
            quest_streak = streak_data.get('quest_streak', 0) if streak_data else 0
            
            # Create stats embed
            embed = discord.Embed(
                title="📊 Your Quest Statistics",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="💎 Total Points",
                value=f"**{total_points:,}** points",
                inline=True
            )
            
            embed.add_field(
                name="✅ Quests Completed",
                value=f"**{len(completed_quests)}** quests",
                inline=True
            )
            
            embed.add_field(
                name="🏆 Achievements",
                value=f"**{len(achievements)}** earned",
                inline=True
            )
            
            embed.add_field(
                name="🔥 Post Streak",
                value=f"**{post_streak}** days",
                inline=True
            )
            
            embed.add_field(
                name="⚡ Quest Streak",
                value=f"**{quest_streak}** days",
                inline=True
            )
            
            embed.set_footer(text=f"Keep it up, {interaction.user.display_name}!")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to load stats: {str(e)}", ephemeral=True)
    
    async def on_timeout(self):
        """Disable buttons when view times out"""
        for item in self.children:
            try:
                item.disabled = True
            except:
                pass


class PurgeConfirmationView(discord.ui.View):
    """Confirmation view for purge commands"""
    
    def __init__(self, ctx, filter_func, amount: int, filter_type: str):
        super().__init__(timeout=30)
        self.ctx = ctx
        self.filter_func = filter_func
        self.amount = amount
        self.filter_type = filter_type
    
    @discord.ui.button(label="✅ Confirm Purge", style=discord.ButtonStyle.danger)
    async def confirm_purge(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Execute the purge operation"""
        try:
            # Check if user has permission
            if not interaction.user.guild_permissions.manage_messages:
                await interaction.response.send_message("❌ You don't have permission to purge messages!", ephemeral=True)
                return
            
            # Update the original message to show confirmation
            confirm_embed = discord.Embed(
                title="⏳ Purging Messages...",
                description=f"Confirmed! Purging up to {self.amount} messages...",
                color=0xf39c12
            )
            await interaction.response.edit_message(embed=confirm_embed, view=None)
            
            # Perform the purge
            purged_messages = await self.ctx.channel.purge(
                limit=self.amount,
                check=self.filter_func
            )
            
            # Create result embed
            result_embed = discord.Embed(
                title="✅ Purge Complete",
                description=f"Successfully purged **{len(purged_messages)}** messages",
                color=0x2ecc71
            )
            result_embed.add_field(name="Filter Used", value=self.filter_type.title(), inline=True)
            result_embed.add_field(name="Messages Deleted", value=str(len(purged_messages)), inline=True)
            result_embed.add_field(name="Channel", value=self.ctx.channel.mention, inline=True)
            result_embed.set_footer(text=f"Purged by {interaction.user.display_name}")
            
            # Update the message with the result
            await interaction.edit_original_response(embed=result_embed)
            
            # Log the purge
            logger.info(f"Purge executed by {interaction.user.display_name} in {self.ctx.channel.name}: {len(purged_messages)} messages deleted (filter: {self.filter_type})")
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
        except discord.Forbidden:
            error_embed = discord.Embed(
                title="❌ Permission Error",
                description="I don't have permission to delete messages in this channel!",
                color=0xe74c3c
            )
            await interaction.edit_original_response(embed=error_embed)
        except discord.HTTPException as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to purge messages: {str(e)}",
                color=0xe74c3c
            )
            await interaction.edit_original_response(embed=error_embed)
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred: {str(e)}",
                color=0xe74c3c
            )
            await interaction.edit_original_response(embed=error_embed)
            logger.error(f"Error during purge: {e}")
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_purge(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the purge operation"""
        embed = discord.Embed(
            title="❌ Purge Cancelled",
            description="The purge operation has been cancelled.",
            color=0x95a5a6
        )
        
        await interaction.response.edit_message(embed=embed, view=None)
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
    
    async def on_timeout(self):
        """Handle view timeout"""
        try:
            # Disable all buttons when timeout occurs
            for item in self.children:
                item.disabled = True
        except:
            pass 