import psycopg2
import os

# Read from the environment; never commit database credentials.
DATABASE_URL = os.environ["DATABASE_URL"]

def main():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # We drop the constraint only if it exists (which postgres allows via ALTER COLUMN rsvp_id DROP NOT NULL)
        cursor.execute("""
            ALTER TABLE event_guests ADD COLUMN IF NOT EXISTS event_id UUID REFERENCES events(id) ON DELETE CASCADE;
            ALTER TABLE event_guests ALTER COLUMN rsvp_id DROP NOT NULL;
        """)
        print("Successfully altered 'event_guests'. Added 'event_id' and made 'rsvp_id' nullable.")
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
