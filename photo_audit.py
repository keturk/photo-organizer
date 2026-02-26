#!/usr/bin/env python3
"""
Photo Collection Audit Tool - Phase 0
Scans photos/videos, extracts EXIF metadata, detects misplaced files.
Stores results in SQLite for subsequent pipeline phases.

Usage:
    python3 photo_audit.py                    # Full scan
    python3 photo_audit.py --report-only      # Just show report from existing data
    python3 photo_audit.py --resume           # Continue interrupted scan
"""

import subprocess
import json
import os
import sys
import re
import argparse
import time
from datetime import datetime

from config import MEDIA_ROOT, DB_PATH, ALL_MEDIA, PHOTO_EXTENSIONS, SKIP_DIRS
from db import init_db


# ── Metadata Parsing ───────────────────────────────────────────

def extract_folder_date(filepath, media_root):
    """Extract year and month from folder structure like .../photos/2024/2024 01/"""
    rel_path = os.path.relpath(filepath, media_root)
    parts = rel_path.split(os.sep)

    year = None
    month = None

    for part in parts:
        ym_match = re.match(r'^(\d{4})\s+(\d{2})', part.strip())
        if ym_match:
            year = int(ym_match.group(1))
            month = int(ym_match.group(2))
            continue

        y_match = re.match(r'^(\d{4})$', part.strip())
        if y_match:
            year = int(y_match.group(1))

    return year, month


def parse_exif_date(date_str):
    """Parse EXIF date string to (year, month)."""
    if not date_str or date_str == '-' or str(date_str).startswith('0000'):
        return None, None
    match = re.match(r'(\d{4}):(\d{2}):(\d{2})', str(date_str))
    if match:
        y, m = int(match.group(1)), int(match.group(2))
        if 1800 <= y <= 2030 and 1 <= m <= 12:
            return y, m
    return None, None


def parse_gps(val):
    """Parse GPS numeric value from exiftool."""
    if val is None or val == '-' or val == '':
        return None
    try:
        f = float(val)
        return f if f != 0.0 else None
    except (ValueError, TypeError):
        return None


# ── Directory Discovery ────────────────────────────────────────

def discover_directories(root):
    """Find all directories containing media files."""
    dirs = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        has_media = any(
            os.path.splitext(f)[1].lower() in ALL_MEDIA
            for f in filenames
        )
        if has_media:
            dirs.append(dirpath)
    return sorted(dirs)


# ── Scanning ───────────────────────────────────────────────────

def scan_directory(directory, conn, media_root):
    """Scan one directory with exiftool in batch JSON mode."""

    cur = conn.execute("SELECT 1 FROM scan_progress WHERE directory = ?", (directory,))
    if cur.fetchone():
        return 0, True

    try:
        result = subprocess.run(
            [
                'exiftool', '-json', '-q',
                '-DateTimeOriginal', '-CreateDate', '-ModifyDate',
                '-Make', '-Model',
                '-GPSLatitude#', '-GPSLongitude#', '-GPSAltitude#',
                '-FileSize#',
                directory
            ],
            capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        print(f"\n  ⚠️  Timeout on {directory}")
        return 0, False

    if not result.stdout.strip():
        conn.execute(
            "INSERT OR REPLACE INTO scan_progress VALUES (?, 0, ?)",
            (directory, datetime.now().isoformat())
        )
        conn.commit()
        return 0, False

    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"\n  ⚠️  JSON error in {directory}")
        return 0, False

    count = 0
    for item in items:
        filepath = item.get('SourceFile', '')
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in ALL_MEDIA:
            continue

        file_type = 'photo' if ext in PHOTO_EXTENSIONS else 'video'

        exif_date = (item.get('DateTimeOriginal')
                     or item.get('CreateDate')
                     or item.get('ModifyDate'))
        exif_year, exif_month = parse_exif_date(exif_date)
        folder_year, folder_month = extract_folder_date(filepath, media_root)

        gps_lat = parse_gps(item.get('GPSLatitude'))
        gps_lon = parse_gps(item.get('GPSLongitude'))
        gps_alt = parse_gps(item.get('GPSAltitude'))

        date_mismatch = 0
        mismatch_years = 0
        mismatch_detail = None
        needs_review = 0

        if exif_year and folder_year and exif_year != folder_year:
            date_mismatch = 1
            mismatch_years = abs(exif_year - folder_year)
            camera = item.get('Model', 'Unknown')
            mismatch_detail = (
                f"EXIF={exif_year}-{exif_month:02d}, "
                f"Folder={folder_year}, Camera={camera}"
            )
            if mismatch_years > 2:
                needs_review = 1

        has_exif_date = 1 if exif_year else 0
        has_gps = 1 if (gps_lat is not None and gps_lon is not None) else 0

        try:
            conn.execute("""
                INSERT OR REPLACE INTO files
                (filepath, filename, extension, file_type, file_size,
                 folder_year, folder_month, exif_date, exif_year, exif_month,
                 camera_make, camera_model,
                 gps_latitude, gps_longitude, gps_altitude,
                 has_exif_date, has_gps, date_mismatch, mismatch_years,
                 mismatch_detail, needs_review, processed_at)
                VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?)
            """, (
                filepath, os.path.basename(filepath), ext, file_type,
                item.get('FileSize'),
                folder_year, folder_month,
                str(exif_date) if exif_date else None, exif_year, exif_month,
                item.get('Make'), item.get('Model'),
                gps_lat, gps_lon, gps_alt,
                has_exif_date, has_gps, date_mismatch, mismatch_years,
                mismatch_detail, needs_review,
                datetime.now().isoformat()
            ))
            count += 1
        except Exception as e:
            print(f"\n  ⚠️  DB error: {e}")

    conn.execute(
        "INSERT OR REPLACE INTO scan_progress VALUES (?, ?, ?)",
        (directory, count, datetime.now().isoformat())
    )
    conn.commit()
    return count, False


