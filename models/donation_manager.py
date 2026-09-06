"""MongoDB-backed store for Ko-fi donations and fundraising goals.

Goals live in their own collection with every detail attached: target, copy,
reward, the channel and message that display them, announcement settings and a
manual backfill. One goal is active at a time; incoming donations are stamped
with whichever goal was active when they landed, so switching goals never
rewrites history.

Privacy note: Ko-fi webhooks carry a supporter `email` and, for shop orders, a
full postal `shipping` address. Neither is ever persisted or forwarded by this
module.
"""

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_GOAL_USD = 600.0

# Ko-fi reports the supporter's currency, not the creator's. Totals are tracked
# in USD, so non-USD amounts are converted with this table. Override any rate
# with e.g. KOFI_RATE_EUR=1.08. Unknown currencies fall through at 1:1 and are
# logged, which keeps the total approximately right instead of dropping the
# donation entirely.
_DEFAULT_RATES_TO_USD = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "AUD": 0.65,
    "NZD": 0.60, "JPY": 0.0067, "SEK": 0.095, "NOK": 0.092, "DKK": 0.145,
    "CHF": 1.13, "PLN": 0.25, "BRL": 0.18, "MXN": 0.058, "INR": 0.012,
    "SGD": 0.74, "HKD": 0.128, "ZAR": 0.055,
}


def rate_to_usd(currency: Optional[str]) -> float:
    """Resolve a conversion rate for `currency`, preferring an env override."""
    code = (currency or "USD").strip().upper() or "USD"
    override = os.getenv(f"KOFI_RATE_{code}")
    if override:
        try:
            return float(override)
        except ValueError:
            logger.warning("Ignoring non-numeric KOFI_RATE_%s=%r", code, override)
    if code not in _DEFAULT_RATES_TO_USD:
        logger.warning("No USD conversion rate for currency %s, treating as 1:1", code)
        return 1.0
    return _DEFAULT_RATES_TO_USD[code]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "goal"


