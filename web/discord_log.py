"""Forwards donation events to a Discord webhook for logging.

Supporter email and shipping addresses are never included.
"""

import logging
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)

ACCENT_COLOR = 0xAD1457


def _format_amount(donation: Dict[str, Any]) -> str:
    amount = donation.get("amount", 0.0)
    currency = donation.get("currency", "USD")
    usd = donation.get("amount_usd", amount)
    base = f"{amount:.2f} {currency}"
    if currency != "USD":
        base += f" (~${usd:.2f})"
    return base


def build_embed(donation: Dict[str, Any], progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the Discord embed for one donation."""
    is_public = donation.get("is_public")
    # A private donation is still logged so the total reconciles, but the
    # supporter's name and message stay hidden exactly as on the public page.
    name = donation.get("from_name") or "Anonymous" if is_public else "Anonymous (private)"

    fields = [
        {"name": "Amount", "value": _format_amount(donation), "inline": True},
        {"name": "Type", "value": str(donation.get("type") or "Donation"), "inline": True},
    ]

    if donation.get("tier_name"):
        fields.append({"name": "Tier", "value": str(donation["tier_name"]), "inline": True})

    if donation.get("is_subscription_payment"):
        first = donation.get("is_first_subscription_payment")
        fields.append({
            "name": "Subscription",
            "value": "First payment" if first else "Recurring",
            "inline": True,
        })

    # Requested explicitly: surface the Discord account behind the donation.
    discord_username = donation.get("discord_username")
    discord_userid = donation.get("discord_userid")
    if discord_username or discord_userid:
        value = str(discord_username or "unknown")
        if discord_userid:
            value += f"\n<@{discord_userid}> (`{discord_userid}`)"
        fields.append({"name": "Discord", "value": value, "inline": False})

    if is_public and donation.get("message"):
        message = str(donation["message"])
        if len(message) > 1000:
            message = message[:997] + "..."
        fields.append({"name": "Message", "value": message, "inline": False})

    if progress:
        fields.append({
            "name": "Goal progress",
            "value": (
                f"${progress['raised_usd']:.2f} / ${progress['goal_usd']:.2f} "
                f"({progress['percent']:.1f}%)"
            ),
            "inline": False,
        })

    return {
        "title": "New Ko-fi donation",
        "description": f"**{name}** just supported Riko.",
        "color": ACCENT_COLOR,
        "fields": fields,
        "footer": {"text": "ko-fi.com/rayenai"},
    }


async def send_donation_log(
    webhook_url: Optional[str],
    donation: Dict[str, Any],
    progress: Optional[Dict[str, Any]] = None,
    session: Optional[aiohttp.ClientSession] = None,
) -> bool:
    """POST the donation embed to the configured Discord webhook."""
    if not webhook_url:
        logger.debug("No donation log webhook configured, skipping")
        return False

    body = {
        "username": "Riko Donations",
        "embeds": [build_embed(donation, progress)],
        # Defence in depth: a supporter name or message could contain @everyone.
        "allowed_mentions": {"parse": []},
    }

    owns_session = session is None
    session = session or aiohttp.ClientSession()
    try:
        async with session.post(webhook_url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status >= 300:
                text = await resp.text()
                logger.error(f"Donation log webhook returned {resp.status}: {text[:300]}")
                return False
            return True
    except Exception as e:
        logger.error(f"Failed to send donation log webhook: {e}")
        return False
    finally:
        if owns_session:
            await session.close()
