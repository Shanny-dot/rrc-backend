import firebase_admin
from firebase_admin import credentials, messaging
from app.core.config import settings
import json

def initialize_firebase():
    if not firebase_admin._apps:
        try:
            # FIREBASE_CREDENTIALS_JSON is the service account JSON, pasted as-is or base64 encoded.
            raw = (settings.FIREBASE_CREDENTIALS_JSON or "").strip()
            if raw:
                if not raw.startswith("{"):
                    import base64
                    raw = base64.b64decode(raw).decode('utf-8')
                cred_dict = json.loads(raw)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
        except Exception as e:
            print(f"Failed to initialize Firebase Admin: {e}")

initialize_firebase()

class PushService:
    @staticmethod
    def send_push_notification(token: str, title: str, body: str, data: dict = None):
        """Sends one phone alert. Returns "sent", "invalid_token" (app uninstalled or token
        replaced, so the caller can forget it) or "failed"."""
        if not firebase_admin._apps or not token:
            return "failed"
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items() if v is not None},
            android=messaging.AndroidConfig(priority="high", notification=messaging.AndroidNotification(sound="default")),
            apns=messaging.APNSConfig(payload=messaging.APNSPayload(aps=messaging.Aps(sound="default"))),
            token=token,
        )
        try:
            messaging.send(message)
            return "sent"
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError):
            return "invalid_token"
        except Exception as e:
            print(f"Failed to send push notification: {e}")
            return "failed"
