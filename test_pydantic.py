from app.schemas.event import EventCreate
from datetime import datetime
import json

try:
    e = EventCreate(title="Test", event_date=datetime.now(), points_for_attending=10, points_for_referring=10, capacity=10)
    print("Dict:", e.dict())
    
    # Try json()
    s = e.json()
    print("JSON string:", s)
    
    # Try json.loads
    d = json.loads(s)
    print("Loaded dict:", d)
except Exception as ex:
    print("ERROR:", ex)
