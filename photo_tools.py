#!/usr/bin/env python3
"""
Photo Tools CLI - IronClaw Integration Layer
Called by IronClaw to query, analyze, and tag the photo collection.
Depends on photo_audit.py having populated the SQLite database first.

Commands:
    photo_tools.py stats                          # Collection overview
    photo_tools.py mismatches [--limit N]         # Date mismatch report
    photo_tools.py query [filters]                # Search photos
    photo_tools.py analyze <filepath>             # AI vision on single photo
    photo_tools.py batch-analyze [filters]        # AI vision on batch
    photo_tools.py tag <filepath> [--keywords ..] # Write IPTC/XMP tags
    photo_tools.py batch-tag [filters]            # Write tags from AI results
    photo_tools.py propagate-gps                  # Fill GPS gaps from neighbors
    photo_tools.py review-mismatches              # Review date misplacements
"""

import subprocess
import json
import os
import sys
import base64
import argparse
import re
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

from config import (
    MEDIA_ROOT, DB_PATH, OLLAMA_URL, VISION_MODEL, VISION_PROMPT,
    GPS_WINDOW_HOURS, BATCH_SIZE
)
from db import get_db


def _check_ollama():
    """Verify Ollama is reachable. Fail fast if not."""
    try:
        req = Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urlopen(req, timeout=5) as resp:
            resp.read()
    except (URLError, OSError) as e:
        print(f"ERROR: Cannot reach Ollama at {OLLAMA_URL}", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print("Check that Ollama is running and OLLAMA_URL in .env is correct.", file=sys.stderr)
        sys.exit(1)


# ── Commands ───────────────────────────────────────────────────

def cmd_stats(args):
    """Show collection statistics."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    photos = conn.execute("SELECT COUNT(*) FROM files WHERE file_type='photo'").fetchone()[0]
    videos = conn.execute("SELECT COUNT(*) FROM files WHERE file_type='video'").fetchone()[0]
    with_date = conn.execute("SELECT COUNT(*) FROM files WHERE has_exif_date=1").fetchone()[0]
    with_gps = conn.execute("SELECT COUNT(*) FROM files WHERE has_gps=1").fetchone()[0]
    mismatches = conn.execute("SELECT COUNT(*) FROM files WHERE date_mismatch=1").fetchone()[0]
    review = conn.execute("SELECT COUNT(*) FROM files WHERE needs_review=1").fetchone()[0]
    ai_done = conn.execute("SELECT COUNT(*) FROM files WHERE ai_processed_at IS NOT NULL").fetchone()[0]

    print(json.dumps({
        "total_files": total,
        "photos": photos,
        "videos": videos,
        "with_exif_date": with_date,
        "without_exif_date": total - with_date,
        "with_gps": with_gps,
        "without_gps": total - with_gps,
        "date_mismatches": mismatches,
        "needs_review": review,
        "ai_analyzed": ai_done,
        "ai_pending": total - ai_done,
        "pct_with_date": round(with_date / total * 100, 1) if total else 0,
        "pct_with_gps": round(with_gps / total * 100, 1) if total else 0,
        "pct_ai_done": round(ai_done / total * 100, 1) if total else 0
    }, indent=2))
    conn.close()


def cmd_mismatches(args):
    """Show files where EXIF date doesn't match folder year."""
    conn = get_db()
    limit = args.limit or 20

    rows = conn.execute("""
        SELECT filepath, filename, folder_year, exif_year, exif_month,
               camera_make, camera_model, mismatch_years, extension
        FROM files
        WHERE date_mismatch = 1
        ORDER BY mismatch_years DESC
        LIMIT ?
    """, (limit,)).fetchall()

    results = []
    for r in rows:
        results.append({
            "filepath": r["filepath"],
            "filename": r["filename"],
            "folder_year": r["folder_year"],
            "exif_year": r["exif_year"],
            "exif_month": r["exif_month"],
            "camera": f"{r['camera_make'] or ''} {r['camera_model'] or ''}".strip(),
            "mismatch_years": r["mismatch_years"],
            "extension": r["extension"]
        })

    summary = conn.execute("""
        SELECT COUNT(*) as cnt,
               SUM(CASE WHEN mismatch_years > 10 THEN 1 ELSE 0 END) as severe,
               SUM(CASE WHEN mismatch_years BETWEEN 3 AND 10 THEN 1 ELSE 0 END) as moderate,
               SUM(CASE WHEN mismatch_years < 3 THEN 1 ELSE 0 END) as minor
        FROM files WHERE date_mismatch = 1
    """).fetchone()

    print(json.dumps({
        "total_mismatches": summary["cnt"],
        "severe_over_10yr": summary["severe"],
        "moderate_3_10yr": summary["moderate"],
        "minor_under_3yr": summary["minor"],
        "top_mismatches": results
    }, indent=2))
    conn.close()


def cmd_query(args):
    """Search photos with filters."""
    conn = get_db()

    conditions = []
    params = []

    if args.year:
        conditions.append("folder_year = ?")
        params.append(args.year)
    if args.exif_year:
        conditions.append("exif_year = ?")
        params.append(args.exif_year)
    if args.no_gps:
        conditions.append("has_gps = 0")
    if args.has_gps:
        conditions.append("has_gps = 1")
    if args.no_date:
        conditions.append("has_exif_date = 0")
    if args.camera:
        conditions.append("(camera_make LIKE ? OR camera_model LIKE ?)")
        params.extend([f"%{args.camera}%", f"%{args.camera}%"])
    if args.extension:
        conditions.append("extension = ?")
        params.append(f".{args.extension.lower().lstrip('.')}")
    if args.mismatch:
        conditions.append("date_mismatch = 1")
    if args.needs_review:
        conditions.append("needs_review = 1")
    if args.not_analyzed:
        conditions.append("ai_processed_at IS NULL")
    if args.analyzed:
        conditions.append("ai_processed_at IS NOT NULL")
    if args.tag:
        conditions.append("ai_tags LIKE ?")
        params.append(f"%{args.tag}%")
    if args.file_type:
        conditions.append("file_type = ?")
        params.append(args.file_type)

    where = " AND ".join(conditions) if conditions else "1=1"
    limit = args.limit or 20

    count = conn.execute(
        f"SELECT COUNT(*) FROM files WHERE {where}", params
    ).fetchone()[0]

    rows = conn.execute(f"""
        SELECT filepath, filename, folder_year, exif_year, exif_month,
               camera_model, has_gps, has_exif_date, date_mismatch,
               ai_tags, ai_description, extension
        FROM files WHERE {where}
        ORDER BY folder_year DESC, filepath
        LIMIT ?
    """, params + [limit]).fetchall()

    results = []
    for r in rows:
        entry = {
            "filepath": r["filepath"],
            "filename": r["filename"],
            "folder_year": r["folder_year"],
            "exif_year": r["exif_year"],
            "camera": r["camera_model"],
            "has_gps": bool(r["has_gps"]),
            "has_date": bool(r["has_exif_date"]),
            "mismatch": bool(r["date_mismatch"])
        }
        if r["ai_tags"]:
            entry["ai_tags"] = r["ai_tags"]
        if r["ai_description"]:
            entry["ai_description"] = r["ai_description"]
        results.append(entry)

    print(json.dumps({
        "total_matching": count,
        "showing": len(results),
        "results": results
    }, indent=2))
    conn.close()


def _collect_context(filepath):
    """Collect .context.txt hints from photo dir up to MEDIA_ROOT."""
    hints = []
    directory = os.path.dirname(os.path.abspath(filepath))
    root = os.path.abspath(MEDIA_ROOT)
    while True:
        ctx_file = os.path.join(directory, ".context.txt")
        if os.path.isfile(ctx_file):
            with open(ctx_file) as f:
                text = f.read().strip()
                if text:
                    hints.append(text)
        if os.path.normcase(directory) == os.path.normcase(root) or directory == os.path.dirname(directory):
            break
        directory = os.path.dirname(directory)
    # Reverse so top-level context comes first
    hints.reverse()
    return "\n".join(hints) if hints else None


def _send_to_vision(filepath):
    """Send an image to the Ollama vision API and return the analysis."""
    ext = os.path.splitext(filepath)[1].lower()

    if ext in {'.mp4', '.mov', '.avi', '.mts', '.3gp'}:
        return None, "Video analysis not yet supported. Extract frames first."

    # HEIC → JPEG conversion
    if ext == '.heic':
        try:
            temp_path = "/tmp/photo_analyze_temp.jpg"
            subprocess.run(
                ['convert', filepath, temp_path],
                capture_output=True, check=True, timeout=30
            )
            with open(temp_path, 'rb') as f:
                img_data = base64.b64encode(f.read()).decode('utf-8')
            os.remove(temp_path)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None, "Cannot convert HEIC. Install: sudo apt install imagemagick"
    else:
        with open(filepath, 'rb') as f:
            img_data = base64.b64encode(f.read()).decode('utf-8')

    prompt = VISION_PROMPT
    context = _collect_context(filepath)
    if context:
        prompt += f"\n\nBackground context for this photo:\n{context}"

    payload = json.dumps({
        "model": VISION_MODEL,
        "prompt": prompt,
        "images": [img_data],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 4096}
    }).encode('utf-8')

    req = Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    start = time.time()
    with urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode('utf-8'))
    elapsed = time.time() - start

    response_text = result.get("response", "")

    # Parse JSON from response
    try:
        cleaned = re.sub(r'^```json\s*', '', response_text.strip())
        cleaned = re.sub(r'\s*```$', '', cleaned)
        analysis = json.loads(cleaned)
    except json.JSONDecodeError:
        analysis = {"raw_response": response_text}

    return analysis, elapsed


