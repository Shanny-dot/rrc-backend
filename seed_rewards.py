"""
Seed rewards from reliiancerewards.com.au into the RRC database.
"""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY")
supabase = create_client(url, key)

# All rewards scraped from https://reliiancerewards.com.au/rewards.php
rewards = [
    # Experiences
    {"title": "Whale Watching Cruises", "description": "Enjoy a scenic whale watching cruise along the beautiful Australian coastline. An unforgettable wildlife experience.", "category": "Experiences", "points_required": 100, "stock": 20, "is_active": True},
    {"title": "Bridge Climb", "description": "Climb the iconic Sydney Harbour Bridge for breathtaking panoramic views of the city and harbour.", "category": "Experiences", "points_required": 400, "stock": 10, "is_active": True},
    {"title": "Health & Wellness Package", "description": "Treat yourself to a luxurious health and wellness spa package. Includes massage, facial, and relaxation treatments.", "category": "Experiences", "points_required": 150, "stock": 30, "is_active": True},
    {"title": "Seaplane Ride", "description": "Take to the skies on a scenic seaplane flight over Sydney Harbour and the Northern Beaches.", "category": "Experiences", "points_required": 400, "stock": 10, "is_active": True},
    {"title": "Helicopter Flight Experience", "description": "Soar above the city in a thrilling helicopter flight experience with stunning aerial views.", "category": "Experiences", "points_required": 300, "stock": 8, "is_active": True},
    {"title": "Tandem Skydive", "description": "Experience the ultimate adrenaline rush with a tandem skydive from 14,000 feet.", "category": "Experiences", "points_required": 300, "stock": 15, "is_active": True},
    {"title": "Hot Air Ballooning", "description": "Float serenely over the countryside at sunrise in a magical hot air balloon ride.", "category": "Experiences", "points_required": 400, "stock": 12, "is_active": True},

    # Dining
    {"title": "Dinner Voucher For 2", "description": "Enjoy a fine dining experience for two at a premium partner restaurant.", "category": "Dining", "points_required": 100, "stock": 50, "is_active": True},
    {"title": "Gold Class Movie Tickets", "description": "Two Gold Class movie tickets for a luxury cinema experience with reclining seats and in-seat dining.", "category": "Dining", "points_required": 100, "stock": 100, "is_active": True},

    # Shopping - $50 tier
    {"title": "Rebel Gift Card ($50)", "description": "$50 Rebel Sport gift card. Perfect for sports and fitness enthusiasts.", "category": "Shopping", "points_required": 150, "stock": 50, "is_active": True},
    {"title": "David Jones Gift Card ($50)", "description": "$50 David Jones gift card. Shop fashion, beauty, home and more.", "category": "Shopping", "points_required": 150, "stock": 50, "is_active": True},
    {"title": "Freedom Gift Card ($50)", "description": "$50 Freedom Furniture gift card. Upgrade your home with stylish furniture.", "category": "Shopping", "points_required": 150, "stock": 50, "is_active": True},
    {"title": "JB HI FI Gift Card ($50)", "description": "$50 JB Hi-Fi gift card for the latest tech, music, movies and games.", "category": "Shopping", "points_required": 150, "stock": 50, "is_active": True},
    {"title": "Woolworths Gift Card ($50)", "description": "$50 Woolworths gift card for groceries, fresh food and everyday essentials.", "category": "Shopping", "points_required": 150, "stock": 100, "is_active": True},

    # Shopping - $100 tier
    {"title": "Rebel Gift Card ($100)", "description": "$100 Rebel Sport gift card. More value for sports gear and activewear.", "category": "Shopping", "points_required": 300, "stock": 30, "is_active": True},
    {"title": "David Jones Gift Card ($100)", "description": "$100 David Jones gift card. Premium shopping experience.", "category": "Shopping", "points_required": 300, "stock": 30, "is_active": True},
    {"title": "Freedom Gift Card ($100)", "description": "$100 Freedom Furniture gift card for your dream home makeover.", "category": "Shopping", "points_required": 300, "stock": 30, "is_active": True},
    {"title": "Woolworths Gift Card ($100)", "description": "$100 Woolworths gift card. Stock up on everything you need.", "category": "Shopping", "points_required": 300, "stock": 50, "is_active": True},

    # Shopping - Premium tier
    {"title": "David Jones Gift Card ($200)", "description": "$200 David Jones gift card. The ultimate premium shopping experience.", "category": "Shopping", "points_required": 600, "stock": 15, "is_active": True},
    {"title": "Toy World Card", "description": "Toy World gift card for kids' toys, games and fun for all ages.", "category": "Shopping", "points_required": 50, "stock": 80, "is_active": True},
]

print(f"Seeding {len(rewards)} rewards into database...")

# Check existing rewards to avoid duplicates
existing = supabase.table("rewards").select("title").execute()
existing_titles = {r["title"] for r in (existing.data or [])}

inserted = 0
skipped = 0
for reward in rewards:
    if reward["title"] in existing_titles:
        print(f"  SKIP (exists): {reward['title']}")
        skipped += 1
        continue
    
    try:
        supabase.table("rewards").insert(reward).execute()
        print(f"  ADDED: {reward['title']} ({reward['points_required']} pts)")
        inserted += 1
    except Exception as e:
        print(f"  ERROR: {reward['title']}: {e}")

print(f"\nDone! Inserted: {inserted}, Skipped: {skipped}, Total: {len(rewards)}")
