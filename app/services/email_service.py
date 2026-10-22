import base64
import html
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
import httpx
import resend
from app.core.config import settings

# Emails go out through, in order of preference:
#   1. Google Workspace (SMTP_USER + SMTP_PASSWORD, an app password) — sent from SMTP_USER
#      unless FROM_EMAIL is one of that account's "Send mail as" aliases;
#   2. ZeptoMail (Zoho) when ZEPTOMAIL_API_KEY is set;
#   3. Resend.
_SMTP = bool(settings.SMTP_USER and settings.SMTP_PASSWORD)
resend.api_key = settings.RESEND_API_KEY or ""
FROM_EMAIL = settings.FROM_EMAIL or settings.SMTP_USER or "noreply@reliiancerewards.com.au"
_EMAIL_ENABLED = _SMTP or bool(settings.ZEPTOMAIL_API_KEY) or bool(settings.RESEND_API_KEY)

GOLD = "#FAB95B"


# The email banner logo (from "Reliiance Rewards logofor email.pdf"), sent inside every email
# rather than linked, so it shows even if the website moves or blocks image requests.
LOGO_CID = "rrclogo"
_LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "email_logo.png")
try:
    with open(_LOGO_PATH, "rb") as _f:
        _LOGO_B64 = base64.b64encode(_f.read()).decode()
except OSError:
    _LOGO_B64 = ""


def _zepto_address(value):
    return {"address": value} if isinstance(value, str) else value


def _send_smtp(params: dict):
    """Google Workspace: smtp.gmail.com with the account's app password."""
    msg = EmailMessage()
    msg["From"] = formataddr((settings.FROM_NAME, params["from"]))
    to = params["to"] if isinstance(params["to"], list) else [params["to"]]
    msg["To"] = ", ".join(to)
    msg["Subject"] = params["subject"]
    if params.get("reply_to"):
        msg["Reply-To"] = params["reply_to"]
    msg.set_content("This email needs an email app that can show HTML.")
    msg.add_alternative(params["html"], subtype="html")
    for img in params.get("inline_images") or []:
        maintype, subtype = (img.get("mime_type") or "image/png").split("/", 1)
        msg.get_payload()[1].add_related(base64.b64decode(img["content"]), maintype=maintype, subtype=subtype,
                                         cid=f"<{img['cid']}>")
    for att in params.get("attachments") or []:
        maintype, subtype = (att.get("mime_type") or "application/octet-stream").split("/", 1)
        msg.add_attachment(base64.b64decode(att["content"]), maintype=maintype, subtype=subtype, filename=att["name"])
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD.replace(" ", ""))
        smtp.send_message(msg)
    return {"sent": True}


def _send(params: dict):
    """Sends one email. params: from, to (address or list), subject, html, optional reply_to
    and inline_images ([{cid, mime_type, content (base64)}]).
    Raises on failure so callers' error handling (and logs) still apply."""
    if _SMTP:
        return _send_smtp(params)
    if settings.ZEPTOMAIL_API_KEY:
        to = params["to"] if isinstance(params["to"], list) else [params["to"]]
        body = {
            "from": {"address": params["from"], "name": settings.FROM_NAME},
            "to": [{"email_address": _zepto_address(a)} for a in to],
            "subject": params["subject"],
            "htmlbody": params["html"],
        }
        if params.get("reply_to"):
            body["reply_to"] = [_zepto_address(params["reply_to"])]
        if params.get("inline_images"):
            body["inline_images"] = params["inline_images"]
        if params.get("attachments"):
            body["attachments"] = params["attachments"]
        key = settings.ZEPTOMAIL_API_KEY.strip()
        r = httpx.post(settings.ZEPTOMAIL_API_URL, json=body, timeout=30, headers={
            "Authorization": key if key.startswith("Zoho-enczapikey") else f"Zoho-enczapikey {key}",
            "Accept": "application/json",
        })
        if r.status_code >= 300:
            raise Exception(f"ZeptoMail {r.status_code}: {r.text[:300]}")
        return r.json()
    params = {k: v for k, v in params.items() if v is not None and k not in ("inline_images", "attachments")}
    return resend.Emails.send(params)


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _paragraphs(text: str) -> str:
    """Plain text from the admin website (one paragraph per line) as safe HTML."""
    return "".join(f"<p>{_esc(line)}</p>" for line in (text or "").split("\n") if line.strip())