def cmd_analyze(args):
    """Send a single photo to qwen3-vl for AI analysis."""
    _check_ollama()
    filepath = args.filepath

    if not os.path.exists(filepath):
        print(json.dumps({"error": f"File not found: {filepath}"}))
        return

    try:
        analysis, elapsed = _send_to_vision(filepath)
    except URLError as e:
        print(json.dumps({"error": f"Ollama connection failed: {e}"}))
        return
    except Exception as e:
        print(json.dumps({"error": f"Vision API error: {e}"}))
        return

    if analysis is None:
        print(json.dumps({"error": elapsed}))  # elapsed holds error message
        return

    # Store in database
    conn = get_db()
    tags_str = ", ".join(analysis.get("tags", [])) if "tags" in analysis else None
    description = analysis.get("scene")
    location_guess = (
        json.dumps(analysis.get("location", {}))
        if "location" in analysis else None
    )

    conn.execute("""
        UPDATE files SET
            ai_tags = ?,
            ai_description = ?,
            ai_location_guess = ?,
            ai_processed_at = datetime('now')
        WHERE filepath = ?
    """, (tags_str, description, location_guess, filepath))
    conn.commit()
    conn.close()

    print(json.dumps({
        "filepath": filepath,
        "analysis": analysis,
        "processing_time_seconds": round(elapsed, 1),
        "model": VISION_MODEL,
        "stored_to_db": True
    }, indent=2))


