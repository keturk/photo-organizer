"""
Database initialization and helpers for Photo Organizer.
"""

import sqlite3
from config import DB_PATH


def init_db(db_path=None):
    """Initialize SQLite database with schema and return connection."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT UNIQUE,
            filename TEXT,
            extension TEXT,
            file_type TEXT,
            file_size INTEGER,
            folder_year INTEGER,
            folder_month INTEGER,
            exif_date TEXT,
            exif_year INTEGER,
            exif_month INTEGER,
            camera_make TEXT,
            camera_model TEXT,
            gps_latitude REAL,
            gps_longitude REAL,
            gps_altitude REAL,
            has_exif_date INTEGER DEFAULT 0,
            has_gps INTEGER DEFAULT 0,
            date_mismatch INTEGER DEFAULT 0,
            mismatch_years INTEGER DEFAULT 0,
            mismatch_detail TEXT,
            ai_tags TEXT,
            ai_description TEXT,
            ai_location_guess TEXT,
            needs_review INTEGER DEFAULT 0,
            processed_at TEXT,
            ai_processed_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_progress (
            directory TEXT PRIMARY KEY,
            file_count INTEGER,
            scanned_at TEXT
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_mismatch ON files(date_mismatch)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_has_gps ON files(has_gps)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_has_date ON files(has_exif_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_folder_year ON files(folder_year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exif_year ON files(exif_year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_needs_review ON files(needs_review)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_processed ON files(ai_processed_at)")
    conn.commit()
    return conn


def get_db(db_path=None):
    """Get a database connection with Row factory for dict-like access."""
    import os
    path = db_path or DB_PATH
    if not os.path.exists(path):
        print(f"Error: Database not found at {path}")
        print("Run photo_audit.py first to scan the collection.")
        raise SystemExit(1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
