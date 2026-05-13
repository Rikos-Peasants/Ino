# 🦊 Ino - Riko's Shrine Guardian Bot

<div align="center">

![Discord.py](https://img.shields.io/badge/discord.py-2.3.0+-blue?logo=discord&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10+-yellow?logo=python&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-4.0+-green?logo=mongodb&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-purple)

**A feature-rich Discord bot with AI-powered content moderation, gamification, and community engagement features.**

*Ino is a shrine spirit watching over the community while her friend Riko explores the digital realm.*

[Features](#-features) • [Quick Start](#-quick-start) • [Commands](#-commands) • [Configuration](#%EF%B8%8F-configuration) • [Architecture](#-architecture)

</div>

---

## ✨ Features

### 🎮 Gamification & Engagement
| Feature | Description |
|---------|-------------|
| **🏆 Quest System** | Daily quests with varying difficulties (easy/medium/hard) and categories (posting, voting, engagement) |
| **🎖️ Achievements** | Unlockable achievements for milestones with point rewards |
| **🔥 Streak System** | Track daily activity streaks with bonus rewards |
| **📊 Leaderboards** | Comprehensive leaderboards for images, points, and achievements |
| **⭐ Patreon Perks** | 1.5x point multiplier for Patreon supporters |

### 🎨 Art Challenge System
| Feature | Description |
|---------|-------------|
| **🖌️ AI Art Challenges** | Automated art challenges using the Serika.art API |
| **🤖 AI Verification** | gemini-flash-latest-powered submission verification |
| **🏅 Challenge Types** | Remake, Tags, Mixed, and Edit challenges |
| **📅 Scheduled Drops** | Challenges drop at 02:00, 08:00, 14:00, and 20:00 UTC |
| **💰 Point Rewards** | Earn 50 base points per completed challenge |

### 🖼️ Image Voting System
| Feature | Description |
|---------|-------------|
| **👍👎 Auto-Reactions** | Automatic voting reactions on images in designated channels |
| **📈 Real-time Tracking** | Instant vote tracking with MongoDB storage |
| **🥇 Best Image Posts** | Automatic weekly, monthly, and yearly highlights |
| **📷 Historical Scanning** | Processes 90 days of historical images on startup |

### 🛡️ Moderation & Security
| Feature | Description |
|---------|-------------|
| **🔒 NSFWBAN System** | Persistent NSFW content bans with automatic role reapplication |
| **👁️ Content Moderation** | AI-powered content moderation using OpenAI and Google NL APIs |
| **🖼️ Scam Image Detection** | Mongo-backed SHA-256 and perceptual dHash detection for known scam images |
| **📝 Audit Logging** | Complete logging of all moderation actions |
| **🚫 Role Management** | Automatic role restriction enforcement |
| **💬 DM Notifications** | Users receive detailed ban/unban notifications |

### 📺 YouTube Integration
| Feature | Description |
|---------|-------------|
| **🔔 Video Announcements** | Automatic notifications for new YouTube uploads |
| **📱 Shorts Detection** | Separate role pings for videos up to 1m30s |
| **🦊 AI Announcements** | Ino's personality-driven video announcements using Gemini AI |
| **📡 RSS Monitoring** | Real-time YouTube channel monitoring |

### 🏛️ Community Features
| Feature | Description |
|---------|-------------|
| **💬 Forum Support** | Auto-pings for staff forum threads with tag-based formatting |
| **📋 Help System** | Automatic help role pings for project-related threads |
| **🎭 Dynamic Status** | Rotating humorous status messages every 2 minutes |
| **🎉 Welcome System** | Custom welcome messages for new members |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+** or **Docker**
- **MongoDB** database (local or cloud)
- **Discord Bot Token** with required intents

### Docker Deployment (Recommended)

```bash
# Clone the repository
git clone https://github.com/Rikos-Peasants/Ino.git
cd Ino

# Configure environment
cp .env.example .env
# Edit .env with your configuration

# Start the bot
./docker-start.sh

# Or use docker-compose directly
docker-compose up -d
```

### Manual Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your configuration

# Run the bot
python bot.py
```

### Docker Management Commands

```bash
docker-compose logs -f      # View live logs
docker-compose down         # Stop the bot
docker-compose restart      # Restart the bot
docker-compose ps           # Check status
```

---

## ⚙️ Configuration

### Required Environment Variables

```env
# Discord Configuration
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=your_guild_id
COMMAND_PREFIX=R!

# Role Configuration
BANNED_ROLE_ID=your_banned_role_id
RESTRICTED_ROLE_ID=your_restricted_role_id

# Database
MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/database
```

### Optional Environment Variables

```env
# AI Services
GEMINI_API_KEY=your_gemini_api_key          # For AI announcements & art verification
OPENAI_KEY=your_openai_key                   # Primary content moderation
GOOGLE_NL_API_KEY=your_google_nl_key         # Secondary moderation check
GOOGLE_TRANSLATE_API_KEY=your_translate_key  # Google Cloud Translation API
AUTO_TRANSLATE_ENABLED=true                  # Auto-reply with EN translations for non-English chat
AUTO_TRANSLATE_CHANNEL_IDS=                  # Empty means all channels
AUTO_TRANSLATE_REVIEW_CHANNEL_ID=1401293444005101568
AUTO_TRANSLATE_MIN_CONFIDENCE=0.60
AUTO_TRANSLATE_ROMANIZED_ENABLED=true        # Uses Gemini fallback for romaji/Hinglish-style text
AUTO_TRANSLATE_ROMANIZED_MIN_CHARS=8

# YouTube Integration
YOUTUBE_API_KEY=your_youtube_api_key         # YouTube Data API

# Art Challenge System
SERIKA_ART_KEY=your_serika_api_key           # Serika.art API access
SERIKA_ART_URL_BASE=https://serika.art/api/v1

# Scam Image Detection
SCAM_IMAGE_DETECTION_ENABLED=true
SCAM_IMAGE_DELETE_MATCHES=true
SCAM_IMAGE_SCAN_BOT_MESSAGES=false
SCAM_IMAGE_DHASH_DISTANCE=6
SCAM_IMAGE_MAX_ATTACHMENT_BYTES=8388608
SCAM_IMAGE_CROSS_CHANNEL_THRESHOLD=3
SCAM_IMAGE_CROSS_CHANNEL_WINDOW_SECONDS=15
SCAM_IMAGE_CROSS_CHANNEL_ALERT_COOLDOWN_MINUTES=10
SCAM_IMAGE_BURST_SCAN_ENABLED=true
SCAM_IMAGE_BURST_WINDOW_SECONDS=70
SCAM_IMAGE_BURST_DELETE_MESSAGES=false
SCAM_IMAGE_BURST_TIMEOUT_ENABLED=true
SCAM_IMAGE_BURST_TIMEOUT_SECONDS=60

# Patreon Integration
PATREON_ROLE_ID=your_patreon_role_id         # Role for Patreon supporters
```

### Required Bot Permissions

Enable these permissions when inviting the bot:
- ✅ Read Messages/View Channels
- ✅ Send Messages
- ✅ Embed Links
- ✅ Attach Files
- ✅ Add Reactions
- ✅ Manage Roles
- ✅ Use Slash Commands
- ✅ Read Message History
- ✅ Manage Messages

### Required Bot Intents

Enable these intents in the Discord Developer Portal:
- ✅ Server Members Intent
- ✅ Message Content Intent

---

## 📋 Commands

### Public Commands

| Command | Description |
|---------|-------------|
| `/uptime` | Shows how long the bot has been running |
| `/leaderboard` | View the image voting leaderboard |
| `/stats [user]` | View your or another user's image statistics |
| `/quests` | View your daily quests and progress |
| `/achievements [user]` | View achievements and unlocked badges |
| `/streak` | Check your daily activity streak |
| `/patreon` | View Patreon information and supporter perks |

### Moderation Commands

| Command | Description | Access |
|---------|-------------|--------|
| `/nsfwban <user> [reason]` | Ban user from NSFW content | Moderators/Admins |
| `/nsfwunban <user>` | Remove NSFW ban from user | Moderators/Admins |
| `/warn <user> <reason>` | Issue a warning to a user | Moderators/Admins |
| `/purge <amount>` | Delete messages in bulk | Admins |
| `/scamimage status` | View scam image detector status | Moderators/Admins |
| `/scamimage scan <image>` | Scan an image without adding it | Moderators/Admins |
| `/scamimage scan_recent [limit] [channel] [delete_matches]` | Scan recent channel images for known scam signatures | Moderators/Admins |
| `/scamimage image_timeline [user] [minutes] [per_channel_limit] [include_ignored] [post_to_modlog]` | Inspect recent image timing across server channels without actions | Moderators/Admins |
| `/scamimage burst_config [scan_enabled] [window_seconds] [delete_messages] [timeout_enabled] [timeout_seconds]` | View or update repeated-image burst actions | Moderators/Admins |
| `/scamimage add <image> <label>` | Add an image signature | Moderators/Admins |
| `/scamimage add_url` | Add an image signature from a URL modal | Moderators/Admins |
| `/scamimage bulk_recent <label> [limit] [channel]` | Bulk-add recent channel images | Moderators/Admins |
| `/scamimage list [query] [active_only]` | List scam image signatures | Moderators/Admins |
| `/scamimage enable <sha256_prefix>` | Re-enable a signature | Moderators/Admins |
| `/scamimage disable <sha256_prefix>` | Disable a signature | Moderators/Admins |
| `/scamimage recent [limit]` | View recent detections and delete status | Moderators/Admins |
| `/scamimage seed_defaults` | Import bundled known scam image signatures | Moderators/Admins |

### Manual Repeated Image Burst Test

Use `tools/repeated_image_burst_tester.py` with a normal test bot token to simulate repeated image posting across channels. It defaults to dry-run; add `--send` only when you want it to post. Set `SCAM_IMAGE_SCAN_BOT_MESSAGES=true` temporarily if you want Ino to scan the tester bot's image messages.

```bash
python tools/repeated_image_burst_tester.py --channels 123,456,789 --image-dir C:\path\to\images --delay 20 --rounds 1 --send
```

Environment variables are also supported: `DISCORD_TEST_BOT_TOKEN`, `DISCORD_TEST_CHANNEL_IDS`, `DISCORD_TEST_IMAGE_DIR`, `DISCORD_TEST_DELAY_SECONDS`, `DISCORD_TEST_ROUNDS`, and `DISCORD_TEST_MESSAGE`.

### Owner Commands

| Command | Description |
|---------|-------------|
| `/processold` | Process historical images from the past year |
| `/bestweek` | Manually post the best image of the week |
| `/bestmonth` | Manually post the best image of the month |
| `/bestyear` | Manually post the best image of the year |
| `/dbstatus` | Check MongoDB connection status |
| `/testowner` | Test bot owner permissions |
| `/synccommands` | Force sync slash commands to Discord |

### Art Challenge Commands

| Command | Description | Access |
|---------|-------------|--------|
| `/artchallenge` | View current active art challenge | Everyone |
| `/submit` | Submit artwork to the current challenge | Everyone |
| `/challengestats` | View your art challenge statistics | Everyone |

> **Note:** All commands support both text format (`R!command`) and slash format (`/command`)

---

## 🏗️ Architecture

Ino follows the **Model-View-Controller (MVC)** pattern for clean separation of concerns:

```
Ino/
├── 📄 bot.py                           # Main bot entry point & Discord client
├── 📄 config.py                        # Environment configuration management
├── 📄 sync_commands.py                 # Utility for syncing slash commands
├── 📄 requirements.txt                 # Python dependencies
├── 📄 docker-compose.yml               # Docker orchestration
├── 📄 Dockerfile                       # Container build instructions
├── 📄 docker-start.sh                  # Quick start script
│
├── 📁 models/                          # Data layer & business logic
│   ├── 📄 mongo_leaderboard_manager.py # MongoDB operations for leaderboards
│   ├── 📄 quest_manager.py             # Quest & achievement system
│   ├── 📄 art_challenge_manager.py     # Art challenge logic & AI verification
│   ├── 📄 youtube_monitor.py           # YouTube RSS monitoring & announcements
│   ├── 📄 random_announcer.py          # AI-powered random announcements
│   ├── 📄 role_manager.py              # Role management logic
│   ├── 📄 moderation_manager.py        # Content moderation system
│   ├── 📄 scam_image_manager.py        # Scam image signature detection
│   ├── 📄 mod_offline_manager.py       # Offline moderation queue
│   └── 📄 inorep_manager.py            # Reputation system
│
├── 📁 views/                           # Presentation layer
│   ├── 📄 embeds.py                    # Discord embed templates
│   ├── 📄 art_challenge_view.py        # Art challenge UI components
│   ├── 📄 moderation_view.py           # Moderation UI components
│   ├── 📄 scam_image_view.py           # Scam image management UI
│   ├── 📄 forum_thread_view.py         # Forum thread UI
│   ├── 📄 ask_staff_topic_view.py      # Staff request UI
│   ├── 📄 combined_leaderboard_view.py # Leaderboard pagination
│   └── 📄 paginated_achievements_view.py # Achievement browser
│
├── 📁 controllers/                     # Event handlers & command routing
│   ├── 📄 commands.py                  # All bot commands (hybrid)
│   ├── 📄 scam_image_controller.py     # Scam image commands and message scanner
│   ├── 📄 events.py                    # Discord event handlers
│   ├── 📄 scheduler.py                 # Scheduled tasks (best images, challenges)
│   └── 📄 security.py                  # Command permission decorators
│
├── 📄 system-prompt.txt                # Ino's personality for AI announcements
└── 📄 system-art.txt                   # Art verification AI prompt
```

### Technology Stack

| Component | Technology |
|-----------|------------|
| **Discord Library** | discord.py 2.3.0+ |
| **Database** | MongoDB with PyMongo |
| **AI Models** | gemini-flash-latest |
| **Content Moderation & Translation** | OpenAI API, Google Natural Language API, Google Cloud Translation API |
| **Art API** | Serika.art API |
| **YouTube** | YouTube Data API v3, RSS feeds |
| **Image Processing** | Pillow |
| **HTTP Client** | aiohttp, requests |
| **Containerization** | Docker, Docker Compose |

---

## 📡 API Integrations

### Google Gemini AI
Used for AI-powered features:
- YouTube video announcements with Ino's personality
- Art challenge submission verification
- Random community announcements

### Serika.art API
Used for the art challenge system:
- Fetching reference images for challenges
- Challenge tag generation
- Art content sourcing

### YouTube Data API
Used for video monitoring:
- Channel activity monitoring
- Video metadata retrieval
- Shorts detection (≤1m30s)

### Content Moderation APIs
Dual-layer content moderation:
- **Primary**: OpenAI Moderation API
- **Secondary**: Google Natural Language API

### Google Cloud Translation API
Used for auto-translating non-English chat messages to English:
- Detects the source language first
- Skips English messages
- Prompts users once before processing their messages with translation providers
- Users can change consent with `/translation opt-in` and `/translation opt-out`
- Uses Gemini as a fallback for romanized non-English text like Hindi written in Latin letters or Japanese romaji
- Replies in the format `Translated NL to EN: Hello, how is it going?`

---

## 🐳 Docker Configuration

### Resource Limits

The Docker container is configured with:
- **Memory Limit**: 512MB (256MB reserved)
- **CPU Limit**: 0.5 cores (0.25 reserved)
- **Auto-restart**: On failure (unless stopped manually)

### Health Monitoring

Built-in health checks run every 30 seconds:
- Verifies Python process is running
- Automatic container restart on failure
- 3 retries before marking unhealthy

### Logging

Structured JSON logging with:
- **Max file size**: 10MB per log file
- **Max files**: 3 (rotating)
- **Log location**: `./logs/` volume mount

---

## 🔧 Troubleshooting

### Slash Commands Not Appearing

1. **Wait for sync** - Global commands can take up to 1 hour to propagate
2. **Check permissions** - Ensure bot has "Use Slash Commands" permission
3. **Verify intents** - Enable required intents in Developer Portal
4. **Re-invite bot** with proper scopes:
   ```
   https://discord.com/api/oauth2/authorize?client_id=YOUR_BOT_ID&permissions=8&scope=bot%20applications.commands
   ```

### MongoDB Connection Issues

1. **Check URI format** - Ensure proper connection string
2. **Verify network** - Check firewall/IP whitelist settings
3. **Test credentials** - Verify username/password
4. **Check cluster status** - Ensure MongoDB cluster is running

### Bot Not Responding

1. **Check logs** - `docker-compose logs -f` or console output
2. **Verify token** - Ensure Discord token is valid
3. **Check guild ID** - Bot only responds in configured guild
4. **Restart bot** - `docker-compose restart`

---

## 🎭 Ino's Personality

Ino is a shrine spirit who has watched over the Fushimi Inari shrine for centuries. When her friend Riko became trapped in the digital realm as a fox spirit internet personality, Ino took on the role of announcing videos and watching over the community.

**Character Traits:**
- 🧘 **Composed & Wise** - Centuries of shrine-keeping bring calm rationality
- 💕 **Caring but Exasperated** - Genuinely cares, but sighs at the community's antics
- 😏 **Gently Teasing** - A little playful ribbing to keep everyone motivated
- 🛡️ **Protective** - Especially of Riko and the community's wellbeing

---

## 🤝 Contributing

Contributions are welcome! Please ensure:
1. Code follows the existing MVC architecture
2. New features include appropriate logging
3. Database operations use the existing managers
4. Commands use the hybrid command system

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Made with 💜 for the Riko community**

*"Well, well... another update complete. Now, if you'll excuse me, I have a shrine to tend to."* - Ino

</div>