def cmd_batch_analyze(args):
    """Batch analyze photos through AI vision."""
    _check_ollama()
    conn = get_db()

    conditions = ["ai_processed_at IS NULL", "file_type = 'photo'"]
    params = []

    if args.folder:
        conditions.append("filepath LIKE ?")
        params.append(args.folder.rstrip("/") + "/%")
    elif args.folder_year:
        conditions.append("folder_year = ?")
        params.append(args.folder_year)
    if args.needs_review:
        conditions.append("needs_review = 1")
    if args.no_gps:
        conditions.append("has_gps = 0")

    where = " AND ".join(conditions)
    limit = args.limit or BATCH_SIZE

    rows = conn.execute(f"""
        SELECT filepath, filename, folder_year
        FROM files WHERE {where}
        ORDER BY folder_year ASC, filepath
        LIMIT ?
    """, params + [limit]).fetchall()

    total = conn.execute(
        f"SELECT COUNT(*) FROM files WHERE {where}", params
    ).fetchone()[0]
    conn.close()

    results = {"total_pending": total, "batch_size": len(rows), "results": []}
    successes = 0
    failures = 0

    for i, row in enumerate(rows):
        print(f"[{i+1}/{len(rows)}] {row['filename']}...", file=sys.stderr, flush=True)

        try:
            analysis, elapsed = _send_to_vision(row["filepath"])

            if analysis is None:
                failures += 1
                results["results"].append({
                    "filepath": row["filepath"], "status": "error", "error": elapsed
                })
                continue

            # Store
            conn = get_db()
            tags_str = ", ".join(analysis.get("tags", [])) if "tags" in analysis else None
            description = analysis.get("scene")
            location_guess = (
                json.dumps(analysis.get("location", {}))
                if "location" in analysis else None
            )

            conn.execute("""
                UPDATE files SET
                    ai_tags = ?, ai_description = ?,
                    ai_location_guess = ?, ai_processed_at = datetime('now')
                WHERE filepath = ?
            """, (tags_str, description, location_guess, row["filepath"]))
            conn.commit()
            conn.close()

            successes += 1
            results["results"].append({
                "filepath": row["filepath"],
                "status": "success",
                "tags": analysis.get("tags", []),
                "scene": analysis.get("scene"),
                "time": round(elapsed, 1)
            })

        except Exception as e:
            failures += 1
            results["results"].append({
                "filepath": row["filepath"], "status": "error", "error": str(e)
            })

        if i < len(rows) - 1:
            time.sleep(1)

    results["successes"] = successes
    results["failures"] = failures
    results["remaining"] = total - len(rows)

    print(json.dumps(results, indent=2))