def _layout(heading: str, body_html: str, button: tuple = None) -> str:
    """Every member email shares one simple branded layout. button: (label, url)."""
    button_html = (
        f'<p style="margin:28px 0 8px"><a href="{_esc(button[1])}" style="background:{GOLD};color:#0A0A0A;'
        f'padding:12px 22px;border-radius:10px;text-decoration:none;font-weight:bold;display:inline-block">'
        f'{_esc(button[0])}</a></p>'
    ) if button and button[1] else ""
    return f"""
    <div style="background:#f4f4f4;padding:24px 12px;font-family:Arial,Helvetica,sans-serif">
      <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden">
        <div style="background:#201D1D;padding:0;color:{GOLD};font-weight:bold;font-size:18px;letter-spacing:1px;text-align:center">
          <img src="cid:{LOGO_CID}" alt="{_esc(settings.FROM_NAME)}" width="560" style="display:block;width:100%;max-width:560px;height:auto;border:0">
        </div>
        <div style="padding:24px;color:#222;font-size:15px;line-height:1.55">
          <h2 style="margin:0 0 14px;font-size:21px;color:#111">{heading}</h2>
          {body_html}
          {button_html}
        </div>
        <div style="padding:14px 24px;color:#999;font-size:12px;border-top:1px solid #eee">
          This is an automated message from {_esc(settings.FROM_NAME)}. Please don't reply to this email.
        </div>
      </div>
    </div>"""


def _deliver(to_email: str, subject: str, html_content: str, reply_to: str = None, inline_images: list = None,
             attachments: list = None) -> bool:
    """True when the email was accepted. Never raises: a failed email must not fail the request.
    attachments: [{name, mime_type, content (base64)}]."""
    if not _EMAIL_ENABLED:
        print(f"Email skipped (email sending is not configured): {subject}")
        return False
    if not to_email:
        return False
    if _LOGO_B64 and f"cid:{LOGO_CID}" in html_content:
        inline_images = [{"cid": LOGO_CID, "mime_type": "image/png", "content": _LOGO_B64}] + list(inline_images or [])
    try:
        _send({"from": FROM_EMAIL, "to": to_email, "subject": subject, "html": html_content,
               "reply_to": reply_to or None, "inline_images": inline_images, "attachments": attachments})
        return True
    except Exception as e:
        print(f"Failed to send email ({subject}): {e}")
        return False


def _first(name: str) -> str:
    return (name or "").strip().split(" ")[0] or "there"


def _site(path: str) -> str:
    from urllib.parse import urlsplit
    url = str(settings.FRONTEND_URL or "https://admin.reliiancerewards.com.au")
    if "vercel.app" in url:
        return f"https://admin.reliiancerewards.com.au{path}"
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{path}"


def _box(rows: list) -> str:
    """Highlighted details box. rows: [(label, value)]; empty values are left out."""
    lines = "<br>".join(f"{_esc(k)}: <strong>{_esc(v)}</strong>" for k, v in rows if v not in (None, ""))
    return f'<p style="background:#faf6ee;border-radius:10px;padding:12px 14px">{lines}</p>' if lines else ""


def _event_rows(event: dict, when: str) -> list:
    return [("When", when), ("Where", event.get("location"))]


def _attendee_info(event: dict) -> str:
    info = (event.get("attendee_info") or "").strip()
    return f"<p><strong>Good to know:</strong></p>{_paragraphs(info)}" if info else ""