class DonationManager:
    """Donations, goals, and everything the bar and the website read."""

    def __init__(self, db):
        self.db = db
        self.donations = db["donations"]
        self.goals = db["donation_goals"]
        self.settings = db["donation_settings"]
        self._ensure_indexes()

    def _ensure_indexes(self):
        try:
            # Ko-fi retries the same message_id until it gets a 200, so this
            # unique index is what makes webhook delivery idempotent.
            self.donations.create_index("message_id", unique=True)
            self.donations.create_index([("received_at", -1)])
            self.donations.create_index([("goal_id", 1), ("received_at", -1)])
            self.donations.create_index([("is_public", 1), ("received_at", -1)])
            self.goals.create_index("goal_id", unique=True)
            self.goals.create_index([("is_active", 1)])
            self.settings.create_index("key", unique=True)
            logger.info("Donation collections indexed")
        except Exception as e:
            logger.error(f"Failed to create donation indexes: {e}")

    # ------------------------------------------------------------------
    # generic settings
    # ------------------------------------------------------------------
    def _get_setting_sync(self, key: str, default: Any) -> Any:
        doc = self.settings.find_one({"key": key})
        if not doc:
            return default
        value = doc.get("value")
        return default if value is None else value

    def _set_setting_sync(self, key: str, value: Any) -> None:
        self.settings.update_one(
            {"key": key},
            {"$set": {"key": key, "value": value, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    async def get_setting(self, key: str, default: Any = None) -> Any:
        try:
            return await asyncio.to_thread(self._get_setting_sync, key, default)
        except Exception as e:
            logger.error(f"Error reading donation setting {key}: {e}")
            return default

    async def set_setting(self, key: str, value: Any) -> bool:
        try:
            await asyncio.to_thread(self._set_setting_sync, key, value)
            return True
        except Exception as e:
            logger.error(f"Error writing donation setting {key}: {e}")
            return False

    # ------------------------------------------------------------------
    # goals
    # ------------------------------------------------------------------
    @staticmethod
    def _blank_goal() -> Dict[str, Any]:
        """Shape of a goal document, with the defaults a fresh one gets."""
        return {
            "goal_id": uuid.uuid4().hex[:12],
            "name": "maidmaster",
            "title": "Rayen in a maid costume",
            "description": "",
            "reward": "",
            "target_usd": DEFAULT_GOAL_USD,
            "backfill_usd": 0.0,
            "is_active": True,
            "channel_id": None,
            "message_id": None,
            "category_id": None,
            "announce": True,
            "ping_role_id": None,
            "bar_title": "MAIDMASTER",
            "bar_subtitle": None,
            "created_at": datetime.now(timezone.utc),
            "created_by": None,
            "completed_at": None,
        }

    def _create_goal_sync(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        doc = self._blank_goal()
        doc.update({k: v for k, v in fields.items() if v is not None})
        doc["name"] = slugify(doc.get("name") or doc.get("title") or "goal")
        if doc.get("is_active"):
            # Exactly one goal is active at a time.
            self.goals.update_many({"is_active": True}, {"$set": {"is_active": False}})
        self.goals.insert_one(doc)
        doc.pop("_id", None)
        return doc

    async def create_goal(self, **fields) -> Optional[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(self._create_goal_sync, fields)
        except Exception as e:
            logger.error(f"Error creating goal: {e}")
            return None

    def _update_goal_sync(self, goal_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        update = {k: v for k, v in fields.items() if v is not None}
        if not update:
            return self.goals.find_one({"goal_id": goal_id}, {"_id": 0})
        if "name" in update:
            update["name"] = slugify(update["name"])
        update["updated_at"] = datetime.now(timezone.utc)
        self.goals.update_one({"goal_id": goal_id}, {"$set": update})
        return self.goals.find_one({"goal_id": goal_id}, {"_id": 0})

    async def update_goal(self, goal_id: str, **fields) -> Optional[Dict[str, Any]]:
        """Update a goal. Passing None for a field leaves it unchanged."""
        try:
            return await asyncio.to_thread(self._update_goal_sync, goal_id, fields)
        except Exception as e:
            logger.error(f"Error updating goal {goal_id}: {e}")
            return None

    def _clear_goal_field_sync(self, goal_id: str, field: str) -> None:
        """Explicitly null a field, which update_goal cannot do by design."""
        self.goals.update_one({"goal_id": goal_id}, {"$set": {field: None}})

    async def clear_goal_field(self, goal_id: str, field: str) -> bool:
        try:
            await asyncio.to_thread(self._clear_goal_field_sync, goal_id, field)
            return True
        except Exception as e:
            logger.error(f"Error clearing {field} on goal {goal_id}: {e}")
            return False

    async def get_goal(self, goal_id: str) -> Optional[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(
                lambda: self.goals.find_one({"goal_id": goal_id}, {"_id": 0})
            )
        except Exception as e:
            logger.error(f"Error reading goal {goal_id}: {e}")
            return None

    async def get_active_goal(self) -> Optional[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(
                lambda: self.goals.find_one({"is_active": True}, {"_id": 0})
            )
        except Exception as e:
            logger.error(f"Error reading active goal: {e}")
            return None

    async def list_goals(self, limit: int = 25) -> List[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(
                lambda: list(self.goals.find({}, {"_id": 0}).sort("created_at", -1).limit(limit))
            )
        except Exception as e:
            logger.error(f"Error listing goals: {e}")
            return []

    def _activate_sync(self, goal_id: str) -> bool:
        self.goals.update_many({"is_active": True}, {"$set": {"is_active": False}})
        return self.goals.update_one(
            {"goal_id": goal_id}, {"$set": {"is_active": True}}
        ).matched_count > 0

    async def activate_goal(self, goal_id: str) -> bool:
        try:
            return await asyncio.to_thread(self._activate_sync, goal_id)
        except Exception as e:
            logger.error(f"Error activating goal {goal_id}: {e}")
            return False

    async def delete_goal(self, goal_id: str) -> bool:
        """Remove a goal. Donations stamped with it are left untouched."""
        try:
            return await asyncio.to_thread(
                lambda: self.goals.delete_one({"goal_id": goal_id}).deleted_count > 0
            )
        except Exception as e:
            logger.error(f"Error deleting goal {goal_id}: {e}")
            return False

    async def ensure_default_goal(self) -> Dict[str, Any]:
        """Return the active goal, creating the default one if none exists."""
        goal = await self.get_active_goal()
        if goal:
            return goal
        created = await self.create_goal(
            name="maidmaster",
            title="Rayen in a maid costume",
            description=(
                "Hit the target and Rayen puts on the maid outfit. "
                "On camera. No takebacks."
            ),
            reward="Rayen wears the maid costume on stream",
            target_usd=DEFAULT_GOAL_USD,
            bar_title="MAIDMASTER",
        )
        return created or self._blank_goal()

    # ------------------------------------------------------------------
    # donations
    # ------------------------------------------------------------------
    def _record_sync(self, doc: Dict[str, Any]) -> bool:
        """Insert a donation. Returns False if this message_id was already stored."""
        from pymongo.errors import DuplicateKeyError

        try:
            self.donations.insert_one(doc)
            return True
        except DuplicateKeyError:
            return False

    async def record_donation(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Persist a parsed Ko-fi payload against the currently active goal.

        Returns the stored document on first receipt, or None if this
        `message_id` has already been recorded (a Ko-fi retry).
        """
        amount = payload.get("amount") or 0.0
        currency = payload.get("currency") or "USD"
        is_public = bool(payload.get("is_public"))
        goal = await self.get_active_goal()

        doc = {
            "message_id": payload.get("message_id"),
            "kofi_transaction_id": payload.get("kofi_transaction_id"),
            "goal_id": goal.get("goal_id") if goal else None,
            "type": payload.get("type") or "Donation",
            "is_public": is_public,
            # A private donation still counts toward the total, but its name and
            # message must never surface. Drop them at write time rather than
            # relying on every read path to filter correctly.
            "from_name": (payload.get("from_name") or "Anonymous") if is_public else None,
            "message": (payload.get("message") or None) if is_public else None,
            "amount": float(amount),
            "currency": currency,
            "amount_usd": round(float(amount) * rate_to_usd(currency), 2),
            "tier_name": payload.get("tier_name"),
            "is_subscription_payment": bool(payload.get("is_subscription_payment")),
            "is_first_subscription_payment": bool(payload.get("is_first_subscription_payment")),
            "discord_username": payload.get("discord_username"),
            "discord_userid": payload.get("discord_userid"),
            "kofi_timestamp": payload.get("timestamp"),
            "received_at": datetime.now(timezone.utc),
        }

        try:
            inserted = await asyncio.to_thread(self._record_sync, doc)
        except Exception as e:
            logger.error(f"Error recording donation: {e}")
            return None

        if not inserted:
            logger.info(f"Duplicate Ko-fi message_id {doc['message_id']}, ignoring retry")
            return None

        doc.pop("_id", None)
        return doc

    def _totals_sync(self, goal_id: Optional[str]) -> Dict[str, Any]:
        match = {"goal_id": goal_id} if goal_id else {}
        pipeline = [
            {"$match": match},
            {"$group": {"_id": None, "total_usd": {"$sum": "$amount_usd"}, "count": {"$sum": 1}}},
        ]
        result = list(self.donations.aggregate(pipeline))
        if not result:
            return {"total_usd": 0.0, "count": 0}
        return {
            "total_usd": float(result[0].get("total_usd") or 0.0),
            "count": int(result[0].get("count") or 0),
        }

    async def get_progress(self, goal_id: Optional[str] = None) -> Dict[str, Any]:
        """Everything the progress bar and the web page need, in one call."""
        try:
            goal = await (self.get_goal(goal_id) if goal_id else self.get_active_goal())
            if not goal:
                goal = self._blank_goal()
                goal["goal_id"] = None

            totals = await asyncio.to_thread(self._totals_sync, goal.get("goal_id"))
            target = float(goal.get("target_usd") or DEFAULT_GOAL_USD)
            backfill = float(goal.get("backfill_usd") or 0.0)
        except Exception as e:
            logger.error(f"Error computing donation progress: {e}")
            return {
                "raised_usd": 0.0, "goal_usd": DEFAULT_GOAL_USD, "percent": 0.0,
                "percent_raw": 0.0, "donation_count": 0, "backfill_usd": 0.0,
                "goal": None,
            }

        raised = round(totals["total_usd"] + backfill, 2)
        percent = (raised / target * 100.0) if target > 0 else 0.0
        return {
            "raised_usd": raised,
            "goal_usd": target,
            # Callers render this directly; clamping here keeps a bar that has
            # exceeded its goal from overflowing its track.
            "percent": round(min(percent, 100.0), 2),
            "percent_raw": round(percent, 2),
            "donation_count": totals["count"],
            "backfill_usd": backfill,
            "goal": goal,
        }

    def _list_sync(self, limit: int, public_only: bool, goal_id: Optional[str]) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if public_only:
            query["is_public"] = True
        if goal_id:
            query["goal_id"] = goal_id
        cursor = self.donations.find(query, {"_id": 0}).sort("received_at", -1).limit(limit)
        return list(cursor)

    async def list_donations(
        self, limit: int = 50, public_only: bool = True, goal_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(self._list_sync, limit, public_only, goal_id)
        except Exception as e:
            logger.error(f"Error listing donations: {e}")
            return []

    def _top_sync(self, limit: int, goal_id: Optional[str]) -> List[Dict[str, Any]]:
        match: Dict[str, Any] = {"is_public": True, "from_name": {"$ne": None}}
        if goal_id:
            match["goal_id"] = goal_id
        pipeline = [
            {"$match": match},
            {"$group": {"_id": "$from_name", "total_usd": {"$sum": "$amount_usd"}, "count": {"$sum": 1}}},
            {"$sort": {"total_usd": -1}},
            {"$limit": limit},
        ]
        return [
            {
                "name": row["_id"],
                "total_usd": round(float(row.get("total_usd") or 0.0), 2),
                "count": int(row.get("count") or 0),
            }
            for row in self.donations.aggregate(pipeline)
        ]

    async def top_donors(self, limit: int = 10, goal_id: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(self._top_sync, limit, goal_id)
        except Exception as e:
            logger.error(f"Error computing top donors: {e}")
            return []
