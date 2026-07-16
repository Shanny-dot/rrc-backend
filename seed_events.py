"""
Seed dummy events into the RRC database for testing (admin app + mobile app).
"""
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY")
supabase = create_client(url, key)

now = datetime.utcnow()

events = [
    {
        "title": "Property Investment Seminar",
        "description": "Learn the fundamentals of property investment, market trends, and financing strategies from industry experts.",
        "location": "Sydney Convention Centre, NSW",
        "event_date": (now + timedelta(days=7)).isoformat(),
        "image_url": "https://reliiancerewards.com.au/images/1.jpg",
        "points_for_attending": 50,
        "points_for_referring": 25,
        "capacity": 100,
        "is_active": True,
    },
    {
        "title": "Wealth & Finance Workshop",
        "description": "An interactive workshop covering budgeting, superannuation, and long-term wealth building strategies.",
        "location": "Melbourne CBD, VIC",
        "event_date": (now + timedelta(days=14)).isoformat(),
        "image_url": "https://reliiancerewards.com.au/images/3.jpg",
        "points_for_attending": 75,
        "points_for_referring": 30,
        "capacity": 60,
        "is_active": True,
    },
    {
        "title": "Personal Growth & Networking Night",
        "description": "An evening of networking, guest speakers, and personal development talks. Light refreshments provided.",
        "location": "Brisbane Riverside Hall, QLD",
        "event_date": (now + timedelta(days=21)).isoformat(),
        "image_url": "https://reliiancerewards.com.au/images/4.jpg",
        "points_for_attending": 40,
        "points_for_referring": 20,
        "capacity": 150,
        "is_active": True,
    },
    {
        "title": "First Home Buyers Info Session",
        "description": "Everything first home buyers need to know about grants, deposits, and the buying process.",
        "location": "Online (Zoom)",
        "event_date": (now + timedelta(days=3)).isoformat(),
        "image_url": "https://reliiancerewards.com.au/images/5.jpg",
        "points_for_attending": 30,
        "points_for_referring": 15,
        "capacity": 200,
        "is_active": True,
    },
]

print(f"Seeding {len(events)} events into database...")

existing = supabase.table("events").select("title").execute()
existing_titles = {e["title"] for e in (existing.data or [])}

inserted = 0
skipped = 0
for event in events:
    if event["title"] in existing_titles:
        print(f"  SKIP (exists): {event['title']}")
        skipped += 1
        continue
    try:
        supabase.table("events").insert(event).execute()
        print(f"  ADDED: {event['title']} on {event['event_date']}")
        inserted += 1
    except Exception as e:
        print(f"  ERROR: {event['title']}: {e}")

print(f"\nDone! Inserted: {inserted}, Skipped: {skipped}, Total: {len(events)}")