HOW_TO_EARN = """
<p><strong>How to earn points</strong></p>
<ul style="padding-left:20px;margin:0 0 12px">
  <li>Refer friends from the Referrals tab</li>
  <li>RSVP to our events and check in on the day</li>
  <li>Look out for birthday and surprise bonuses</li>
</ul>
<p>Then swap your points for experiences, gift cards and more on the Rewards tab.</p>
"""


def _ics(event: dict) -> tuple:
    """(Google Calendar link, .ics attachment) for the event, assuming two hours long."""
    import datetime
    from urllib.parse import quote
    from app.services.program_service import _parse_ts
    start = _parse_ts(event.get("event_date"))
    if not start:
        return None, None
    end = start + datetime.timedelta(hours=2)
    fmt = lambda d: d.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: E731
    title, place = event.get("title") or "Event", event.get("location") or ""
    details = (event.get("description") or "")[:500]
    gcal = (f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={quote(title)}"
            f"&dates={fmt(start)}/{fmt(end)}&location={quote(place)}&details={quote(details)}")
    esc = lambda s: s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")  # noqa: E731
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Reliiance Rewards//Events//EN", "METHOD:PUBLISH",
        "BEGIN:VEVENT", f"UID:{event.get('id')}@reliiancerewards", f"DTSTAMP:{fmt(datetime.datetime.now(datetime.timezone.utc))}",
        f"DTSTART:{fmt(start)}", f"DTEND:{fmt(end)}", f"SUMMARY:{esc(title)}", f"LOCATION:{esc(place)}",
        f"DESCRIPTION:{esc(details)}", "END:VEVENT", "END:VCALENDAR", ""])
    att = {"name": "event.ics", "mime_type": "text/calendar", "content": base64.b64encode(ics.encode()).decode()}
    return gcal, att


def _fill(template: str, values: dict) -> str:
    """Replaces {reward}, {points} … placeholders; unknown ones are left as typed."""
    out = template or ""
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


