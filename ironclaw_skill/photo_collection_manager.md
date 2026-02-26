---
name: photo_collection_manager
description: AI-powered photo collection manager — scan, analyze, tag, and query your photo library
---

# Photo Collection Manager

You have access to a photo collection management toolkit at `~/photo-organizer/`.
The collection contains ~128,000 photos and videos spanning from the 1960s to 2024.

## Available Commands

All commands use wrapper scripts that handle virtual environment activation automatically.

### Collection Overview
```
~/photo-organizer/run_tools.sh stats
```
Shows total files, metadata coverage, AI analysis progress.

### Find Date Mismatches
```
~/photo-organizer/run_tools.sh mismatches --limit 30
```
Files where EXIF date doesn't match folder year. EXIF is usually correct - folder is wrong.

### Search Photos
```
~/photo-organizer/run_tools.sh query [options]
```
Options:
- `--year 2024` — filter by folder year
- `--exif-year 2023` — filter by actual EXIF year
- `--no-gps` — photos missing GPS
- `--has-gps` — photos with GPS
- `--no-date` — photos missing EXIF date
- `--camera iPhone` — filter by camera model
- `--extension heic` — filter by file type
- `--mismatch` — only date mismatches
- `--needs-review` — flagged for review
- `--not-analyzed` — not yet processed by AI
- `--analyzed` — already AI processed
- `--tag beach` — search AI-generated tags
- `--file-type photo` or `--file-type video`
- `--limit 50` — number of results

### AI Vision Analysis (Single Photo)
```
~/photo-organizer/run_tools.sh analyze "/path/to/photo.jpg"
```
Sends the photo to qwen3-vl:32b for scene recognition, object detection, location guessing, era estimation, and keyword tagging. Results are stored in the database.

### AI Vision Batch Analysis
```
~/photo-organizer/run_tools.sh batch-analyze --folder-year 1968 --limit 10
~/photo-organizer/run_tools.sh batch-analyze --folder "/path/to/photos/2024/2024 09" --limit 20
```
Options:
- `--folder-year 1968` — focus on a specific year
- `--folder "/path/..."` — focus on a specific folder
- `--needs-review` — prioritize flagged files
- `--no-gps` — focus on photos missing location
- `--limit 10` — batch size

Each photo takes ~15-60 seconds on the RTX 3090.

### Write Tags to Files
```
~/photo-organizer/run_tools.sh tag "/path/to/photo.jpg"
~/photo-organizer/run_tools.sh tag "/path/to/photo.jpg" --keywords "beach,sunset,family"
```
Writes IPTC:Keywords and XMP:Subject tags. Without --keywords, uses AI-generated tags from the database.

### Batch Write Tags
```
~/photo-organizer/run_tools.sh batch-tag --folder-year 2024 --limit 50
~/photo-organizer/run_tools.sh batch-tag --folder "/path/to/photos/2024/2024 09"
```

### GPS Propagation
```
~/photo-organizer/run_tools.sh propagate-gps --folder-year 2024 --window 4 --dry-run
~/photo-organizer/run_tools.sh propagate-gps --folder-year 2024 --window 4
```
Fills GPS gaps by copying coordinates from nearby photos. Use `--dry-run` first.

### Full Pipeline
```
~/photo-organizer/run_pipeline.sh --folder "/path/to/photos/2024/2024 09"
~/photo-organizer/run_pipeline.sh --year 1968 --batch-size 20
~/photo-organizer/run_pipeline.sh --year 2024 --dry-run
```
Runs scan → AI analyze → write tags in one command.

### EXIF Scan
```
~/photo-organizer/run_audit.sh --resume
~/photo-organizer/run_audit.sh --folder "/path/to/photos/2024/2024 09"
~/photo-organizer/run_audit.sh --report-only
```

### Review Misplaced Files
```
~/photo-organizer/run_tools.sh review-mismatches --limit 20
```

## Workflow Guidelines

1. **Always check stats first** to understand current state
2. **Start AI analysis with small batches** (--limit 5) to verify quality
3. **Use dry-run for GPS propagation** before committing
4. **Write tags only after reviewing AI results**
5. For old scanned photos (1960s-1980s), AI vision is the primary way to get tags
6. The database is at `~/photo_audit.db` — query it directly with sqlite3 if needed

## Architecture

- EXIF scanning: `~/photo-organizer/run_audit.sh`
- AI + queries: `~/photo-organizer/run_tools.sh`
- Full pipeline: `~/photo-organizer/run_pipeline.sh`
- Vision model: qwen3-vl:32b via Ollama (configured in .env)
- Config: `~/photo-organizer/.env`
- Tags written: IPTC:Keywords + XMP:Subject (compatible with QNAP QuMagie)
