import sqlite3
import re
import os

try:
    import psycopg2
except ImportError:
    pass

from services.db_service import db_service

def fix_semester_names():
    rows = db_service.query("SELECT id, name FROM semesters")
    updated = 0
    if not rows:
        print("No semesters found.")
        return
        
    for row in rows:
        name = row["name"]
        match = re.match(r"(c\d+)_(\d+)(?:st|nd|rd|th)_sem\s*-\s*([A-Za-z0-9_]+)\s*\((SBTET_[A-Z]+)\)", name, re.IGNORECASE)
        if match:
            curriculum = match.group(1).upper()
            sem = match.group(2)
            group = match.group(3).upper()
            board_raw = match.group(4).upper()
            
            board = "TG SBTET" if board_raw == "SBTET_TG" else ("AP SBTET" if board_raw == "SBTET_AP" else board_raw)
            
            new_name = f"{curriculum} SEM {sem} - {board} {group}"
            
            print(f"Updating '{name}' -> '{new_name}'")
            db_service.execute("UPDATE semesters SET name = %s WHERE id = %s" if os.getenv("VERCEL") else "UPDATE semesters SET name = ? WHERE id = ?", (new_name, row["id"]))
            updated += 1
            
    print(f"Updated {updated} semesters.")

if __name__ == "__main__":
    fix_semester_names()

