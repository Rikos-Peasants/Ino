"""Thank-you emails over Amazon SES, via SMTP.

SMTP rather than the SES API so this needs nothing beyond the standard
library; boto3 would be a new dependency for one call.

Privacy: the supporter's address is used to address this one message and is
never written to the database, never sent to Discord, and never logged. It
exists only for the lifetime of the request that received the webhook.
"""

import asyncio
import html
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Optional

from web.characters import CHARACTERS, email_copy, text as ctext

IMG_DIR = Path(__file__).resolve().parent / "static" / "img"

# Site tokens, inlined. Email clients ignore stylesheets and most <style>.
CANVAS = "#000000"
SURFACE = "#0a0708"
SURFACE_2 = "#120d10"
LINE = "#241a1e"
INK = "#f2ecee"
INK_SOFT = "#9b8f95"
ACCENT = "#ad1457"
ACCENT_BRIGHT = "#d82a75"
ACCENT_TEXT = "#ff4d8d"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'

FACES = {
    "ino": ("ino.png", "face-ino"),
    "riko": ("riko-face.png", "face-riko"),
    "yura": ("yura.png", "face-yura"),
}

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


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _face_html(key: str, meta: dict) -> str:
    """Portrait if the file exists, otherwise the same monogram the site uses."""
    filename, cid = FACES.get(key, ("", ""))
    if filename and (IMG_DIR / filename).is_file():
        return (
            f'<img src="cid:{cid}" alt="" width="56" height="56" '
            f'style="display:block;width:56px;height:56px;border:0;'
            f'border-radius:10px;background:{SURFACE_2};">'
        )
    accent = meta.get("accent", ACCENT)
    mono = _esc(meta.get("monogram") or key[:1].upper())
    return (
        f'<table role="presentation" width="56" height="56" cellpadding="0" cellspacing="0" '
        f'style="width:56px;height:56px;background:{SURFACE_2};border-radius:10px;">'
        f'<tr><td width="56" height="56" align="center" valign="middle" '
        f'style="width:56px;height:56px;font:700 22px/56px {FONT};color:{accent};">{mono}</td></tr>'
        f'</table>'
    )


def _voice_card(key: str, note: str) -> str:
    meta = CHARACTERS.get(key, {})
    name = _esc(meta.get("name") or key.title())
    role = _esc(meta.get("role") or "")
    accent = meta.get("accent", ACCENT)
    line_color = {"ino": "#d6e8ff", "riko": "#ffd7e6", "yura": "#e0d4ff"}.get(key, INK)
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="margin:0 0 10px;background:{SURFACE};border:1px solid {LINE};
              border-left:3px solid {accent};border-radius:12px;">
  <tr>
    <td width="56" valign="top" style="padding:16px 0 16px 16px;">{_face_html(key, meta)}</td>
    <td valign="top" style="padding:16px 16px 16px 14px;">
      <p style="margin:0 0 4px;font:700 15px/1.3 {FONT};color:{INK};">
        {name}
        <span style="padding-left:8px;font:400 12px/1.3 {MONO};letter-spacing:.03em;
                     text-transform:lowercase;color:{INK_SOFT};">{role}</span>
      </p>
      <p style="margin:0;font:400 14px/1.55 {FONT};color:{line_color};">{_esc(note)}</p>
    </td>
  </tr>
</table>"""


def _progress_bar(percent: float) -> str:
    pct = max(0.0, min(float(percent), 100.0))
    fill = f"{max(pct, 2.0):.0f}%" if pct > 0 else "0%"
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{SURFACE_2};border:1px solid {LINE};border-radius:28px;">
  <tr>
    <td style="padding:0;">
      <table role="presentation" width="{fill}" cellpadding="0" cellspacing="0">
        <tr>
          <td style="height:18px;background:{ACCENT};background:linear-gradient(180deg,{ACCENT_BRIGHT},{ACCENT});
                     border-radius:28px;font-size:0;line-height:0;">&nbsp;</td>
        </tr>
      </table>
    </td>
  </tr>
</table>"""


def _html_body(
    *,
    supporter: str,
    heading: str,
    eyebrow: str,
    intro: str,
    goal_title: str,
    goal_blurb: str,
    percent: float,
    raised: str,
    target: str,
    ino_note: str,
    riko_note: str,
    yura_note: str,
    kofi_notice: str,
    signoff: str,
    cta: str,
    site_url: str,
    preheader: str,
) -> str:
    donations = f"{site_url}/donations"
    pct = max(0.0, min(float(percent), 100.0))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark only">
<meta name="supported-color-schemes" content="dark only">
<title>{_esc(heading)}</title>
<style>
  :root {{ color-scheme: dark only; }}
  body {{ background-color: {CANVAS} !important; }}
</style>
</head>
<body style="margin:0;padding:0;background:{CANVAS};color:{INK};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{CANVAS};">
  {_esc(preheader)}
  {"&nbsp;&zwnj;" * 40}
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CANVAS}"
       style="background:{CANVAS};margin:0;padding:0;">
