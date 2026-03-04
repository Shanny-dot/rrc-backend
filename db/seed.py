import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta

load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(url, key)

def seed():
    print("Beginning Database Seed via Supabase Client...")
    
    # 1. Seed Events
    events = [
        {
            "title": "Property Investment Workshop",
            "description": "Learn the basics of property investment in 2026.",
            "location": "Online Webinar",
            "event_date": (datetime.now() + timedelta(days=14)).isoformat(),
            "image_url": "https://picsum.photos/id/10/800/400",
            "points_for_attending": 50,
            "points_for_referring": 20,
            "capacity": 100,
            "is_active": True
        },
        {
            "title": "First Home Buyers Breakfast",
            "description": "Network and learn about grants available.",
            "location": "Sydney CBD",
            "event_date": (datetime.now() + timedelta(days=5)).isoformat(),
            "image_url": "https://picsum.photos/id/20/800/400",
            "points_for_attending": 100,
            "points_for_referring": 50,
            "capacity": 50,
            "is_active": True
        },
        {
            "title": "Wealth Creation Seminar",
            "description": "Advanced strategies for portfolio growth.",
            "location": "Melbourne Office",
            "event_date": (datetime.now() + timedelta(days=30)).isoformat(),
            "image_url": "https://picsum.photos/id/30/800/400",
            "points_for_attending": 75,
            "points_for_referring": 25,
            "capacity": 200,
            "is_active": True
        },
        {
            "title": "End of Year Gala",
            "description": "Celebrate successes with top referrers.",
            "location": "Gold Coast Resort",
            "event_date": (datetime.now() + timedelta(days=60)).isoformat(),
            "image_url": "https://picsum.photos/id/40/800/400",
            "points_for_attending": 200,
            "points_for_referring": 0,
            "capacity": 150,
            "is_active": True
        },
         {
            "title": "Q3 Market Wrap-up",
            "description": "Live Q&A covering recent market shifts.",
            "location": "Online Webinar",
            "event_date": (datetime.now() + timedelta(days=7)).isoformat(),
            "image_url": "https://picsum.photos/id/50/800/400",
            "points_for_attending": 25,
            "points_for_referring": 10,
            "capacity": 500,
            "is_active": True
        }
    ]

    print("Inserting 5 Events...")
    for ev in events:
         try:
              supabase.table("events").insert(ev).execute()
         except Exception as e:
              print(f"Skipping event insert (may exist): {e}")

    # 2. Seed Rewards
    rewards = [
        {
            "title": "Hoyts Movie Ticket",
            "description": "General admission for 1 adult.",
            "category": "Experiences",
            "points_required": 100,
            "image_url": "https://picsum.photos/id/100/400/300",
            "stock": 50,
            "is_active": True
        },
        {
            "title": "$50 Coles Voucher",
            "description": "Digital gift card for Coles supermarkets.",
            "category": "Shopping",
            "points_required": 250,
            "image_url": "https://picsum.photos/id/101/400/300",
            "stock": 100,
            "is_active": True
        },
         {
            "title": "Airbnb $100 Credit",
            "description": "Credit towards your next stay.",
            "category": "Travel",
            "points_required": 500,
            "image_url": "https://picsum.photos/id/102/400/300",
            "stock": 20,
            "is_active": True
        },
         {
            "title": "Apple AirPods Pro",
            "description": "Latest generation noise-cancelling headphones.",
            "category": "Electronics",
            "points_required": 2500,
            "image_url": "https://picsum.photos/id/103/400/300",
            "stock": 5,
            "is_active": True
        },
         {
            "title": "Exclusive VIP Property Tour",
            "description": "Private viewing of off-market prestige properties.",
            "category": "Experiences",
            "points_required": 5000,
            "image_url": "https://picsum.photos/id/104/400/300",
            "stock": 2,
            "is_active": True
        }
    ]

    print("Inserting 5 Rewards...")
    for rew in rewards:
         try:
             supabase.table("rewards").insert(rew).execute()
         except Exception as e:
             print(f"Skipping reward insert (may exist): {e}")

    print("Seed Complete!")

if __name__ == "__main__":
    seed()
