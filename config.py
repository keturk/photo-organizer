"""
Shared configuration for Photo Organizer.
Loads settings from .env in the project directory.
"""

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = PROJECT_DIR / ".env"

REQUIRED_KEYS = ["MEDIA_ROOT", "OLLAMA_URL"]


def _load_config():
    """Load key=value pairs from .env. Fail if file is missing."""
    if not CONFIG_FILE.exists():
        print(f"ERROR: {CONFIG_FILE} not found.", file=sys.stderr)
        print("Run 'bash setup.sh' or copy .env.example to .env", file=sys.stderr)
        sys.exit(1)

    config = {}
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip()

    missing = [k for k in REQUIRED_KEYS if not config.get(k)]
    if missing:
        print(f"ERROR: Missing required settings in .env: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    return config


_config = _load_config()

# ── Required settings ─────────────────────────────────────────

MEDIA_ROOT = _config["MEDIA_ROOT"]
OLLAMA_URL = _config["OLLAMA_URL"]

# ── Optional settings (sensible defaults) ─────────────────────

DB_PATH = os.path.expanduser(_config.get("DB_PATH") or "~/photo_audit.db")
VISION_MODEL = _config.get("VISION_MODEL") or "qwen3-vl:32b"
GPS_WINDOW_HOURS = int(_config.get("GPS_WINDOW_HOURS") or "4")
BATCH_SIZE = int(_config.get("BATCH_SIZE") or "10")

_skip = _config.get("SKIP_DIRS") or "$RECYCLE.BIN,System Volume Information,.qsyncclient"
SKIP_DIRS = set(s.strip() for s in _skip.split(","))

# ── Constants ──────────────────────────────────────────────────

PHOTO_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.heic', '.webp',
    '.tiff', '.tif', '.bmp', '.gif'
}

VIDEO_EXTENSIONS = {
    '.mp4', '.mov', '.avi', '.mts', '.3gp',
    '.mkv', '.wmv', '.m4v'
}

ALL_MEDIA = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

VISION_PROMPT = """Analyze this photo and provide the following information in JSON format:
{
    "scene": "Brief description of the scene (1-2 sentences)",
    "objects": ["list", "of", "main", "objects"],
    "people": {"count": 0, "description": "age ranges, activities"},
    "location": {"guess": "best guess of location/country", "confidence": "high/medium/low", "clues": "what clues you used"},
    "era": {"guess": "estimated decade/year", "confidence": "high/medium/low", "clues": "clothing, cars, tech, etc"},
    "mood": "overall mood/atmosphere",
    "tags": ["keyword1", "keyword2", "keyword3", "..."],
    "is_scan_of_print": true/false,
    "is_screenshot": true/false
}

Be specific with tags - include: setting (indoor/outdoor/beach/mountain), weather,
season, activities, objects, colors, events (birthday/wedding/graduation).
For location, look for signs, architecture, landscape, vegetation, license plates.
For era, look at clothing style, hairstyles, cars, technology visible.
Respond ONLY with valid JSON, no other text."""
