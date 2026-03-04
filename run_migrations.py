import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def run_migrations():
    if not DATABASE_URL:
        print("DATABASE_URL not found in .env")
        return

    print(f"Connecting to database...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cursor = conn.cursor()

        migration_file = "db/migrations/001_initial.sql"
        print(f"Reading {migration_file}...")
        
        with open(migration_file, "r") as f:
            sql = f.read()

        print("Executing migration SQL...")
        cursor.execute(sql)
        
        print("Migration executed successfully!")
        
    except Exception as e:
        print(f"Error executing migration: {e}")
    finally:
        if 'conn' in locals() and conn:
            cursor.close()
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    run_migrations()
