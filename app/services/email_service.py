import resend
from app.core.config import settings

resend.api_key = settings.RESEND_API_KEY
FROM_EMAIL = settings.FROM_EMAIL

class EmailService:

    @staticmethod
    def send_welcome_email(to_email: str, full_name: str, referral_code: str):
        html_content = f"""
        <h1>Welcome to RRC, {full_name}!</h1>
        <p>Thank you for joining our exclusive platform. You have been awarded 100 bonus points.</p>
        <p>Your unique referral code is: <strong>{referral_code}</strong></p>
        <p>Share this code with friends to earn more points!</p>
        """
        try:
            r = resend.Emails.send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": "Welcome to RRC - Your 100 Bonus Points",
                "html": html_content
            })
            return r
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_referral_invite(to_email: str, inviter_name: str):
        html_content = f"""
        <h1>You're invited to join RRC!</h1>
        <p>{inviter_name} has invited you to join our exclusive referral and rewards platform.</p>
        """
        try:
            r = resend.Emails.send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"{inviter_name} invited you to RRC",
                "html": html_content
            })
            return r
        except Exception as e:
            print(f"Failed to send email: {e}")

    @staticmethod
    def send_rsvp_confirmation(to_email: str, event_name: str, event_date: str, event_location: str, qr_base64: str):
        # qr_base64 should be a data URI: data:image/png;base64,...
        html_content = f"""
        <h1>RSVP Confirmed: {event_name}</h1>
        <p>Date: {event_date}</p>
        <p>Location: {event_location}</p>
        <p>Please present this QR code at the event:</p>
        <img src="{qr_base64}" alt="QR Code" />
        """
        try:
            r = resend.Emails.send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"Your RSVP for {event_name}",
                "html": html_content
            })
            return r
        except Exception as e:
             print(f"Failed to send email: {e}")

    @staticmethod
    def send_guest_invite(to_email: str, inviter_name: str, event_name: str):
        html_content = f"""
        <h1>You're invited as a guest!</h1>
        <p>{inviter_name} has invited you to attend {event_name}.</p>
        """
        try:
            r = resend.Emails.send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"Guest Invitation: {event_name}",
                "html": html_content
            })
            return r
        except Exception as e:
             print(f"Failed to send email: {e}")

    @staticmethod
    def send_redemption_approved(to_email: str, reward_name: str, points_used: int, remaining_balance: int):
         html_content = f"""
         <h1>Reward Redemption Approved</h1>
         <p>Your request for "{reward_name}" was approved.</p>
         <p>Points used: {points_used}</p>
         <p>Remaining balance: {remaining_balance}</p>
         """
         try:
            r = resend.Emails.send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": "Reward Redemption Approved",
                "html": html_content
            })
            return r
         except Exception as e:
             print(f"Failed to send email: {e}")

    @staticmethod
    def send_redemption_rejected(to_email: str, reward_name: str, refund_note: str, remaining_balance: int):
        html_content = f"""
         <h1>Reward Redemption Update</h1>
         <p>Unfortunately, your request for "{reward_name}" could not be processed at this time.</p>
         <p>Admin Note: {refund_note}</p>
         <p>Your points have been refunded. Remaining balance: {remaining_balance}</p>
         """
        try:
            r = resend.Emails.send({
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": "Reward Redemption Update",
                "html": html_content
            })
            return r
        except Exception as e:
             print(f"Failed to send email: {e}")

    @staticmethod
    def notify_admin_new_redemption(reward_name: str):
        # Sends to settings.ADMIN_EMAIL
        html_content = f"""
         <h1>New Redemption Request</h1>
         <p>A user has requested to redeem: {reward_name}. Please log in to the admin panel to action it.</p>
         """
        try:
            r = resend.Emails.send({
                "from": FROM_EMAIL,
                "to": settings.ADMIN_EMAIL,
                "subject": "ACTION REQUIRED: New Reward Redemption",
                "html": html_content
            })
            return r
        except Exception as e:
             print(f"Failed to send email: {e}")
