"""
Update reward images from reliiancerewards.com.au
"""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY")
supabase = create_client(url, key)

BASE = "https://reliiancerewards.com.au"

# Mapping: (title_contains, points_required) -> image_url
# Using points to disambiguate duplicate titles like "David Jones Gift Card"
reward_images = [
    ("Whale Watching Cruises", 100, f"{BASE}/rrc_admin/files/fbe1565ae043dc473eb263116cc80f4f.jpg"),
    ("Bridge Climb", 400, f"{BASE}/rrc_admin/files/882f59d8b9db703c9aa78b349695fafb.jpg"),
    ("Health & Wellness Package", 150, f"{BASE}/rrc_admin/files/c250871bf5e9d02de28fc2159ce14944.jpg"),
    ("Seaplane Ride", 400, f"{BASE}/rrc_admin/files/a0be79ec3bd4959d0518756168e98691.jpg"),
    ("Helicopter Flight Experience", 300, f"{BASE}/rrc_admin/files/41f3f2bc8342e7f2ce547c27048b23f8.jpg"),
    ("Tandem Skydive", 300, f"{BASE}/rrc_admin/files/47880218fdded83dd82bf59253b536af.jpg"),
    ("Hot Air Ballooning", 400, f"{BASE}/rrc_admin/files/7bd047a9f79e71c7373a0c3dcd60c906.jpg"),
    ("Dinner Voucher For 2", 100, f"{BASE}/rrc_admin/files/0dd6004e94b700ba93944bb4f0e57497.jpg"),
    ("Gold Class Movie Tickets", 100, f"{BASE}/rrc_admin/files/42a86759fb1818ab41d6d7e1cb2ba338.jpg"),
    ("Rebel Gift Card ($50)", 150, f"{BASE}/rrc_admin/files/029476fe51e971495ca567fb42933b6e.jpg"),
    ("David Jones Gift Card ($50)", 150, f"{BASE}/rrc_admin/files/6f6cdcd191ea5b1274a860739d3c18a8.jpg"),
    ("Freedom Gift Card ($50)", 150, f"{BASE}/rrc_admin/files/8f85ce7119b099ab86d355d3558d3c86.jpg"),
    ("JB HI FI Gift Card ($50)", 150, f"{BASE}/rrc_admin/files/d17015382a4ab24c1f1b3992fca1cd42.jpg"),
    ("Woolworths Gift Card ($50)", 150, f"{BASE}/rrc_admin/files/fee5b095af99a008d9199bbeddec188f.jpg"),
    ("Rebel Gift Card ($100)", 300, f"{BASE}/rrc_admin/files/9b5f5114bbbbae38934c1dbb95d73160.jpg"),
    ("David Jones Gift Card ($100)", 300, f"{BASE}/rrc_admin/files/bc4db5133741e7505ff9eb4280c18d14.jpg"),
    ("Freedom Gift Card ($100)", 300, f"{BASE}/rrc_admin/files/b7599ac5c3e4205de3ef86ef9de2e2a2.jpg"),
    ("Woolworths Gift Card ($100)", 300, f"{BASE}/rrc_admin/files/304833f2bdf68c78caf8c9a3294ffc5c.jpg"),
    ("David Jones Gift Card ($200)", 600, f"{BASE}/rrc_admin/files/7b7638cff4c6d2218e46ac1f2a2e3d01.jpg"),
    ("Toy World Card", 50, f"{BASE}/rrc_admin/files/dcb79dc434588845975a3d44231a54fd.jpg"),
]

print(f"Updating images for {len(reward_images)} rewards...")

updated = 0
for title, pts, img_url in reward_images:
    resp = supabase.table("rewards").update({"image_url": img_url}).eq("title", title).eq("points_required", pts).execute()
    if resp.data:
        print(f"  ✓ {title} ({pts}pts)")
        updated += 1
    else:
        print(f"  ✗ NOT FOUND: {title} ({pts}pts)")

print(f"\nDone! Updated: {updated}/{len(reward_images)}")
