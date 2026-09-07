"""Thank-you emails over Amazon SES, via SMTP.

SMTP rather than the SES API so this needs nothing beyond the standard
library; boto3 would be a new dependency for one call.

Privacy: the supporter's address is used to address this one message and is
never written to the database, never sent to Discord, and never logged. It
exists only for the lifetime of the request that received the webhook.
"""

import asyncio
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from web.characters import email_copy

logger = logging.getLogger(__name__)

# Deliberately loose. SES will reject anything genuinely malformed; this only
# stops obvious rubbish from reaching the network.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _mask(address: str) -> str:
    """A form safe to log: keeps the domain, drops the person."""
    local, _, domain = address.partition("@")
    return f"{local[:2]}***@{domain}" if domain else "***"


def is_configured() -> bool:
    return bool(
        os.getenv("AWS_EMAIL_SMTP_USERNAME")
        and os.getenv("AWS_EMAIL_PASS")
        and os.getenv("AWS_EMAIL_ENDPOINT")
    )


def sender() -> str:
    domain = os.getenv("AWS_EMAIL_DOMAIN", "serika.email")
    name = os.getenv("DONATION_FROM_NAME", "Ino")
    return formataddr((name, f"donations@{domain}"))


def build_message(
    to: str,
    supporter: str,
    amount: str,
    goal_title: str,
    percent: float,
    raised: str,
    target: str,
    site_url: str,
    kofi_notice: str,
) -> EmailMessage:
    """The thank-you, as a multipart text and HTML message."""
    copy = email_copy()
    subject = copy.get("subject", "Thank you for your donation")
    heading = copy.get("heading", "Thank you.")
    intro = copy.get("intro", "Your donation of {amount} has been recorded.").format(
        amount=amount
    )
    ino_note = copy.get("ino_note", "")
    riko_note = copy.get("riko_note", "")
    signoff = copy.get("signoff", "Ino")

    filled = int(max(0.0, min(percent, 100.0)) // 5)
    bar = "█" * filled + "░" * (20 - filled)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender()
    msg["To"] = to

    msg.set_content(
        f"{heading}\n\n"
        f"Hi {supporter},\n\n"
        f"{intro}\n\n"
        f"{goal_title}\n"
        f"{bar}  {percent:.1f}%\n"
        f"{raised} of {target}\n\n"
        f"Ino: {ino_note}\n"
        f"Riko: {riko_note}\n\n"
        f"{kofi_notice}\n\n"
        f"See every supporter: {site_url}/donations\n\n"
        f"{signoff}\n"
    )

    # Table-based and inline-styled, because email clients ignore most CSS.
    pct = max(0.0, min(percent, 100.0))
    msg.add_alternative(
        f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0a0708;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0a0708;padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#000;border:1px solid #241a1e;border-radius:14px;">
  <tr><td style="padding:32px 32px 8px;">
    <p style="margin:0 0 6px;font:600 12px/1.4 ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:#ff4d8d;">Donation received</p>
    <h1 style="margin:0 0 14px;font:700 30px/1.15 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#f2ecee;letter-spacing:-.02em;">{heading}</h1>
    <p style="margin:0 0 22px;font:400 16px/1.6 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#c9bfc4;">Hi {supporter}, {intro}</p>
  </td></tr>

  <tr><td style="padding:0 32px 8px;">
    <p style="margin:0 0 8px;font:600 15px/1.4 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#f2ecee;">{goal_title}</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#120d10;border-radius:999px;">
      <tr><td style="padding:0;">
        <table role="presentation" width="{pct:.0f}%" cellpadding="0" cellspacing="0" style="min-width:2%;">
          <tr><td style="height:12px;background:#ad1457;border-radius:999px;font-size:0;line-height:0;">&nbsp;</td></tr>
        </table>
      </td></tr>
    </table>
    <p style="margin:10px 0 24px;font:400 13px/1.5 ui-monospace,Menlo,monospace;color:#9b8f95;">{raised} of {target} · {percent:.1f}%</p>
  </td></tr>

  <tr><td style="padding:0 32px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-left:3px solid #4aa3ff;background:#0d0a0c;border-radius:0 8px 8px 0;margin-bottom:10px;">
      <tr><td style="padding:12px 14px;">
        <p style="margin:0 0 3px;font:600 13px/1.4 -apple-system,Segoe UI,sans-serif;color:#4aa3ff;">Ino</p>
        <p style="margin:0;font:400 14px/1.55 -apple-system,Segoe UI,sans-serif;color:#d6e8ff;">{ino_note}</p>
      </td></tr>
    </table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-left:3px solid #ad1457;background:#0d0a0c;border-radius:0 8px 8px 0;">
      <tr><td style="padding:12px 14px;">
        <p style="margin:0 0 3px;font:600 13px/1.4 -apple-system,Segoe UI,sans-serif;color:#ff4d8d;">Riko</p>
        <p style="margin:0;font:400 14px/1.55 -apple-system,Segoe UI,sans-serif;color:#ffd7e6;">{riko_note}</p>
      </td></tr>
    </table>
  </td></tr>

  <tr><td style="padding:26px 32px 0;">
    <a href="{site_url}/donations" style="display:inline-block;background:#ad1457;color:#fff;text-decoration:none;font:600 15px/1 -apple-system,Segoe UI,sans-serif;padding:14px 26px;border-radius:9px;">See every supporter</a>
  </td></tr>

  <tr><td style="padding:24px 32px 30px;">
    <p style="margin:22px 0 0;padding-top:18px;border-top:1px solid #241a1e;font:400 13px/1.6 -apple-system,Segoe UI,sans-serif;color:#9b8f95;">{kofi_notice}</p>
    <p style="margin:14px 0 0;font:400 12px/1.6 -apple-system,Segoe UI,sans-serif;color:#6f656a;">{signoff}</p>
  </td></tr>
</table>
</td></tr></table>
</body></html>""",
        subtype="html",
    )
    return msg


def _send_sync(msg: EmailMessage) -> bool:
    host = os.getenv("AWS_EMAIL_ENDPOINT", "")
    port = int(os.getenv("AWS_EMAIL_SMTP_PORT", "587") or 587)
    username = os.getenv("AWS_EMAIL_SMTP_USERNAME", "")
    password = os.getenv("AWS_EMAIL_PASS", "")

    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
                server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.starttls(context=context)
                server.login(username, password)
                server.send_message(msg)
        return True
    except Exception as e:
        # Never include the message body or recipient in the error.
        logger.error(f"SES send failed: {type(e).__name__}: {e}")
        return False


async def send_thank_you(to: Optional[str], **fields) -> bool:
    """Send the thank-you. Returns False when skipped or failed.

    `to` comes straight off the Ko-fi webhook and is not stored anywhere.
    """
    if not to or not _EMAIL_RE.match(to.strip()):
        return False
    if not is_configured():
        logger.info("SES not configured, skipping donation thank-you")
        return False

    to = to.strip()
    try:
        msg = build_message(to=to, **fields)
    except Exception as e:
        logger.error(f"Could not build thank-you email: {e}")
        return False

    sent = await asyncio.to_thread(_send_sync, msg)
    logger.info("Thank-you email %s for %s", "sent" if sent else "failed", _mask(to))
    return sent
