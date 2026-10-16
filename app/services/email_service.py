import html
import httpx
import resend
from app.core.config import settings

# Emails go through ZeptoMail (Zoho) when ZEPTOMAIL_API_KEY is set, otherwise Resend.
# FROM_EMAIL must be an address on a domain verified in that email service.
resend.api_key = settings.RESEND_API_KEY or ""
FROM_EMAIL = settings.FROM_EMAIL or "noreply@rrcapp.com"
_EMAIL_ENABLED = bool((settings.ZEPTOMAIL_API_KEY or settings.RESEND_API_KEY) and settings.FROM_EMAIL)


def _zepto_address(value):
    return {"address": value} if isinstance(value, str) else value


def _send(params: dict):
    """Sends one email. params: from, to (address or list), subject, html, optional reply_to.
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
        key = settings.ZEPTOMAIL_API_KEY.strip()
        r = httpx.post(settings.ZEPTOMAIL_API_URL, json=body, timeout=30, headers={
            "Authorization": key if key.startswith("Zoho-enczapikey") else f"Zoho-enczapikey {key}",
            "Accept": "application/json",
        })
        if r.status_code >= 300:
            raise Exception(f"ZeptoMail {r.status_code}: {r.text[:300]}")
        return r.json()
    params = {k: v for k, v in params.items() if v is not None}
    return resend.Emails.send(params)


class EmailService:

    @staticmethod
    def send_welcome_email(to_email: str, full_name: str, referral_code: str):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        html_content = f"""
        <h1>Welcome to RRC, {full_name}!</h1>
        <p>Thank you for joining our exclusive platform. You have been awarded 100 bonus points.</p>
        <p>Your unique referral code is: <strong>{referral_code}</strong></p>
        <p>Share this code with friends to earn more points!</p>
        """
        try:
            r = _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": "Welcome to RRC - Your 100 Bonus Points",
                "html": html_content,
            })
            return r
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_referral_invite(to_email: str, inviter_name: str, referral_code: str = None, invite_link: str = None):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        code_html = f"<p>Use {inviter_name}'s code <strong>{referral_code}</strong> when you sign up.</p>" if referral_code else ""
        link_html = f'<p><a href="{invite_link}">Join Reliance Rewards</a></p>' if invite_link else ""
        html_content = f"""
        <h1>You're invited to join Reliance Rewards</h1>
        <p>{inviter_name} has invited you to join Reliance Rewards. A Reliance broker may contact you to see how we can help.</p>
        {code_html}
        {link_html}
        """
        try:
            r = _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"{inviter_name} invited you to Reliance Rewards",
                "html": html_content,
            })
            return r
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_rsvp_confirmation(to_email: str, event_name: str, event_date: str, event_location: str, qr_base64: str):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        html_content = f"""
        <h1>RSVP Confirmed: {event_name}</h1>
        <p>Date: {event_date}</p>
        <p>Location: {event_location}</p>
        <p>Please present this QR code at the event:</p>
        <img src="{qr_base64}" alt="QR Code" />
        """
        try:
            r = _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"Your RSVP for {event_name}",
                "html": html_content,
            })
            return r
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_guest_invite(to_email: str, inviter_name: str, event_name: str):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        html_content = f"""
        <h1>You're invited as a guest!</h1>
        <p>{inviter_name} has invited you to attend {event_name}.</p>
        """
        try:
            r = _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"Guest Invitation: {event_name}",
                "html": html_content,
            })
            return r
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_redemption_approved(to_email: str, reward_name: str, points_used: int, remaining_balance: int):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        html_content = f"""
        <h1>Reward Redemption Approved</h1>
        <p>Your request for "{reward_name}" was approved.</p>
        <p>Points used: {points_used}</p>
        <p>Remaining balance: {remaining_balance}</p>
        """
        try:
            r = _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": "Reward Redemption Approved",
                "html": html_content,
            })
            return r
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_redemption_rejected(to_email: str, reward_name: str, refund_note: str, remaining_balance: int):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        html_content = f"""
        <h1>Reward Redemption Update</h1>
        <p>Unfortunately, your request for "{reward_name}" could not be processed at this time.</p>
        <p>Admin Note: {refund_note}</p>
        <p>Your points have been refunded. Remaining balance: {remaining_balance}</p>
        """
        try:
            r = _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": "Reward Redemption Update",
                "html": html_content,
            })
            return r
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def notify_admin_new_redemption(reward_name: str):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        html_content = f"""
        <h1>New Redemption Request</h1>
        <p>A user has requested to redeem: {reward_name}. Please log in to the admin panel to action it.</p>
        """
        try:
            r = _send({
                "from": FROM_EMAIL,
                "to": settings.ADMIN_EMAIL,
                "subject": "ACTION REQUIRED: New Reward Redemption",
                "html": html_content,
            })
            return r
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_redemption_requested(to_email: str, reward_name: str, points_used: int, remaining_balance: int, reference: str):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        html_content = f"""
        <h1>We've received your reward request</h1>
        <p>Reward: <strong>{reward_name}</strong></p>
        <p>Points used: {points_used}</p>
        <p>New balance: {remaining_balance} pts</p>
        <p>Reference number: <strong>{reference}</strong></p>
        <p>We'll let you know when it's on its way.</p>
        """
        try:
            return _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"Reward request received ({reference})",
                "html": html_content,
            })
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_redemption_sent(to_email: str, reward_name: str, note: str = None):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        note_html = f"<p>{note}</p>" if note else ""
        html_content = f"""
        <h1>Your reward is on its way</h1>
        <p>"{reward_name}" has been sent.</p>
        {note_html}
        """
        try:
            return _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"Your {reward_name} has been sent",
                "html": html_content,
            })
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_staff_feedback(to_email: str, member: dict, feedback: dict):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        name = html.escape(member.get("full_name") or "A member")
        contact = html.escape(" · ".join(v for v in (member.get("email"), member.get("mobile")) if v))
        category = html.escape((feedback.get("category") or "other").capitalize())
        message = html.escape(feedback.get("message") or "").replace("\n", "<br>")
        app = html.escape(" ".join(v for v in (feedback.get("platform"), feedback.get("app_version")) if v))
        html_content = f"""
        <h2>New app feedback ({category})</h2>
        <p><strong>{name}</strong>{f" — {contact}" if contact else ""}</p>
        <blockquote style="border-left:3px solid #FAB95B;margin:0;padding:8px 14px">{message}</blockquote>
        <p style="color:#777">{f"App: {app}. " if app else ""}See all feedback on the admin website.</p>
        """
        try:
            return _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "reply_to": member.get("email") or None,
                "subject": f"App feedback from {member.get('full_name') or 'a member'}",
                "html": html_content,
            })
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_staff_broker_request(to_email: str, member: dict, note: str):
        if not _EMAIL_ENABLED:
            print("Email skipped: email sending is not configured")
            return
        name = html.escape(member.get("full_name") or "A member")
        contact = html.escape(" · ".join(v for v in (member.get("email"), member.get("mobile")) if v))
        html_content = f"""
        <h2>{name} would like to talk to their broker</h2>
        <p>{html.escape(note)}</p>
        <p>{contact}</p>
        <p style="color:#777">Mark it as contacted on the admin website's Broker requests page.</p>
        """
        try:
            return _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "reply_to": member.get("email") or None,
                "subject": f"Broker request from {member.get('full_name') or 'a member'}",
                "html": html_content,
            })
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_event_thank_you(to_email: str, first_name: str, event_title: str, message: str,
                             links: list, broker_url: str = None, broker_name: str = None):
        """Thank-you after an event: key points, slides/recording links and a Talk to my broker button."""
        if not _EMAIL_ENABLED:
            return False
        para = "".join(f"<p>{html.escape(line)}</p>" for line in message.split("\n") if line.strip())
        link_html = "".join(
            f'<p><a href="{html.escape(url)}" style="color:#FAB95B;font-weight:bold">{html.escape(label)} →</a></p>'
            for label, url in links)
        broker_html = (
            f'<p style="margin-top:28px"><a href="{html.escape(broker_url)}" '
            f'style="background:#FAB95B;color:#0A0A0A;padding:12px 22px;border-radius:10px;text-decoration:none;font-weight:bold">'
            f'Talk to my broker</a></p><p style="color:#777;font-size:13px">{html.escape(broker_name or "")}</p>'
        ) if broker_url else ""
        html_content = f"""
        <h2>Thanks for coming to {html.escape(event_title)}, {html.escape(first_name or 'there')}!</h2>
        {para}
        {link_html}
        {broker_html}
        """
        try:
            _send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"Thanks for coming to {event_title}",
                "html": html_content,
            })
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False
