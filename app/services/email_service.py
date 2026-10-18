import html
import httpx
import resend
from app.core.config import settings

# Emails go through ZeptoMail (Zoho) when ZEPTOMAIL_API_KEY is set, otherwise Resend.
# FROM_EMAIL must be an address on a domain verified in that email service.
resend.api_key = settings.RESEND_API_KEY or ""
FROM_EMAIL = settings.FROM_EMAIL or "noreply@rrcapp.com"
_EMAIL_ENABLED = bool((settings.ZEPTOMAIL_API_KEY or settings.RESEND_API_KEY) and settings.FROM_EMAIL)

GOLD = "#FAB95B"


def _zepto_address(value):
    return {"address": value} if isinstance(value, str) else value


def _send(params: dict):
    """Sends one email. params: from, to (address or list), subject, html, optional reply_to
    and inline_images ([{cid, mime_type, content (base64)}], ZeptoMail only).
    Raises on failure so callers' error handling (and logs) still apply."""
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
        key = settings.ZEPTOMAIL_API_KEY.strip()
        r = httpx.post(settings.ZEPTOMAIL_API_URL, json=body, timeout=30, headers={
            "Authorization": key if key.startswith("Zoho-enczapikey") else f"Zoho-enczapikey {key}",
            "Accept": "application/json",
        })
        if r.status_code >= 300:
            raise Exception(f"ZeptoMail {r.status_code}: {r.text[:300]}")
        return r.json()
    params = {k: v for k, v in params.items() if v is not None and k != "inline_images"}
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
        <div style="background:#0A0A0A;padding:18px 24px;color:{GOLD};font-weight:bold;font-size:18px;letter-spacing:1px">
          {_esc(settings.FROM_NAME)}
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


def _deliver(to_email: str, subject: str, html_content: str, reply_to: str = None, inline_images: list = None) -> bool:
    """True when the email was accepted. Never raises: a failed email must not fail the request."""
    if not _EMAIL_ENABLED:
        print(f"Email skipped (email sending is not configured): {subject}")
        return False
    if not to_email:
        return False
    try:
        _send({"from": FROM_EMAIL, "to": to_email, "subject": subject, "html": html_content,
               "reply_to": reply_to or None, "inline_images": inline_images})
        return True
    except Exception as e:
        print(f"Failed to send email ({subject}): {e}")
        return False


def _first(name: str) -> str:
    return (name or "").strip().split(" ")[0] or "there"


def _fill(template: str, values: dict) -> str:
    """Replaces {reward}, {points} … placeholders; unknown ones are left as typed."""
    out = template or ""
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


class EmailService:

    # 1. Sign up
    @staticmethod
    def send_welcome_email(to_email: str, full_name: str, referral_code: str = None, welcome_points: int = 0):
        points_html = (f"<p>To get you started, we've added <strong>{welcome_points:,} welcome points</strong> to your account.</p>"
                       if welcome_points else "")
        code_html = (f"<p>Your personal referral code is <strong>{_esc(referral_code)}</strong>. Friends enter it when they "
                     f"create their account, so you earn points when they join.</p>") if referral_code else ""
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Thanks for joining {_esc(settings.FROM_NAME)}. You can now earn points by referring friends and coming to our events, and spend them on rewards.</p>
        {points_html}
        {code_html}
        """
        return _deliver(to_email, f"Welcome to {settings.FROM_NAME}", _layout("Welcome aboard!", body))

    # 2. Forgot password
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
        details = (f'<p style="background:#faf6ee;border-radius:10px;padding:12px 14px">'
                   f'Reward: <strong>{_esc(values.get("reward"))}</strong><br>'
                   f'Status: <strong>{_esc(template.get("label") or "")}</strong><br>'
                   f'Reference: <strong>{_esc(values.get("reference"))}</strong><br>'
                   f'Points balance: <strong>{_esc(values.get("balance"))}</strong></p>')
        note_html = f"<p><strong>Note from our team:</strong><br>{_esc(note)}</p>" if note else ""
        body = f"<p>Hi {_esc(_first(full_name))},</p>{_paragraphs(message)}{details}{note_html}"
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
        where = f"<br>Where: <strong>{_esc(event.get('location'))}</strong>" if event.get("location") else ""
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>You're booked in for <strong>{_esc(event.get('title'))}</strong>. We look forward to seeing you!</p>
        <p style="background:#faf6ee;border-radius:10px;padding:12px 14px">When: <strong>{_esc(when)}</strong>{where}</p>
        {qr_html}
        <p style="color:#777;font-size:13px">Can't make it? Please cancel your RSVP in the app so someone else can take your spot.</p>
        """
        return _deliver(to_email, f"You're going: {event.get('title')}", _layout("RSVP confirmed", body), inline_images=images)

    # 7. RSVP cancelled
    @staticmethod
    def send_rsvp_cancelled(to_email: str, full_name: str, event: dict, when: str) -> bool:
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Your RSVP for <strong>{_esc(event.get('title'))}</strong> ({_esc(when)}) has been cancelled.</p>
        <p>Changed your mind? You can RSVP again from the Events screen in the app while spots are available.</p>
        """
        return _deliver(to_email, f"RSVP cancelled: {event.get('title')}", _layout("Your RSVP has been cancelled", body))

    # 8. Reminder the day before an event
    @staticmethod
    def send_event_reminder(to_email: str, full_name: str, event: dict, when: str) -> bool:
        where = f"<br>Where: <strong>{_esc(event.get('location'))}</strong>" if event.get("location") else ""
        body = f"""
        <p>Hi {_esc(_first(full_name))},</p>
        <p>Just a reminder that <strong>{_esc(event.get('title'))}</strong> is tomorrow.</p>
        <p style="background:#faf6ee;border-radius:10px;padding:12px 14px">When: <strong>{_esc(when)}</strong>{where}</p>
        <p>Remember to check in at the event with the <strong>Check in</strong> button on the Events screen to collect your points.</p>
        """
        return _deliver(to_email, f"Reminder: {event.get('title')} is tomorrow", _layout("See you tomorrow!", body))

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
                             button_label: str = "Contact us"):
        """Thank-you after an event: key points, slides/recording links and a Contact us button."""
        link_html = "".join(
            f'<p><a href="{_esc(url)}" style="color:#b07d1a;font-weight:bold">{_esc(label)} →</a></p>'
            for label, url in links)
        name_html = f'<p style="color:#777;font-size:13px">Questions? {_esc(broker_name)} is happy to help.</p>' if broker_url and broker_name else ""
        body = f"{_paragraphs(message)}{link_html}{name_html}"
        return _deliver(to_email, f"Thanks for coming to {event_title}",
                        _layout(f"Thanks for coming to {_esc(event_title)}, {_esc(first_name or 'there')}!", body,
                                (button_label or "Contact us", broker_url)))