# ── Report ─────────────────────────────────────────────────────

def print_report(conn):
    """Print a summary report of the collection audit."""
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    if total == 0:
        print("❌ No files in database. Run a scan first.")
        return

    photos = conn.execute("SELECT COUNT(*) FROM files WHERE file_type='photo'").fetchone()[0]
    videos = conn.execute("SELECT COUNT(*) FROM files WHERE file_type='video'").fetchone()[0]
    with_date = conn.execute("SELECT COUNT(*) FROM files WHERE has_exif_date=1").fetchone()[0]
    without_date = total - with_date
    with_gps = conn.execute("SELECT COUNT(*) FROM files WHERE has_gps=1").fetchone()[0]
    without_gps = total - with_gps
    mismatches = conn.execute("SELECT COUNT(*) FROM files WHERE date_mismatch=1").fetchone()[0]
    review = conn.execute("SELECT COUNT(*) FROM files WHERE needs_review=1").fetchone()[0]

    print()
    print("=" * 70)
    print("  📊  PHOTO COLLECTION AUDIT REPORT")
    print("=" * 70)
    print(f"""
  📁 Total files:         {total:>8,}
     📷 Photos:           {photos:>8,}
     🎥 Videos:           {videos:>8,}

  📅 Date metadata:
     ✅ With EXIF date:   {with_date:>8,}  ({with_date/total*100:.1f}%)
     ❌ Missing date:     {without_date:>8,}  ({without_date/total*100:.1f}%)

  📍 GPS metadata:
     ✅ With GPS:         {with_gps:>8,}  ({with_gps/total*100:.1f}%)
     ❌ Missing GPS:      {without_gps:>8,}  ({without_gps/total*100:.1f}%)

  ⚠️  Date mismatches:    {mismatches:>8,}  (EXIF year ≠ folder year)
  🔍 Needs review:        {review:>8,}  (mismatch > 2 years)
""")

    if mismatches > 0:
        print("  ── Mismatch Breakdown ──────────────────────────────────────")
        rows = conn.execute("""
            SELECT folder_year, exif_year, camera_model, COUNT(*) as cnt
            FROM files WHERE date_mismatch=1
            GROUP BY folder_year, exif_year, camera_model
            ORDER BY cnt DESC LIMIT 20
        """).fetchall()
        print(f"  {'Folder':>8}  →  {'EXIF':>8}  {'Camera':<30}  {'Count':>6}")
        print(f"  {'─'*8}     {'─'*8}  {'─'*30}  {'─'*6}")
        for r in rows:
            print(f"  {r[0] or '?':>8}  →  {r[1] or '?':>8}  {(r[2] or 'Unknown'):<30}  {r[3]:>6,}")
        print()

    print("  ── Camera Models ──────────────────────────────────────────")
    rows = conn.execute("""
        SELECT COALESCE(camera_make,'') || ' ' || COALESCE(camera_model,'') as cam,
               COUNT(*) as cnt
        FROM files
        WHERE camera_make IS NOT NULL OR camera_model IS NOT NULL
        GROUP BY cam ORDER BY cnt DESC LIMIT 12
    """).fetchall()
    for r in rows:
        print(f"     {r[0]:<40}  {r[1]:>8,}")
    print()

    print("  ── Files by Decade ────────────────────────────────────────")
    rows = conn.execute("""
        SELECT (folder_year / 10) * 10 as decade, COUNT(*) as cnt
        FROM files WHERE folder_year IS NOT NULL
        GROUP BY decade ORDER BY decade
    """).fetchall()
    if rows:
        max_cnt = max(r[1] for r in rows)
        for r in rows:
            bar = '█' * max(1, int(r[1] / max_cnt * 40))
            print(f"     {r[0]}s  {bar} {r[1]:,}")
    print()

    print("  ── File Types ─────────────────────────────────────────────")
    rows = conn.execute("""
        SELECT extension, COUNT(*) as cnt
        FROM files GROUP BY extension ORDER BY cnt DESC
    """).fetchall()
    for r in rows:
        print(f"     {r[0]:<10}  {r[1]:>8,}")

    print()
    print("=" * 70)
    print(f"  Database: {DB_PATH}")
    print("=" * 70)
    print()