class EmailService:

    # 1. Sign up
    @staticmethod
    def send_welcome_email(to_email: str, full_name: str, referral_code: str = None, welcome_points: int = 0,
                           inviter_name: str = None):
        """Sign-up, and the joining bonus for friends who signed up from a member's referral."""
        joined_html = (f"<p>Thanks for accepting {_esc(inviter_name)}'s invitation — we're glad you're here.</p>"
                       if inviter_name else "")
        points_html = (f"<p>To get you started, we've added <strong>{welcome_points:,} bonus points</strong> to your account.</p>"
                       if welcome_points else "")
        code_html = (f"<p>Your personal referral code is <strong>{_esc(referral_code)}</strong>. Friends enter it when they "
                     f"create their account, so you earn points when they join.</p>") if referral_code else ""
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Thanks for joining {_esc(settings.FROM_NAME)}.</p>
        {joined_html}
        {points_html}
        {HOW_TO_EARN}
        {code_html}
        <p>Have a question? Our FAQs cover the most common ones.</p>
        """
        subject = f"Welcome to {settings.FROM_NAME}" + (f" — {welcome_points:,} bonus points added" if welcome_points else "")
        return _deliver(to_email, subject, _layout("Welcome aboard!", body, ("Read the FAQs", _site("/faq"))))

    @staticmethod
    def send_details_changed(to_email: str, full_name: str, changes: list) -> bool:
        """changes: [(label, new value)], e.g. [("Mobile number", "0412 345 678")]."""
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>The details on your {_esc(settings.FROM_NAME)} account were just updated:</p>
        {_box(changes)}
        <p><strong>If this wasn't you</strong>, please contact us straight away from Profile → Help &amp; contact in the app.</p>
        """
        return _deliver(to_email, "Your account details were updated", _layout("Your details were updated", body))

    @staticmethod
    def send_account_deleted(to_email: str, full_name: str, points_lost: int) -> bool:
        points_html = (f"<p>Any unused points ({points_lost:,}) have been removed and can't be restored.</p>"
                       if points_lost else "<p>Any unused points have been removed and can't be restored.</p>")
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>As requested, your {_esc(settings.FROM_NAME)} account has been deleted.</p>
        {points_html}
        <p>Thanks for being a member. You're welcome back any time — just sign up again in the app.</p>
        <p style="color:#777;font-size:13px">If you didn't ask for this, please contact us as soon as possible.</p>
        """
        return _deliver(to_email, "Your account has been deleted", _layout("Your account has been deleted", body))

    @staticmethod
    def send_points_added(to_email: str, full_name: str, points: int, reason: str, balance: int) -> bool:
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Good news — <strong>{points:,} points</strong> have been added to your account.</p>
        {_box([("Reason", reason), ("Points added", f"{points:,}"), ("New balance", f"{balance:,} points")])}
        <p>Open the Rewards tab in the app to see what you can redeem.</p>
        """
        return _deliver(to_email, f"+{points:,} points added to your account", _layout(f"+{points:,} points!", body))

    @staticmethod
    def send_points_expiring(to_email: str, full_name: str, points: int, use_by: str, balance: int, rewards: list) -> bool:
        """rewards: [(title, points_required)] the member can already afford."""
        rewards_html = ""
        if rewards:
            items = "".join(f"<li>{_esc(t)} — {p:,} points</li>" for t, p in rewards)
            rewards_html = f"<p>Rewards you can redeem right now:</p><ul style='padding-left:20px'>{items}</ul>"
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p><strong>{points:,} of your points</strong> will expire on <strong>{_esc(use_by)}</strong> if they're not used.</p>
        {_box([("Points expiring", f"{points:,}"), ("Use by", use_by), ("Current balance", f"{balance:,} points")])}
        {rewards_html}
        <p>Open the Rewards tab in the app to redeem them before they go.</p>
        """
        return _deliver(to_email, f"{points:,} points expire on {use_by}", _layout("Your points expire soon", body))

    @staticmethod
    def send_friend_joined(to_email: str, full_name: str, friend_name: str, points: int) -> bool:
        points_html = (f"<p>Once their referral is confirmed, <strong>{points:,} points</strong> will be added to your account.</p>"
                       if points else "<p>We'll let you know when your referral points are added.</p>")
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Your friend <strong>{_esc(friend_name)}</strong> has joined {_esc(settings.FROM_NAME)} using your invitation. Thank you!</p>
        {points_html}
        <p>You can follow their progress on the Referrals tab.</p>
        """
        return _deliver(to_email, f"{friend_name} joined {settings.FROM_NAME}", _layout("Your friend joined!", body))

    @staticmethod
    def send_tier_upgrade(to_email: str, full_name: str, tier_name: str, benefits: list) -> bool:
        items = "".join(f"<li>{_esc(b)}</li>" for b in benefits)
        benefits_html = f"<p>Your {_esc(tier_name)} benefits:</p><ul style='padding-left:20px'>{items}</ul>" if items else ""
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Congratulations — you've reached <strong>{_esc(tier_name)}</strong> tier!</p>
        {benefits_html}
        <p>Thanks for being such a valued member.</p>
        """
        return _deliver(to_email, f"You've reached {tier_name} tier", _layout(f"Welcome to {_esc(tier_name)}!", body))

    # 2. Forgot password
    @staticmethod
    def send_verification_code(to_email: str, full_name: str, code: str) -> bool:
        """The 6-digit code that confirms a member's email address."""
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Enter this code in the {_esc(settings.FROM_NAME)} app to confirm your email address:</p>
        <p style="margin:22px 0;font-size:32px;font-weight:bold;letter-spacing:8px;color:#111">{_esc(code)}</p>
        <p>The code expires in 10 minutes. Your bonus points are added once your email and mobile are both confirmed.</p>
        <p style="color:#777;font-size:13px">If you didn't sign up, you can ignore this email.</p>
        """
        return _deliver(to_email, f"Your verification code: {code}", _layout("Confirm your email", body))

    @staticmethod
    def send_password_reset(to_email: str, full_name: str, reset_link: str) -> bool:
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>We received a request to reset the password for your {_esc(settings.FROM_NAME)} account. Tap the button below to choose a new password.</p>
        <p style="color:#777;font-size:13px">If you didn't ask for this, you can ignore this email — your password won't change.</p>
        """
        return _deliver(to_email, "Reset your password", _layout("Reset your password", body, ("Choose a new password", reset_link)))

    # 3. Referral invitation
    @staticmethod
    def send_referral_invite(to_email: str, inviter_name: str, referral_code: str = None, invite_link: str = None,
                             friend_name: str = None) -> bool:
        inviter = _esc(inviter_name or "A friend")
        code_html = (f"<p>When you sign up, enter {inviter}'s referral code <strong>{_esc(referral_code)}</strong>.</p>"
                     if referral_code else "")
        body = f"""
        <p>Hi {_esc(_first(friend_name))},</p>
        <p>{inviter} thinks you'd enjoy {_esc(settings.FROM_NAME)} — a members' program with exclusive events, rewards and offers.
        Someone from our team may also be in touch to say hello.</p>
        {code_html}
        """
        return _deliver(to_email, f"{inviter_name or 'A friend'} invited you to {settings.FROM_NAME}",
                        _layout("You're invited!", body, ("Join now", invite_link)))

    # 4 & 5. Reward redemption confirmation and status updates (wording edited on the admin website)
    @staticmethod
    def send_redemption_status(to_email: str, full_name: str, template: dict, values: dict, note: str = None) -> bool:
        subject = _fill(template.get("subject") or "Update on your reward", values)
        message = _fill(template.get("message") or "", values)
        details = _box([
            ("Reward", values.get("reward")),
            ("Status", template.get("label")),
            ("Reference", values.get("reference")),
            ("Points used", values.get("points")),
            ("Points balance", values.get("balance")),
            ("Expected delivery", values.get("delivery")),
        ])
        about = _paragraphs(values.get("description") or "") if values.get("description") else ""
        note_html = f"<p><strong>Note from our team:</strong><br>{_esc(note)}</p>" if note else ""
        body = f"<p>Hi {_esc(_first(full_name))},</p>{_paragraphs(message)}{details}{about}{note_html}"
        return _deliver(to_email, subject, _layout(_esc(subject), body))

    @staticmethod
    def notify_admin_new_redemption(reward_name: str, member_name: str = None):
        if not settings.ADMIN_EMAIL:
            return False
        body = f"<p>{_esc(member_name or 'A member')} has asked to redeem <strong>{_esc(reward_name)}</strong>. " \
               f"Please log in to the admin website to action it.</p>"
        return _deliver(settings.ADMIN_EMAIL, "ACTION REQUIRED: New reward redemption", _layout("New redemption request", body))

    # 6. RSVP confirmation
    @staticmethod
    def send_rsvp_confirmation(to_email: str, full_name: str, event: dict, when: str, qr_png_base64: str = None) -> bool:
        qr_html, images = "", None
        if qr_png_base64:
            images = [{"cid": "rsvpqr", "mime_type": "image/png", "content": qr_png_base64}]
            qr_html = ('<p>Show this code at the door, or check in with the <strong>Check in</strong> button on the Events screen:</p>'
                       '<p><img src="cid:rsvpqr" alt="Your RSVP code" width="180" height="180"></p>')
        gcal, ics = _ics(event)
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>You're booked in for <strong>{_esc(event.get('title'))}</strong>. We look forward to seeing you!</p>
        {_box(_event_rows(event, when))}
        {_attendee_info(event)}
        <p><strong>Checking in:</strong> on the day, open the app and tap <strong>Check in</strong> on the Events screen
        to scan the event QR code — that's how your points are added.</p>
        {qr_html}
        <p>Add it to your calendar: open the attached invite{f', or <a href="{_esc(gcal)}" style="color:#b07d1a">add it to Google Calendar</a>' if gcal else ''}.</p>
        <p style="color:#777;font-size:13px">Can't make it? Please cancel your RSVP in the app so someone else can take your spot.</p>
        """
        return _deliver(to_email, f"You're going: {event.get('title')}", _layout("RSVP confirmed", body), inline_images=images,
                        attachments=[ics] if ics else None)

    @staticmethod
    def send_event_changed(to_email: str, full_name: str, event: dict, when: str, changes: list) -> bool:
        items = "".join(f"<li>{_esc(c)}</li>" for c in changes)
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>There's been a change to <strong>{_esc(event.get('title'))}</strong>, which you're booked in for:</p>
        <ul style="padding-left:20px">{items}</ul>
        {_box(_event_rows(event, when))}
        {_attendee_info(event)}
        <p>You're still booked in. If you can no longer make it, please cancel your RSVP in the app.</p>
        """
        return _deliver(to_email, f"Event update: {event.get('title')}", _layout("Your event has changed", body))

    @staticmethod
    def send_event_cancelled(to_email: str, full_name: str, event: dict, when: str) -> bool:
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>We're sorry — <strong>{_esc(event.get('title'))}</strong> ({_esc(when)}) has been cancelled.</p>
        <p>Your RSVP has been cancelled too, so there's nothing you need to do. Keep an eye on the Events tab for upcoming events.</p>
        """
        return _deliver(to_email, f"Event cancelled: {event.get('title')}", _layout("Event cancelled", body))

    # 7. RSVP cancelled
    @staticmethod
    def send_rsvp_cancelled(to_email: str, full_name: str, event: dict, when: str) -> bool:
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Your RSVP for <strong>{_esc(event.get('title'))}</strong> ({_esc(when)}) has been cancelled.</p>
        <p>Changed your mind? You can RSVP again from the Events screen in the app while spots are available.</p>
        """
        return _deliver(to_email, f"RSVP cancelled: {event.get('title')}", _layout("Your RSVP has been cancelled", body))

    # 8. Reminders a week before and the day before an event
    @staticmethod
    def send_event_reminder(to_email: str, full_name: str, event: dict, when: str, days: int = 1) -> bool:
        soon = "tomorrow" if days == 1 else "in a week" if days == 7 else f"in {days} days"
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Just a reminder that <strong>{_esc(event.get('title'))}</strong> is {soon}.</p>
        {_box(_event_rows(event, when))}
        {_attendee_info(event)}
        <p>Remember to check in at the event with the <strong>Check in</strong> button on the Events screen to collect your points.</p>
        <p style="color:#777;font-size:13px">Can't make it any more? Please cancel your RSVP in the app.</p>
        """
        heading = "See you tomorrow!" if days == 1 else "See you soon!"
        return _deliver(to_email, f"Reminder: {event.get('title')} is {soon}", _layout(heading, body))

    # Event "Invite a friend"
    @staticmethod
    def send_guest_invite(to_email: str, inviter_name: str, event: dict, when: str, guest_name: str = None,
                          invite_link: str = None) -> bool:
        where = f"<br>Where: <strong>{_esc(event.get('location'))}</strong>" if event.get("location") else ""
        desc = _paragraphs(event.get("description") or "")
        body = f"""
        <p>Hi {_esc(_first(guest_name))},</p>
        <p>{_esc(inviter_name or 'A friend')} would like you to come along to <strong>{_esc(event.get('title'))}</strong> as their guest.</p>
        <p style="background:#faf6ee;border-radius:10px;padding:12px 14px">When: <strong>{_esc(when)}</strong>{where}</p>
        {desc}
        """
        return _deliver(to_email, f"{inviter_name or 'A friend'} invited you to {event.get('title')}",
                        _layout("You're invited to an event", body, ("Find out more", invite_link)))

    @staticmethod
    def send_staff_new_member(full_name: str, email: str, mobile: str, points: int, inviter_name: str = None,
                              how: str = "") -> bool:
        """Tells staff (ADMIN_EMAIL) that someone has signed up."""
        if not settings.ADMIN_EMAIL:
            return False
        via = {"(register)": "Email sign-up", "(google)": "Google", "(apple)": "Apple", "(facebook)": "Facebook"}.get(how, "")
        body = f"""
        <p>A new member has joined {_esc(settings.FROM_NAME)}.</p>
        {_box([("Name", full_name), ("Email", email), ("Mobile", mobile), ("Signed up with", via),
               ("Invited by", inviter_name), ("Points given", f"{points:,}" if points else "0")])}
        <p style="color:#777;font-size:13px">See all members on the admin website's Users page.</p>
        """
        return _deliver(settings.ADMIN_EMAIL, f"New member: {full_name or email or 'unknown'}",
                        _layout("New member signed up", body), reply_to=email or None)

    @staticmethod
    def send_staff_feedback(to_email: str, member: dict, feedback: dict):
        name = html.escape(member.get("full_name") or "A member")
        contact = html.escape(" · ".join(v for v in (member.get("email"), member.get("mobile")) if v))
        category = html.escape((feedback.get("category") or "other").capitalize())
        message = html.escape(feedback.get("message") or "").replace("\n", "<br>")
        app = html.escape(" ".join(v for v in (feedback.get("platform"), feedback.get("app_version")) if v))
        html_content = f"""
        <h2>New app feedback ({category})</h2>
        <p><strong>{name}</strong>{f" — {contact}" if contact else ""}</p>
        <blockquote style="border-left:3px solid {GOLD};margin:0;padding:8px 14px">{message}</blockquote>
        <p style="color:#777">{f"App: {app}. " if app else ""}See all feedback on the admin website.</p>
        """
        return _deliver(to_email, f"App feedback from {member.get('full_name') or 'a member'}", html_content,
                        reply_to=member.get("email"))

    @staticmethod
    def send_staff_broker_request(to_email: str, member: dict, note: str):
        name = html.escape(member.get("full_name") or "A member")
        contact = html.escape(" · ".join(v for v in (member.get("email"), member.get("mobile")) if v))
        html_content = f"""
        <h2>{name} would like to be contacted</h2>
        <p>{html.escape(note)}</p>
        <p>{contact}</p>
        <p style="color:#777">Mark it as contacted on the admin website's Broker requests page.</p>
        """
        return _deliver(to_email, f"Contact request from {member.get('full_name') or 'a member'}", html_content,
                        reply_to=member.get("email"))

    @staticmethod
    def send_event_thank_you(to_email: str, first_name: str, event_title: str, message: str,
                             links: list, broker_url: str = None, broker_name: str = None,
                             button_label: str = "Contact us", points_added: int = 0):
        """Thank-you after an event: points added, key takeaways, slides/recording links and a Contact us button."""
        link_html = "".join(
            f'<p><a href="{_esc(url)}" style="color:#b07d1a;font-weight:bold">{_esc(label)} →</a></p>'
            for label, url in links)
        points_html = (f"<p><strong>{points_added:,} points</strong> have been added to your account for attending.</p>"
                       if points_added else "")
        name_html = f'<p style="color:#777;font-size:13px">Questions? {_esc(broker_name)} is happy to help.</p>' if broker_url and broker_name else ""
        body = f"{points_html}{_paragraphs(message)}{link_html}{name_html}"
        return _deliver(to_email, f"Thanks for coming to {event_title}",
                        _layout(f"Thanks for coming to {_esc(event_title)}, {_esc(first_name or 'there')}!", body,
                                (button_label or "Contact us", broker_url)))
