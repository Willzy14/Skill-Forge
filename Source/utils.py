"""Shared utilities for Skill Forge.

Path resolution, config loading, transcript parsing, slugify.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "Config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
LOCAL_SETTINGS_PATH = CONFIG_DIR / "local.settings.json"
PROMPTS_DIR = PROJECT_ROOT / "Prompts"
OUTPUT_DIR = PROJECT_ROOT / "Output"
BACKUP_DIR = PROJECT_ROOT / "Backup" / "Promoted Skills"
COMMANDS_DIR = PROJECT_ROOT / "Commands"

DEFAULT_SETTINGS = {
    "schema_version": 1,
    "default_granularity": "medium",
    "min_references_per_skill": 3,
    "max_references_per_skill": 15,
    "skill_name_prefix": "",
    "description_min_chars": 60,
    "description_max_chars": 600,
    "description_prefix": "This skill should be used when",
    "reference_body_min_chars": 80,
    "transcript_min_segments": 1,
    "transcript_min_chars": 2000,
}


def load_config() -> dict[str, Any]:
    """Merge `settings.json` with optional `local.settings.json`. Defaults fill gaps."""
    config: dict[str, Any] = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            config.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {SETTINGS_PATH}: {e}") from e
    if LOCAL_SETTINGS_PATH.exists():
        try:
            config.update(json.loads(LOCAL_SETTINGS_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {LOCAL_SETTINGS_PATH}: {e}") from e
    return config


_SLUG_KEEP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int = 60) -> str:
    """Filesystem-safe slug. Lowercase, hyphenated, ASCII-only."""
    if not text:
        return "untitled"
    normalised = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_KEEP.sub("-", normalised.lower()).strip("-")
    if not slug:
        return "untitled"
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug


@dataclass
class TranscriptSegment:
    timestamp: str
    text: str


@dataclass
class Transcript:
    title: str
    channel: str
    url: str
    duration: str
    source: str
    video_id: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    body_chars: int = 0
    path: Path | None = None


_METADATA_TABLE_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|$", re.MULTILINE)
_SEGMENT_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.+)$", re.MULTILINE)
_FILENAME_VIDEO_ID_RE = re.compile(r"\[([\w-]{8,})\]\.md$")


def load_transcript(path: Path) -> Transcript:
    """Parse a YouTube Transcription markdown file."""
    if not path.exists():
        raise FileNotFoundError(f"Transcript not found: {path}")
    text = path.read_text(encoding="utf-8")

    metadata: dict[str, str] = {}
    for match in _METADATA_TABLE_RE.finditer(text):
        key, value = match.group(1).strip(), match.group(2).strip()
        if key.lower() not in ("field", "-------"):
            metadata[key.lower()] = value

    # Extract title from first H1
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else metadata.get("title", path.stem)

    # Segments
    segments: list[TranscriptSegment] = []
    for m in _SEGMENT_RE.finditer(text):
        segments.append(TranscriptSegment(timestamp=m.group(1), text=m.group(2).strip()))

    body_chars = sum(len(s.text) for s in segments)

    # Video ID: from URL field if available, otherwise from filename
    video_id = ""
    url = metadata.get("url", "")
    url_id_match = re.search(r"v=([\w-]{8,})", url)
    if url_id_match:
        video_id = url_id_match.group(1)
    else:
        fn_match = _FILENAME_VIDEO_ID_RE.search(path.name)
        if fn_match:
            video_id = fn_match.group(1)

    return Transcript(
        title=title,
        channel=metadata.get("channel", "Unknown"),
        url=url,
        duration=metadata.get("duration", ""),
        source=metadata.get("source", ""),
        video_id=video_id,
        segments=segments,
        body_chars=body_chars,
        path=path,
    )


def find_youtube_transcription_root(config: dict[str, Any]) -> Path | None:
    """Resolve YouTube Transcription project path from config or sibling lookup."""
    explicit = config.get("youtube_transcription_project")
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
    # Sibling lookup
    candidate = PROJECT_ROOT.parent / "YouTube Transcription"
    if candidate.exists():
        return candidate
    return None


def find_claude_skills_dir(config: dict[str, Any]) -> Path:
    """Resolve ~/.claude/skills/ location. Uses config override if present, else expanduser."""
    explicit = config.get("claude_skills_dir")
    if explicit:
        return Path(explicit)
    return Path.home() / ".claude" / "skills"


def find_claude_commands_dir(config: dict[str, Any]) -> Path:
    """Resolve ~/.claude/commands/ location."""
    explicit = config.get("claude_commands_dir")
    if explicit:
        return Path(explicit)
    return Path.home() / ".claude" / "commands"


def video_slug_from_transcript(transcript: Transcript) -> str:
    """Slug for staging dir: video_id if available, else slugified title."""
    if transcript.video_id:
        # Include short title prefix so dirs are recognisable
        title_slug = slugify(transcript.title, max_length=40)
        return f"{title_slug}-{transcript.video_id}"
    return slugify(transcript.title)


def channel_slug_from_transcript(transcript: Transcript) -> str:
    return slugify(transcript.channel)


def staging_dir_for(transcript: Transcript) -> Path:
    """Where this transcript's extraction lives in Output/."""
    return OUTPUT_DIR / channel_slug_from_transcript(transcript) / video_slug_from_transcript(transcript)
