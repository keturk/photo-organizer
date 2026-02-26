#!/bin/bash
# Full pipeline: scan → AI analyze → write tags for a given folder year or path
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# shellcheck disable=SC1091
source .venv/bin/activate
trap deactivate EXIT

# ── Parse arguments ───────────────────────────────────────────
FOLDER_YEAR=""
FOLDER_PATH=""
BATCH_SIZE=10
DRY_RUN=false

usage() {
    echo "Usage: $0 (--year <YEAR> | --folder <PATH>) [--batch-size N] [--dry-run]"
    echo ""
    echo "  --year         Folder year to process"
    echo "  --folder       Specific folder path to process"
    echo "  --batch-size   Photos per AI batch (default: 10)"
    echo "  --dry-run      Show what would happen without writing tags"
    echo ""
    echo "Provide either --year or --folder (one is required)."
    echo ""
    echo "Examples:"
    echo "  $0 --year 1968 --batch-size 20"
    echo "  $0 --folder \"/path/to/photos/2024/2024 09\""
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --year) FOLDER_YEAR="$2"; shift 2 ;;
        --folder) FOLDER_PATH="$2"; shift 2 ;;
        --batch-size) BATCH_SIZE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) usage ;;
    esac
done

if [ -z "$FOLDER_YEAR" ] && [ -z "$FOLDER_PATH" ]; then
    usage
fi

if [ -n "$FOLDER_YEAR" ] && [ -n "$FOLDER_PATH" ]; then
    echo "Error: provide --year or --folder, not both."
    exit 1
fi

# Build display label and filter args
if [ -n "$FOLDER_PATH" ]; then
    LABEL="folder $FOLDER_PATH"
    FILTER_ARG="--folder"
    FILTER_VAL="$FOLDER_PATH"
    # SQL filter for inline python queries
    SQL_WHERE="filepath LIKE ?"
    SQL_PARAM="${FOLDER_PATH%/}/%"
else
    LABEL="year $FOLDER_YEAR"
    FILTER_ARG="--folder-year"
    FILTER_VAL="$FOLDER_YEAR"
    SQL_WHERE="folder_year = ?"
    SQL_PARAM="$FOLDER_YEAR"
fi

echo ""
echo "  📸 Photo Pipeline — $LABEL"
echo "  ════════════════════════════════════════"
echo ""

# ── Step 1: Scan ──────────────────────────────────────────────
if [ -n "$FOLDER_PATH" ]; then
    echo "  [1/3] Scanning EXIF metadata (folder only)..."
    python3 photo_audit.py --folder "$FOLDER_PATH"
else
    echo "  [1/3] Scanning EXIF metadata..."
    python3 photo_audit.py --resume
fi
echo ""

# ── Step 2: AI Analyze ────────────────────────────────────────
PENDING=$(python3 -c "
from db import get_db
conn = get_db()
n = conn.execute(
    'SELECT COUNT(*) FROM files WHERE $SQL_WHERE AND ai_processed_at IS NULL AND file_type = \"photo\"',
    ('$SQL_PARAM',)
).fetchone()[0]
print(n)
conn.close()
")

echo "  [2/3] AI vision analysis ($PENDING photos pending)..."

if [ "$PENDING" -eq 0 ]; then
    echo "     All photos already analyzed."
else
    PROCESSED=0
    while [ "$PROCESSED" -lt "$PENDING" ]; do
        REMAINING=$((PENDING - PROCESSED))
        CURRENT_BATCH=$((REMAINING < BATCH_SIZE ? REMAINING : BATCH_SIZE))
        echo "     Batch: $CURRENT_BATCH photos (${PROCESSED}/${PENDING} done)..."
        python3 photo_tools.py batch-analyze $FILTER_ARG "$FILTER_VAL" --limit "$CURRENT_BATCH" > /dev/null
        PROCESSED=$((PROCESSED + CURRENT_BATCH))
    done
    echo "     ✅ $PENDING photos analyzed."
fi
echo ""

# ── Step 3: Write tags ────────────────────────────────────────
TAGGABLE=$(python3 -c "
from db import get_db
conn = get_db()
n = conn.execute(
    'SELECT COUNT(*) FROM files WHERE $SQL_WHERE AND ai_tags IS NOT NULL AND ai_processed_at IS NOT NULL',
    ('$SQL_PARAM',)
).fetchone()[0]
print(n)
conn.close()
")

if [ "$DRY_RUN" = true ]; then
    echo "  [3/3] DRY RUN — would write tags to $TAGGABLE photos."
else
    echo "  [3/3] Writing IPTC/XMP tags to $TAGGABLE photos..."
    if [ "$TAGGABLE" -gt 0 ]; then
        python3 photo_tools.py batch-tag $FILTER_ARG "$FILTER_VAL" --limit "$TAGGABLE"
    else
        echo "     No photos with AI tags to write."
    fi
fi

echo ""
echo "  ════════════════════════════════════════"
echo "  ✅ Pipeline complete for $LABEL"
echo ""