# ── Main ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Photo Collection Audit Tool")
    parser.add_argument('--root', default=MEDIA_ROOT, help='Media root directory')
    parser.add_argument('--db', default=DB_PATH, help='SQLite database path')
    parser.add_argument('--folder', type=str,
                        help='Scan only this specific folder (and subfolders)')
    parser.add_argument('--report-only', action='store_true',
                        help='Only print report from existing data')
    parser.add_argument('--resume', action='store_true',
                        help='Resume interrupted scan')
    args = parser.parse_args()

    conn = init_db(args.db)

    if args.report_only:
        print_report(conn)
        conn.close()
        return

    print()
    print("  🔍 Photo Collection Audit Tool")
    print(f"     Source:   {args.root}")
    print(f"     Database: {args.db}")
    print()

    # Check exiftool
    try:
        subprocess.run(['exiftool', '-ver'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("  ❌ exiftool not found. Install: sudo apt install libimage-exiftool-perl")
        sys.exit(1)

    # Discover directories
    print("  📂 Discovering directories...", flush=True)
    all_dirs = []
    if args.folder:
        folder = args.folder.rstrip("/")
        if os.path.isdir(folder):
            all_dirs = discover_directories(folder)
        else:
            print(f"  ❌ Folder not found: {folder}")
            sys.exit(1)
    else:
        for sub in ['photos', 'videos']:
            sub_path = os.path.join(args.root, sub)
            if os.path.exists(sub_path):
                all_dirs.extend(discover_directories(sub_path))

    already_done = conn.execute("SELECT COUNT(*) FROM scan_progress").fetchone()[0]
    remaining = len(all_dirs) - already_done
    print(f"     Found {len(all_dirs)} directories "
          f"({already_done} already scanned, {remaining} remaining)")
    print()

    if remaining == 0:
        print("  ✅ All directories already scanned!")
        print_report(conn)
        conn.close()
        return

    total_new = 0
    scanned = 0
    start_time = time.time()

    for directory in all_dirs:
        rel_dir = os.path.relpath(directory, args.root)
        count, skipped = scan_directory(directory, conn, args.root)

        if skipped:
            continue

        scanned += 1
        total_new += count
        elapsed = time.time() - start_time
        rate = scanned / elapsed if elapsed > 0 else 0
        eta = (remaining - scanned) / rate if rate > 0 else 0

        print(f"  [{already_done + scanned}/{len(all_dirs)}] "
              f"{rel_dir:<50} +{count:<5} "
              f"(ETA: {int(eta//60)}m {int(eta%60)}s)", flush=True)

    elapsed = time.time() - start_time
    print(f"\n  ✅ Scan complete in {int(elapsed//60)}m {int(elapsed%60)}s")
    print(f"     {total_new:,} new files cataloged")

    print_report(conn)
    conn.close()


if __name__ == "__main__":
    main()