<tr><td align="center" bgcolor="{CANVAS}" style="background:{CANVAS};padding:0;">
<!--[if mso]><table role="presentation" width="560"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="max-width:560px;width:100%;background:{CANVAS};">

  <tr><td style="padding:28px 28px 18px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td valign="middle">
          <table role="presentation" cellpadding="0" cellspacing="0">
            <tr>
              <td valign="middle" style="padding-right:10px;">
                <img src="cid:ino-mark" alt="Ino" width="34" height="34"
                     style="display:block;width:34px;height:34px;border:0;">
              </td>
              <td valign="middle" style="font:700 17px/1 {FONT};letter-spacing:-.02em;color:{INK};">
                Ino
              </td>
            </tr>
          </table>
        </td>
        <td valign="middle" align="right"
            style="font:500 13px/1 {FONT};color:{INK_SOFT};">donations</td>
      </tr>
    </table>
  </td></tr>

  <tr><td style="padding:0 28px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td style="height:1px;background:{LINE};font-size:0;line-height:0;">&nbsp;</td></tr>
    </table>
  </td></tr>

  <tr><td style="padding:28px 28px 8px;">
    <p style="margin:0 0 10px;font:600 11px/1.4 {MONO};letter-spacing:.14em;
              text-transform:uppercase;color:{ACCENT_TEXT};">{_esc(eyebrow)}</p>
    <h1 style="margin:0 0 14px;font:700 34px/1.08 {FONT};letter-spacing:-.03em;color:{INK};">
      {_esc(heading)}
    </h1>
    <p style="margin:0;font:400 16px/1.6 {FONT};color:{INK_SOFT};">
      Hi {_esc(supporter)}. {_esc(intro)}
    </p>
  </td></tr>

  <tr><td style="padding:22px 28px 8px;">
    <p style="margin:0 0 6px;font:600 11px/1.4 {MONO};letter-spacing:.1em;
              text-transform:uppercase;color:{ACCENT_TEXT};">Current goal</p>
    <p style="margin:0 0 16px;font:700 22px/1.2 {FONT};letter-spacing:-.02em;color:{INK};">
      {_esc(goal_title)}
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;">
      <tr>
        <td valign="bottom" style="font:700 42px/1 {FONT};letter-spacing:-.04em;color:{INK};padding-right:10px;">
          {_esc(raised)}
        </td>
        <td valign="bottom" style="font:400 16px/1.2 {FONT};color:{INK_SOFT};padding-bottom:4px;">
          &nbsp;of {_esc(target)}
        </td>
      </tr>
    </table>
    {_progress_bar(pct)}
    <p style="margin:12px 0 0;font:400 13px/1.5 {MONO};color:{INK_SOFT};">{pct:.1f}%</p>
    <p style="margin:14px 0 0;font:400 15px/1.5 {FONT};color:{INK};">{_esc(goal_blurb)}</p>
  </td></tr>

  <tr><td style="padding:22px 28px 4px;">
    {_voice_card("ino", ino_note)}
    {_voice_card("riko", riko_note)}
    {_voice_card("yura", yura_note)}
  </td></tr>

  <tr><td style="padding:18px 28px 8px;">
    <table role="presentation" cellpadding="0" cellspacing="0">
      <tr>
        <td bgcolor="{ACCENT}" style="background:{ACCENT};border-radius:9px;">
          <a href="{_esc(donations)}"
             style="display:inline-block;background:{ACCENT};color:#ffffff;text-decoration:none;
                    font:600 15px/1 {FONT};padding:14px 26px;border-radius:9px;
                    border:1px solid {ACCENT};">{_esc(cta)}</a>
        </td>
      </tr>
    </table>
  </td></tr>

  <tr><td style="padding:22px 28px 36px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td style="height:1px;background:{LINE};font-size:0;line-height:0;">&nbsp;</td></tr>
    </table>
    <p style="margin:18px 0 0;font:400 13px/1.6 {FONT};color:{INK_SOFT};">{_esc(kofi_notice)}</p>
    <p style="margin:14px 0 0;font:400 12px/1.6 {FONT};color:#6f656a;">{_esc(signoff)}</p>
  </td></tr>

</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body></html>"""


def _attach_png(html_part: EmailMessage, filename: str, cid: str) -> None:
    path = IMG_DIR / filename
    if not path.is_file():
        return
    html_part.add_related(
        path.read_bytes(),
        maintype="image",
        subtype="png",
        cid=cid,
        filename=filename,
    )


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
    eyebrow = copy.get("eyebrow", "Donation received")
    intro = copy.get("intro", "Your donation of {amount} has been recorded.").format(
        amount=amount
    )
    ino_note = copy.get("ino_note", "")
    riko_note = copy.get("riko_note", "")
    yura_note = copy.get("yura_note", "")
    signoff = copy.get("signoff", "Ino")
    cta = copy.get("cta", "See the goal")
    goal_blurb = ctext("goal_blurb")
    site_url = site_url.rstrip("/")
    pct = max(0.0, min(float(percent), 100.0))

    filled = int(pct // 5)
    bar = "█" * filled + "░" * (20 - filled)
    preheader = f"Your donation of {amount} is in. {pct:.1f}% of the way."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender()
    msg["To"] = to

    msg.set_content(
        f"{heading}\n\n"
        f"Hi {supporter},\n\n"
        f"{intro}\n\n"
        f"{goal_title}\n"
        f"{bar}  {pct:.1f}%\n"
        f"{raised} of {target}\n"
        f"{goal_blurb}\n\n"
        f"Ino: {ino_note}\n"
        f"Riko: {riko_note}\n"
        f"Yura: {yura_note}\n\n"
        f"{kofi_notice}\n\n"
        f"{cta}: {site_url}/donations\n\n"
        f"{signoff}\n"
    )

    msg.add_alternative(
        _html_body(
            supporter=supporter,
            heading=heading,
            eyebrow=eyebrow,
            intro=intro,
            goal_title=goal_title,
            goal_blurb=goal_blurb,
            percent=pct,
            raised=raised,
            target=target,
            ino_note=ino_note,
            riko_note=riko_note,
            yura_note=yura_note,
            kofi_notice=kofi_notice,
            signoff=signoff,
            cta=cta,
            site_url=site_url,
            preheader=preheader,
        ),
        subtype="html",
    )

    html_part = msg.get_payload()[-1]
    _attach_png(html_part, "ino-mark.png", "ino-mark")
    for key, (filename, cid) in FACES.items():
        _attach_png(html_part, filename, cid)
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
