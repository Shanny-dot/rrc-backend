"""
Update event images from reliiancerewards.com.au
"""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY")
supabase = create_client(url, key)

BASE = "https://reliiancerewards.com.au"

event_images = [
    ("Property Investment Seminar", f"{BASE}/images/1.jpg"),
    ("Wealth & Finance Workshop", f"{BASE}/images/3.jpg"),
    ("Personal Growth & Networking Night", f"{BASE}/images/4.jpg"),
    ("First Home Buyers Info Session", f"{BASE}/images/5.jpg"),
]

print(f"Updating images for {len(event_images)} events...")

updated = 0
for title, img_url in event_images:
    resp = supabase.table("events").update({"image_url": img_url}).eq("title", title).execute()
    if resp.data:
        print(f"  ✓ {title}")
        updated += 1
    else:
        print(f"  ✗ NOT FOUND: {title}")

print(f"\nDone! Updated: {updated}/{len(event_images)}")
