import firebase_admin
from firebase_admin import credentials, messaging
from app.core.config import settings
import json
import os

def initialize_firebase():
    if not firebase_admin._apps:
        try:
            # Assuming settings.FIREBASE_CREDENTIALS_JSON is a base64 encoded string
            # or a path to a JSON file. Let's assume it's a JSON string here simply.
            if settings.FIREBASE_CREDENTIALS_JSON:
                import base64
                decoded_creds = base64.b64decode(settings.FIREBASE_CREDENTIALS_JSON).decode('utf-8')
                cred_dict = json.loads(decoded_creds)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
        except Exception as e:
            print(f"Failed to initialize Firebase Admin: {e}")

initialize_firebase()

class PushService:
    @staticmethod
    def send_push_notification(token: str, title: str, body: str, data: dict = None):
        if not firebase_admin._apps:
             return
        
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            token=token,
        )
        try:
            response = messaging.send(message)
            return response
        except Exception as e:
            print(f"Failed to send push notification: {e}")
