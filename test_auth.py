import asyncio
from app.core.supabase_client import supabase_anon
import os
import jwt
from datetime import datetime, timedelta

def test():
    try:
        # Create a fake bypass token
        jwt_secret = os.environ.get("SUPABASE_JWT_SECRET", "super-secret-jwt-token-with-at-least-32-characters-long")
        payload = {
            "sub": "test-id",
            "role": "authenticated",
            "exp": datetime.utcnow() + timedelta(days=7)
        }
        token = jwt.encode(payload, jwt_secret, algorithm="HS256")
        
        # Test decode without verify
        decoded = jwt.decode(token, options={"verify_signature": False})
        print("Decoded without verify:", decoded)
        
    except Exception as e:
        print(f"Error: {e}")

test()
