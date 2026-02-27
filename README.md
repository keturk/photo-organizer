# Photo Organizer

AI-powered photo collection manager using local LLM inference. Scans, audits, analyzes, and tags your photo/video library using vision AI running on your own hardware.

## Architecture

```
┌─────────────────┐        Ollama API         ┌──────────────────────┐
│   Client PC      │ ──────────────────────►   │  GPU Server          │
│                  │                           │  (NVIDIA GPU)        │
│  IronClaw        │   ◄────────────────────   │                      │
│  photo_tools.py  │        AI results         │  qwen3-vl:32b        │
│  photo_audit.py  │                           │  (vision analysis)   │
│  SQLite DB       │                           │                      │
│  Photo Drive     │                           │  Ollama Docker       │
└─────────────────┘                            └──────────────────────┘
```

- **photo_audit.py** — Batch scanner. Extracts EXIF metadata, detects date mismatches, stores in SQLite. Resumable.
- **photo_tools.py** — CLI toolkit. Queries, AI vision analysis, tagging, GPS propagation.
- **IronClaw skill** — Optional natural language interface to photo_tools.py.

## Requirements

- Python 3.10+
- exiftool (`sudo apt install libimage-exiftool-perl`)
- ImageMagick (`sudo apt install imagemagick`) — for HEIC conversion
- Ollama with qwen3-vl model running on GPU server

## Setup

```bash
cd ~/photo-organizer
bash setup.sh
```

This creates a virtual environment, installs dependencies, and walks you through config.

## Configuration

Edit `.env`:

```env
MEDIA_ROOT=/path/to/your/photos
DB_PATH=~/photo_audit.db
OLLAMA_URL=http://YOUR_OLLAMA_HOST:11434
VISION_MODEL=qwen3-vl:32b
```

## Scripts

All scripts handle virtual environment activation/deactivation automatically.

| Script | Purpose |
|--------|---------|
| `run_pipeline.sh` | End-to-end: scan → AI analyze → write tags |
| `run_audit.sh` | EXIF metadata scan only |
| `run_tools.sh` | Run any photo_tools.py command |

## Usage

### Full Pipeline (recommended)

Process a specific folder or an entire year in one command:

```bash
# Process a specific folder
./run_pipeline.sh --folder "/path/to/photos/2024/2024 09"

# Process all photos from a year
./run_pipeline.sh --year 1968

# Larger AI batches (default: 10)
./run_pipeline.sh --folder "/path/to/photos/2024/2024 09" --batch-size 20

# Preview without writing tags
./run_pipeline.sh --year 2024 --dry-run
```

The pipeline runs three steps:
1. **Scan** — Extract EXIF metadata (folder-only when using `--folder`, full scan with `--year`)
2. **AI Analyze** — Send photos to vision model for scene/tag analysis
3. **Write Tags** — Write IPTC/XMP tags into photo files

### Scan & Audit

```bash
# Full collection scan (resumable — safe to Ctrl+C and restart)
./run_audit.sh

# Resume interrupted scan
./run_audit.sh --resume

# Scan a specific folder only
./run_audit.sh --folder "/path/to/photos/2024/2024 09"

# View report from existing data
./run_audit.sh --report-only
```

### Query & Review

```bash
# Collection stats
./run_tools.sh stats

# Find misplaced files (EXIF date ≠ folder date)
./run_tools.sh mismatches --limit 30

# Search by filters
./run_tools.sh query --year 2024 --no-gps
./run_tools.sh query --camera iPhone --mismatch
./run_tools.sh query --extension heic --needs-review
```

### AI Vision Analysis

```bash
# Analyze a single photo
./run_tools.sh analyze "/path/to/photo.jpg"

# Batch analyze by year or folder
./run_tools.sh batch-analyze --folder-year 1968 --limit 5
./run_tools.sh batch-analyze --folder "/path/to/photos/2024/2024 09" --limit 20

# Analyze photos missing GPS
./run_tools.sh batch-analyze --no-gps --limit 20
```

#### Context Hints

Add optional `.context.txt` files to any photo folder to give the AI background information. Context is inherited from parent directories.

```
photos/
  .context.txt          # "Turkish family photo collection from Ankara"
  1968/
    .context.txt        # "Scanned prints from Baskoy village, rural Turkey"
    1968 01/
      photo.jpg         # gets both context hints
```

### Write Tags

```bash
# Write AI tags to a single file (IPTC + XMP)
./run_tools.sh tag "/path/to/photo.jpg"

# Manual tags
./run_tools.sh tag "/path/to/photo.jpg" --keywords "beach,family,summer"

# Batch write by year or folder
./run_tools.sh batch-tag --folder-year 2024 --limit 50
./run_tools.sh batch-tag --folder "/path/to/photos/2024/2024 09"
```

### GPS Propagation

```bash
# Preview (dry run)
./run_tools.sh propagate-gps --folder-year 2024 --window 4 --dry-run

# Apply
./run_tools.sh propagate-gps --folder-year 2024 --window 4
```

### IronClaw Integration (WIP)

IronClaw integration is a work in progress. The skill file is included but not yet fully tested with IronClaw's skill installation system.

## Database Schema

The SQLite database (`~/photo_audit.db`) stores:

| Column | Description |
|--------|-------------|
| filepath | Full path to file |
| folder_year / folder_month | Extracted from folder structure |
| exif_date / exif_year / exif_month | From EXIF DateTimeOriginal |
| camera_make / camera_model | Camera info |
| gps_latitude / gps_longitude | GPS coordinates |
| has_exif_date / has_gps | Boolean flags |
| date_mismatch / mismatch_years | Folder vs EXIF discrepancy |
| ai_tags / ai_description | AI vision results |
| ai_location_guess | AI location inference |
| needs_review | Flagged for manual review |

Query directly if needed:

```bash
sqlite3 ~/photo_audit.db "SELECT COUNT(*), folder_year FROM files GROUP BY folder_year ORDER BY folder_year;"
```

## Tag Format

Tags are written as:
- **IPTC:Keywords** — widely supported by photo managers
- **XMP:Subject** — modern standard, used by Lightroom/QuMagie
- **IPTC:Caption-Abstract** + **XMP:Description** — scene descriptions

Compatible with: QNAP QuMagie, Qsirch, Apple Photos, Lightroom, digiKam, Synology Photos.

## Notes

- NTFS over USB is slow for metadata scanning. The audit scan is resumable.
- HEIC files require ImageMagick for conversion before AI analysis.
- Vision analysis takes ~15-60 seconds per photo on RTX 3090.
- At 128K files, full AI analysis would take weeks. Prioritize by need.
- GPS propagation works best for phone photos taken in sequence.
- Scanned prints (1960s-1980s) benefit most from AI vision tagging.

## License

MIT