def cmd_tag(args):
    """Write IPTC/XMP tags to a file using exiftool."""
    filepath = args.filepath
    conn = get_db()

    keywords = args.keywords
    description = args.description

    if not keywords and not description:
        row = conn.execute(
            "SELECT ai_tags, ai_description FROM files WHERE filepath = ?",
            (filepath,)
        ).fetchone()
        if row and row["ai_tags"]:
            keywords = row["ai_tags"]
        if row and row["ai_description"]:
            description = row["ai_description"]

    if not keywords and not description:
        print(json.dumps({"error": "No tags. Run analyze first or provide --keywords"}))
        conn.close()
        return

    cmd = ['exiftool', '-overwrite_original']

    if keywords:
        for tag in [t.strip() for t in keywords.split(",")]:
            cmd.extend([f'-IPTC:Keywords+={tag}', f'-XMP:Subject+={tag}'])

    if description:
        cmd.extend([
            f'-IPTC:Caption-Abstract={description}',
            f'-XMP:Description={description}'
        ])

    cmd.append(filepath)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        status = "success" if result.returncode == 0 else "error"
        print(json.dumps({
            "status": status,
            "filepath": filepath,
            "keywords_written": keywords,
            "description_written": description,
            "error": result.stderr if status == "error" else None
        }, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

    conn.close()


def cmd_batch_tag(args):
    """Write AI tags to all analyzed files."""
    conn = get_db()

    conditions = ["ai_tags IS NOT NULL", "ai_processed_at IS NOT NULL"]
    params = []

    if args.folder:
        conditions.append("filepath LIKE ?")
        params.append(args.folder.rstrip("/") + "/%")
    elif args.folder_year:
        conditions.append("folder_year = ?")
        params.append(args.folder_year)

    where = " AND ".join(conditions)
    limit = args.limit or 50

    rows = conn.execute(f"""
        SELECT filepath, ai_tags, ai_description
        FROM files WHERE {where}
        LIMIT ?
    """, params + [limit]).fetchall()

    successes = 0
    failures = 0

    for row in rows:
        cmd = ['exiftool', '-overwrite_original']

        if row["ai_tags"]:
            for tag in [t.strip() for t in row["ai_tags"].split(",")]:
                cmd.extend([f'-IPTC:Keywords+={tag}', f'-XMP:Subject+={tag}'])

        if row["ai_description"]:
            cmd.extend([
                f'-IPTC:Caption-Abstract={row["ai_description"]}',
                f'-XMP:Description={row["ai_description"]}'
            ])

        cmd.append(row["filepath"])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                successes += 1
            else:
                failures += 1
        except Exception:
            failures += 1

    print(json.dumps({
        "status": "batch_tag_complete",
        "successes": successes,
        "failures": failures,
        "total_processed": len(rows)
    }, indent=2))
    conn.close()


def cmd_propagate_gps(args):
    """Propagate GPS data from neighboring photos within same time window."""
    conn = get_db()

    folder_filter = ""
    params = []
    if args.folder_year:
        folder_filter = "AND folder_year = ?"
        params.append(args.folder_year)

    no_gps = conn.execute(f"""
        SELECT id, filepath, exif_date, folder_year, folder_month
        FROM files
        WHERE has_gps = 0 AND has_exif_date = 1 AND file_type = 'photo'
        {folder_filter}
        ORDER BY exif_date
    """, params).fetchall()

    with_gps = conn.execute(f"""
        SELECT filepath, exif_date, gps_latitude, gps_longitude, folder_year
        FROM files
        WHERE has_gps = 1 AND has_exif_date = 1
        {folder_filter}
        ORDER BY exif_date
    """, params).fetchall()

    if not with_gps:
        print(json.dumps({"error": "No GPS reference points available"}))
        conn.close()
        return

    window_hours = args.window or GPS_WINDOW_HOURS
    propagated = 0
    candidates = 0

    for row in no_gps:
        if not row["exif_date"]:
            continue

        try:
            from datetime import datetime as dt
            file_date = row["exif_date"][:19].replace(":", "-", 2)
            best_match = None
            best_diff = float('inf')

            for ref in with_gps:
                if not ref["exif_date"]:
                    continue
                ref_date = ref["exif_date"][:19].replace(":", "-", 2)
                try:
                    t1 = dt.fromisoformat(file_date)
                    t2 = dt.fromisoformat(ref_date)
                    diff_hours = abs((t1 - t2).total_seconds()) / 3600
                    if diff_hours < window_hours and diff_hours < best_diff:
                        best_diff = diff_hours
                        best_match = ref
                except (ValueError, TypeError):
                    continue

            if best_match:
                candidates += 1
                if not args.dry_run:
                    conn.execute("""
                        UPDATE files SET
                            gps_latitude = ?, gps_longitude = ?, has_gps = 1
                        WHERE id = ?
                    """, (best_match["gps_latitude"], best_match["gps_longitude"], row["id"]))
                    propagated += 1
        except Exception:
            continue

    if not args.dry_run:
        conn.commit()

    print(json.dumps({
        "photos_without_gps": len(no_gps),
        "gps_references": len(with_gps),
        "candidates_within_window": candidates,
        "propagated": propagated,
        "window_hours": window_hours,
        "dry_run": args.dry_run
    }, indent=2))
    conn.close()


def cmd_review_mismatches(args):
    """Review and optionally fix date mismatches."""
    conn = get_db()
    limit = args.limit or 20

    rows = conn.execute("""
        SELECT filepath, filename, folder_year, exif_year, exif_month,
               camera_make, camera_model, mismatch_years, has_gps,
               gps_latitude, gps_longitude
        FROM files
        WHERE date_mismatch = 1
        ORDER BY mismatch_years DESC
        LIMIT ?
    """, (limit,)).fetchall()

    results = []
    for r in rows:
        entry = {
            "filepath": r["filepath"],
            "filename": r["filename"],
            "folder_year": r["folder_year"],
            "exif_year": r["exif_year"],
            "exif_month": r["exif_month"],
            "camera": f"{r['camera_make'] or ''} {r['camera_model'] or ''}".strip(),
            "mismatch_years": r["mismatch_years"],
            "has_gps": bool(r["has_gps"]),
            "suggestion": "move_to_exif_year" if r["mismatch_years"] > 2 else "verify"
        }
        if r["gps_latitude"]:
            entry["gps"] = f"{r['gps_latitude']:.4f}, {r['gps_longitude']:.4f}"
        results.append(entry)

    print(json.dumps({
        "mismatches": results,
        "note": "Files with large mismatches are likely misplaced. EXIF date is usually correct."
    }, indent=2))
    conn.close()


# ── Main ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Photo Tools - IronClaw Integration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # stats
    subparsers.add_parser("stats", help="Collection statistics")

    # mismatches
    p = subparsers.add_parser("mismatches", help="Date mismatch report")
    p.add_argument("--limit", type=int, default=20)

    # query
    p = subparsers.add_parser("query", help="Search photos")
    p.add_argument("--year", type=int)
    p.add_argument("--exif-year", type=int)
    p.add_argument("--no-gps", action="store_true")
    p.add_argument("--has-gps", action="store_true")
    p.add_argument("--no-date", action="store_true")
    p.add_argument("--camera", type=str)
    p.add_argument("--extension", type=str)
    p.add_argument("--mismatch", action="store_true")
    p.add_argument("--needs-review", action="store_true")
    p.add_argument("--not-analyzed", action="store_true")
    p.add_argument("--analyzed", action="store_true")
    p.add_argument("--tag", type=str)
    p.add_argument("--file-type", choices=["photo", "video"])
    p.add_argument("--limit", type=int, default=20)

    # analyze
    p = subparsers.add_parser("analyze", help="AI vision analysis")
    p.add_argument("filepath")

    # batch-analyze
    p = subparsers.add_parser("batch-analyze", help="Batch AI analysis")
    p.add_argument("--folder-year", type=int)
    p.add_argument("--folder", type=str, help="Filter by folder path prefix")
    p.add_argument("--needs-review", action="store_true")
    p.add_argument("--no-gps", action="store_true")
    p.add_argument("--limit", type=int, default=BATCH_SIZE)

    # tag
    p = subparsers.add_parser("tag", help="Write IPTC/XMP tags")
    p.add_argument("filepath")
    p.add_argument("--keywords", type=str)
    p.add_argument("--description", type=str)

    # batch-tag
    p = subparsers.add_parser("batch-tag", help="Write AI tags to files")
    p.add_argument("--folder-year", type=int)
    p.add_argument("--folder", type=str, help="Filter by folder path prefix")
    p.add_argument("--limit", type=int, default=50)

    # propagate-gps
    p = subparsers.add_parser("propagate-gps", help="Fill GPS gaps")
    p.add_argument("--folder-year", type=int)
    p.add_argument("--window", type=int, default=GPS_WINDOW_HOURS)
    p.add_argument("--dry-run", action="store_true")

    # review-mismatches
    p = subparsers.add_parser("review-mismatches", help="Review date mismatches")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--fix", action="store_true")

    args = parser.parse_args()

    commands = {
        "stats": cmd_stats,
        "mismatches": cmd_mismatches,
        "query": cmd_query,
        "analyze": cmd_analyze,
        "batch-analyze": cmd_batch_analyze,
        "tag": cmd_tag,
        "batch-tag": cmd_batch_tag,
        "propagate-gps": cmd_propagate_gps,
        "review-mismatches": cmd_review_mismatches,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
