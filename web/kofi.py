"""Parsing and verification for Ko-fi webhook deliveries.

Ko-fi POSTs `application/x-www-form-urlencoded` with a single `data` field
holding the payment as a JSON string. The payload carries a plain-text
`verification_token` which is the only authentication available.
"""

import hmac
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Ko-fi documents these four. Historic payloads and the docs' own example also
# use "Donation", so it is accepted rather than rejected as unknown.
KNOWN_TYPES = {"Donation", "Tip", "Subscription", "Commission", "Shop Order"}


class KofiError(Exception):
    """Raised when a webhook body cannot be trusted or understood."""


def verify_token(received: Optional[str], expected: Optional[str]) -> bool:
    """Constant-time comparison of the Ko-fi verification token."""
    if not expected:
        # Refuse to accept anything when no token is configured; otherwise a
        # misconfigured deploy would silently accept forged donations.
        logger.error("KOFI_VERIFICATION_TOKEN is not configured, rejecting webhook")
        return False
    if not received:
        return False
    return hmac.compare_digest(str(received), str(expected))


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _coerce_amount(value: Any) -> float:
    """Ko-fi sends amount as a string like "3.00"."""
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        logger.warning("Unparseable Ko-fi amount %r, treating as 0", value)
        return 0.0


def parse_payload(raw_data: str, expected_token: Optional[str]) -> Dict[str, Any]:
    """Decode and verify one Ko-fi `data` blob.

    Returns a normalised dict. Raises KofiError if the JSON is malformed or the
    verification token does not match.
    """
    try:
        payload = json.loads(raw_data)
    except (TypeError, ValueError) as e:
        raise KofiError(f"malformed JSON in data field: {e}") from e

    if not isinstance(payload, dict):
        raise KofiError("data field did not decode to an object")

    if not verify_token(payload.get("verification_token"), expected_token):
        raise KofiError("verification token mismatch")

    message_id = payload.get("message_id")
    if not message_id:
        raise KofiError("payload has no message_id")

    kofi_type = payload.get("type") or "Donation"
    if kofi_type not in KNOWN_TYPES:
        # Forward-compatible: log it but still record the payment.
        logger.warning("Unrecognised Ko-fi type %r, recording anyway", kofi_type)

    return {
        "message_id": str(message_id),
        "kofi_transaction_id": payload.get("kofi_transaction_id"),
        "type": kofi_type,
        "is_public": _coerce_bool(payload.get("is_public")),
        "from_name": payload.get("from_name"),
        "message": payload.get("message"),
        "amount": _coerce_amount(payload.get("amount")),
        "currency": (payload.get("currency") or "USD").upper(),
        "tier_name": payload.get("tier_name"),
        "is_subscription_payment": _coerce_bool(payload.get("is_subscription_payment")),
        "is_first_subscription_payment": _coerce_bool(payload.get("is_first_subscription_payment")),
        "discord_username": payload.get("discord_username"),
        "discord_userid": payload.get("discord_userid"),
        "timestamp": payload.get("timestamp"),
        "url": payload.get("url"),
        # `email` and `shipping` are deliberately dropped here and never
        # returned to callers, so no downstream code can persist or leak them.
    }
