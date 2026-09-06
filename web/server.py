"""aiohttp web server for riko.ado.wtf.

Runs inside the bot process on the same event loop, sharing the bot's MongoDB
connection. Serves the public leaderboards, the donations page, a small JSON
API, and the Ko-fi webhook receiver.
"""

import asyncio
import html
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiohttp import web

from config import Config
from web import auth
from web.characters import all_reactions
from web.discord_log import send_donation_log
from web.kofi import KofiError, parse_payload

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def _fmt_money(value: float) -> str:
    return f"{value:,.2f}"


def _relative_time(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


class RikoWebServer:
    """Owns the aiohttp runner and all request handling."""

    def __init__(self, bot):
        self.bot = bot
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._templates: Dict[str, str] = {}
        self._setup_routes()

    # ------------------------------------------------------------------
    # wiring
    # ------------------------------------------------------------------
    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/leaderboard", self.handle_leaderboard)
        self.app.router.add_get("/donations", self.handle_donations)
        self.app.router.add_get("/healthz", self.handle_health)
        self.app.router.add_get("/me", self.handle_me)
        self.app.router.add_get("/auth/login", self.handle_login)
        self.app.router.add_get("/auth/discord", self.handle_oauth_callback)
        self.app.router.add_get("/auth/logout", self.handle_logout)
        self.app.router.add_get("/api/leaderboard", self.api_leaderboard)
        self.app.router.add_get("/api/donations", self.api_donations)
        self.app.router.add_get("/api/progress", self.api_progress)
        self.app.router.add_post("/webhooks/kofi", self.handle_kofi_webhook)
        if STATIC_DIR.is_dir():
            self.app.router.add_static("/static/", STATIC_DIR, name="static")

    def _template(self, name: str) -> str:
        if name not in self._templates:
            path = TEMPLATE_DIR / name
            self._templates[name] = path.read_text(encoding="utf-8")
        return self._templates[name]

    @property
    def donation_manager(self):
        return getattr(self.bot, "donation_manager", None)

    @property
    def leaderboard_manager(self):
        return getattr(self.bot, "leaderboard_manager", None)

    async def start(self):
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, Config.WEB_HOST, Config.WEB_PORT)
        await self.site.start()
        logger.info(f"🌐 Web server listening on {Config.WEB_HOST}:{Config.WEB_PORT}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            logger.info("Web server stopped")

    # ------------------------------------------------------------------
    # data helpers
    # ------------------------------------------------------------------
    async def _get_progress(self) -> Dict[str, Any]:
        manager = self.donation_manager
        if not manager:
            return {
                "raised_usd": 0.0,
                "goal_usd": 600.0,
                "percent": 0.0,
                "percent_raw": 0.0,
                "donation_count": 0,
                "backfill_usd": 0.0,
                "goal": None,
            }
        return await manager.get_progress()

    async def _get_site_stats(self) -> Dict[str, int]:
        """Real counts only. Anything that cannot be measured is omitted."""
        manager = self.leaderboard_manager
        stats = {"members": 0, "images": 0}
        if not manager or not hasattr(manager, "collection"):
            return stats
        try:
            def _count():
                members = manager.collection.count_documents({})
                agg = list(manager.collection.aggregate(
                    [{"$group": {"_id": None, "n": {"$sum": "$image_count"}}}]
                ))
                return members, int(agg[0]["n"]) if agg else 0

            stats["members"], stats["images"] = await asyncio.to_thread(_count)
        except Exception as e:
            logger.error(f"Error computing site stats: {e}")
        return stats

    async def _get_leaderboard(self, limit: int = 25, sort_by: str = "total_score") -> List[Dict[str, Any]]:
        manager = self.leaderboard_manager
        if not manager:
            return []
        try:
            # get_leaderboard is synchronous pymongo work; keep it off the loop
            # so a slow query cannot stall the bot's gateway heartbeat.
            rows = await asyncio.to_thread(manager.get_leaderboard, limit, sort_by)
        except Exception as e:
            logger.error(f"Error loading leaderboard for web: {e}")
            return []
        return [
            {
                "rank": i + 1,
                "name": name,
                "user_id": str(user_id),
                "total_score": total_score,
                "image_count": image_count,
                "avg_score": round(total_score / image_count, 2) if image_count else 0.0,
            }
            for i, (name, user_id, total_score, image_count) in enumerate(rows)
        ]

    # ------------------------------------------------------------------
    # pages
    # ------------------------------------------------------------------
    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "bot_ready": self.bot.is_ready() if hasattr(self.bot, "is_ready") else False,
            "donations": self.donation_manager is not None,
        })

    async def handle_index(self, request: web.Request) -> web.Response:
        progress = await self._get_progress()
        goal = progress.get("goal") or {}
        top = await self._get_leaderboard(limit=5)

        rows = "\n".join(
            f'<li><span class="rank">{r["rank"]}</span>'
            f'<span class="name">{html.escape(r["name"])}</span>'
            f'<span class="score">{r["total_score"]}</span></li>'
            for r in top
        ) or '<li class="empty">No entries yet.</li>'

        stats = await self._get_site_stats()

        page = (
            self._template("index.html")
            .replace("<!--TOP_ROWS-->", rows)
            .replace("{{GOAL_TITLE}}", html.escape(goal.get("title") or "Rayen in a maid costume"))
            .replace("{{RAISED}}", _fmt_money(progress["raised_usd"]))
            .replace("{{GOAL}}", _fmt_money(progress["goal_usd"]))
            .replace("{{PERCENT}}", f"{progress['percent']:.1f}")
            .replace("{{STAT_MEMBERS}}", f"{stats['members']:,}")
            .replace("{{STAT_IMAGES}}", f"{stats['images']:,}")
            .replace("{{KOFI_URL}}", html.escape(Config.KOFI_URL, quote=True))
        )
        return web.Response(text=page, content_type="text/html")

    async def handle_leaderboard(self, request: web.Request) -> web.Response:
        sort_by = request.query.get("sort", "total_score")
        if sort_by not in ("total_score", "image_count", "avg_score"):
            sort_by = "total_score"
        entries = await self._get_leaderboard(limit=100, sort_by=sort_by)

        rows = "\n".join(
            f'<tr><td class="rank">{r["rank"]}</td>'
            f'<td class="name">{html.escape(r["name"])}</td>'
            f'<td class="num">{r["total_score"]}</td>'
            f'<td class="num">{r["image_count"]}</td>'
            f'<td class="num">{r["avg_score"]}</td></tr>'
            for r in entries
        ) or '<tr><td colspan="5" class="empty">No entries yet.</td></tr>'

        page = (
            self._template("leaderboard.html")
            .replace("<!--ROWS-->", rows)
            .replace("{{SORT_TOTAL}}", "true" if sort_by == "total_score" else "false")
            .replace("{{SORT_COUNT}}", "true" if sort_by == "image_count" else "false")
            .replace("{{SORT_AVG}}", "true" if sort_by == "avg_score" else "false")
        )
        return web.Response(text=page, content_type="text/html")

    async def handle_donations(self, request: web.Request) -> web.Response:
        progress = await self._get_progress()
        goal = progress.get("goal") or {}
        goal_id = goal.get("goal_id")
        manager = self.donation_manager
        donations = await manager.list_donations(limit=60, goal_id=goal_id) if manager else []
        top_donors = await manager.top_donors(limit=8, goal_id=goal_id) if manager else []

        donor_rows = []
        for d in donations:
            name = html.escape(d.get("from_name") or "Anonymous")
            amount = d.get("amount_usd") or 0.0
            when = _relative_time(d.get("received_at"))
            message = d.get("message")
            tier = d.get("tier_name")
            badge = f'<span class="tier">{html.escape(str(tier))}</span>' if tier else ""
            msg_html = (
                f'<p class="donor-msg">{html.escape(str(message))}</p>' if message else ""
            )
            donor_rows.append(
                f'<li class="donor">'
                f'<div class="donor-head">'
                f'<span class="donor-name">{name}</span>{badge}'
                f'<span class="donor-amount">${_fmt_money(amount)}</span>'
                f'</div>'
                f'<span class="donor-when">{when}</span>'
                f'{msg_html}'
                f'</li>'
            )

        donors_html = "\n".join(donor_rows) or (
            '<li class="donor empty">No donations recorded yet. '
            'Be the first and your name lands here.</li>'
        )

        top_html = "\n".join(
            f'<li><span class="rank">{i + 1}</span>'
            f'<span class="name">{html.escape(t["name"])}</span>'
            f'<span class="score">${_fmt_money(t["total_usd"])}</span></li>'
            for i, t in enumerate(top_donors)
        ) or '<li class="empty">Nobody yet.</li>'

        title = goal.get("title") or "Rayen in a maid costume"
        description = goal.get("description") or (
            "Hit the target and Rayen puts on the maid outfit. On camera. No takebacks."
        )
        reward = goal.get("reward") or "Rayen wears the maid costume on stream"

        # Rendered server side so the lines are real, selectable, translatable
        # markup rather than strings assembled by JavaScript.
        cast_html = "\n".join(
            f'<li class="cast-card cast--{c["key"]}">'
            f'<img class="cast-face" src="{c["img"]}" alt="" width="72" height="72" loading="lazy">'
            f'<div class="cast-body">'
            f'<p class="cast-name">{html.escape(c["name"])}'
            f'<span class="cast-role">{html.escape(c["role"])}</span></p>'
            f'<p class="cast-line">{html.escape(c["text"])}</p>'
            f'</div></li>'
            for c in all_reactions(progress["percent"])
        )

        page = (
            self._template("donations.html")
            .replace("<!--DONOR_ROWS-->", donors_html)
            .replace("<!--TOP_DONORS-->", top_html)
            .replace("<!--CAST-->", cast_html)
            .replace("{{GOAL_TITLE}}", html.escape(title))
            .replace("{{GOAL_DESC}}", html.escape(description))
            .replace("{{GOAL_REWARD}}", html.escape(reward))
            .replace("{{RAISED}}", _fmt_money(progress["raised_usd"]))
            .replace("{{GOAL}}", _fmt_money(progress["goal_usd"]))
            .replace("{{PERCENT}}", f"{progress['percent']:.1f}")
            .replace("{{COUNT}}", str(progress["donation_count"]))
            .replace("{{KOFI_URL}}", html.escape(Config.KOFI_URL, quote=True))
            # Unformatted numbers for the JSON island; the display values above
            # carry thousands separators and would not parse.
            .replace("{{RAISED_RAW}}", f"{progress['raised_usd']:.2f}")
            .replace("{{GOAL_RAW}}", f"{progress['goal_usd']:.2f}")
            .replace("{{PERCENT_RAW}}", f"{progress['percent']:.2f}")
        )
        return web.Response(text=page, content_type="text/html")

    # ------------------------------------------------------------------
    # json api
    # ------------------------------------------------------------------
    async def api_leaderboard(self, request: web.Request) -> web.Response:
        sort_by = request.query.get("sort", "total_score")
        if sort_by not in ("total_score", "image_count", "avg_score"):
            sort_by = "total_score"
        try:
            limit = max(1, min(int(request.query.get("limit", 50)), 200))
        except ValueError:
            limit = 50
        return web.json_response({"entries": await self._get_leaderboard(limit, sort_by)})

    async def api_progress(self, request: web.Request) -> web.Response:
        progress = await self._get_progress()
        goal = progress.get("goal") or {}
        # Project a safe subset. The raw goal document holds datetimes (which
        # will not serialise) plus channel, message and role ids that have no
        # business on a public endpoint.
        return web.json_response({
            "raised_usd": progress["raised_usd"],
            "goal_usd": progress["goal_usd"],
            "percent": progress["percent"],
            "percent_raw": progress.get("percent_raw", progress["percent"]),
            "donation_count": progress["donation_count"],
            "goal": {
                "name": goal.get("name"),
                "title": goal.get("title"),
                "description": goal.get("description"),
                "reward": goal.get("reward"),
                "target_usd": goal.get("target_usd"),
            } if goal else None,
        })

    async def api_donations(self, request: web.Request) -> web.Response:
        manager = self.donation_manager
        if not manager:
            return web.json_response({"donations": []})
        try:
            limit = max(1, min(int(request.query.get("limit", 50)), 200))
        except ValueError:
            limit = 50
        donations = await manager.list_donations(limit=limit)
        # Only fields safe for public consumption. Notably no email, no
        # shipping, and no Discord id.
        return web.json_response({
            "donations": [
                {
                    "name": d.get("from_name") or "Anonymous",
                    "amount_usd": d.get("amount_usd"),
                    "currency": d.get("currency"),
                    "message": d.get("message"),
                    "tier_name": d.get("tier_name"),
                    "type": d.get("type"),
                    "received_at": (
                        d["received_at"].isoformat() if d.get("received_at") else None
                    ),
                }
                for d in donations
            ]
        })

    # ------------------------------------------------------------------
    # discord oauth
    # ------------------------------------------------------------------
    def _redirect_uri(self, request: web.Request) -> str:
        """Must match a redirect registered on the Discord application."""
        host = request.headers.get("Host", "")
        if host.startswith("localhost") or host.startswith("127.0.0.1"):
            return f"http://{host}/auth/discord"
        return f"{Config.WEB_BASE_URL.rstrip('/')}/auth/discord"

    def _current_user(self, request: web.Request) -> Optional[Dict[str, Any]]:
        return auth.unsign(request.cookies.get(auth.SESSION_COOKIE), auth.SESSION_MAX_AGE)

    async def handle_login(self, request: web.Request) -> web.Response:
        if not Config.DISCORD_CLIENT_ID or not Config.DISCORD_CLIENT_SECRET:
            return web.Response(text="Discord login is not configured.", status=503)

        # A signed, short-lived state cookie is what makes the callback
        # resistant to CSRF; the value must come back unchanged.
        state = secrets.token_urlsafe(24)
        url = auth.build_authorize_url(
            Config.DISCORD_CLIENT_ID, self._redirect_uri(request), state
        )
        response = web.HTTPFound(url)
        response.set_cookie(
            auth.STATE_COOKIE,
            auth.sign({"state": state, "iat": int(time.time())}),
            max_age=auth.STATE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=request.url.scheme == "https",
        )
        return response

    async def handle_oauth_callback(self, request: web.Request) -> web.Response:
        error = request.query.get("error")
        if error:
            return web.HTTPFound("/?login=denied")

        code = request.query.get("code")
        returned_state = request.query.get("state")
        expected = auth.unsign(request.cookies.get(auth.STATE_COOKIE), auth.STATE_MAX_AGE)

        if not code or not expected or expected.get("state") != returned_state:
            logger.warning("Rejected OAuth callback with bad or missing state")
            return web.HTTPFound("/?login=failed")

        token = await auth.exchange_code(
            Config.DISCORD_CLIENT_ID,
            Config.DISCORD_CLIENT_SECRET,
            code,
            self._redirect_uri(request),
        )
        if not token:
            return web.HTTPFound("/?login=failed")

        profile = await auth.fetch_user(token)
        if not profile or not profile.get("id"):
            return web.HTTPFound("/?login=failed")

        response = web.HTTPFound("/me")
        response.set_cookie(
            auth.SESSION_COOKIE,
            auth.sign({
                "id": str(profile["id"]),
                "name": profile.get("global_name") or profile.get("username") or "Unknown",
                "avatar": profile.get("avatar"),
                "iat": int(time.time()),
            }),
            max_age=auth.SESSION_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=request.url.scheme == "https",
        )
        response.del_cookie(auth.STATE_COOKIE)
        return response

    async def handle_logout(self, request: web.Request) -> web.Response:
        response = web.HTTPFound("/")
        response.del_cookie(auth.SESSION_COOKIE)
        return response

    async def handle_me(self, request: web.Request) -> web.Response:
        user = self._current_user(request)
        if not user:
            return web.HTTPFound("/auth/login")

        user_id = user["id"]
        stats = await self._user_stats(user_id)
        rep, tier = await self._user_rep(user_id)

        rows = []
        for label, value in (
            ("Image score", stats.get("total_score")),
            ("Images posted", stats.get("image_count")),
            ("Average per image", stats.get("avg")),
            ("Leaderboard rank", stats.get("rank")),
        ):
            shown = "not ranked yet" if value in (None, "") else str(value)
            rows.append(
                f'<div class="stat-row"><span>{label}</span><strong>{html.escape(shown)}</strong></div>'
            )

        page = (
            self._template("me.html")
            .replace("{{NAME}}", html.escape(user["name"]))
            .replace("{{AVATAR}}", html.escape(auth.avatar_url(user_id, user.get("avatar")), quote=True))
            .replace("{{REP}}", f"{rep:,}")
            .replace("{{REP_STATUS}}", html.escape(str(tier.get("status", ""))))
            .replace("{{REP_RELATIONSHIP}}", html.escape(str(tier.get("relationship", ""))))
            .replace("{{REP_MESSAGE}}", html.escape(str(tier.get("message", ""))))
            .replace("{{REP_COLOR}}", f"#{int(tier.get('color', 0xAD1457)):06x}")
            .replace("<!--STAT_ROWS-->", "\n".join(rows))
        )
        return web.Response(text=page, content_type="text/html")

    async def _user_rep(self, user_id: str):
        """InoRep total plus the tier it falls in."""
        from models.inorep_status import get_inorep_tier

        manager = self.leaderboard_manager
        inorep = getattr(manager, "inorep_manager", None) if manager else None
        if not inorep:
            return 0, get_inorep_tier(0)
        try:
            rep = await inorep.get_user_rep(str(user_id), str(Config.GUILD_ID))
        except Exception as e:
            logger.error(f"Error reading InoRep for {user_id}: {e}")
            rep = 0
        return rep, get_inorep_tier(rep, int(user_id) if str(user_id).isdigit() else None)

    async def _user_stats(self, user_id: str) -> Dict[str, Any]:
        manager = self.leaderboard_manager
        if not manager or not hasattr(manager, "collection"):
            return {}
        try:
            def _lookup():
                doc = manager.collection.find_one({"user_id": str(user_id)})
                if not doc:
                    return {}
                score = doc.get("total_score", 0)
                count = doc.get("image_count", 0)
                # Rank is how many people sit strictly above this score.
                rank = manager.collection.count_documents({"total_score": {"$gt": score}}) + 1
                return {
                    "total_score": score,
                    "image_count": count,
                    "avg": round(score / count, 2) if count else 0,
                    "rank": f"#{rank}",
                }

            return await asyncio.to_thread(_lookup)
        except Exception as e:
            logger.error(f"Error reading user stats for {user_id}: {e}")
            return {}

    # ------------------------------------------------------------------
    # ko-fi webhook
    # ------------------------------------------------------------------
    async def handle_kofi_webhook(self, request: web.Request) -> web.Response:
        try:
            post = await request.post()
            raw = post.get("data")
        except Exception as e:
            logger.error(f"Could not read Ko-fi webhook body: {e}")
            return web.json_response({"error": "bad request"}, status=400)

        if raw is None:
            # Not the documented shape, but tolerate a raw JSON body so manual
            # testing with curl -d @file.json works.
            try:
                raw = (await request.text()) or ""
            except Exception:
                raw = ""

        if not raw:
            return web.json_response({"error": "missing data field"}, status=400)

        try:
            payload = parse_payload(str(raw), Config.KOFI_VERIFICATION_TOKEN)
        except KofiError as e:
            logger.warning(f"Rejected Ko-fi webhook: {e}")
            return web.json_response({"error": str(e)}, status=401)

        manager = self.donation_manager
        if not manager:
            logger.error("Ko-fi webhook received but donation manager is unavailable")
            # 503 so Ko-fi retries once the bot is healthy again.
            return web.json_response({"error": "donations unavailable"}, status=503)

        donation = await manager.record_donation(payload)
        if donation is None:
            # Already recorded. Ko-fi only stops retrying on a 200, so this
            # must succeed rather than report a conflict.
            return web.json_response({"status": "duplicate"})

        progress = await manager.get_progress()

        # Fan out without blocking the 200. Ko-fi retries anything slower than
        # its timeout, which would double-post to Discord.
        asyncio.create_task(self._announce_donation(donation, progress))

        return web.json_response({"status": "ok"})

    async def _announce_donation(self, donation: Dict[str, Any], progress: Dict[str, Any]):
        """Log to Discord and refresh the in-server progress bar."""
        try:
            await send_donation_log(Config.DONATION_LOG_WEBHOOK_URL, donation, progress)
        except Exception as e:
            logger.error(f"Error sending donation log: {e}")

        controller = getattr(self.bot, "donation_controller", None)
        if controller:
            try:
                await controller.refresh_progress_message(donation=donation)
            except Exception as e:
                logger.error(f"Error refreshing donation progress message: {e}")
