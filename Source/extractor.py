"""Skill Forge — extractor.

Prepares an extraction package for Claude. Validates the input transcript,
creates the staging directory, copies the transcript and prompt into it,
and writes an EXTRACT_REQUEST.md so the calling /forge skill knows what
to do next.

This module does NOT call an LLM. The actual extraction is driven by
Claude Code reading the package and writing proposed_skills.json +
PROPOSED_SKILLS.md back into the staging directory.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from utils import (
    OUTPUT_DIR,
    PROMPTS_DIR,
    Transcript,
    channel_slug_from_transcript,
    find_youtube_transcription_root,
    load_config,
    load_transcript,
    staging_dir_for,
    video_slug_from_transcript,
)

PROMPT_FILE = PROMPTS_DIR / "extract_skills.md"


class PreExtractError(Exception):
    """Pre-extraction validation failed."""


def validate_package(transcript: Transcript, config: dict, staging_dir: Path, force: bool) -> None:
    """Pre-extraction sanity checks. Raises PreExtractError on failure."""
    issues: list[str] = []

    if transcript.path is None or not transcript.path.exists():
        issues.append(f"transcript path not readable: {transcript.path}")
    min_segs = config.get("transcript_min_segments", 50)
    if len(transcript.segments) < min_segs:
        issues.append(
            f"transcript has {len(transcript.segments)} segments, minimum {min_segs}"
        )
    min_chars = config.get("transcript_min_chars", 2000)
    if transcript.body_chars < min_chars:
        issues.append(f"transcript body is {transcript.body_chars} chars, minimum {min_chars}")

    if not PROMPT_FILE.exists():
        issues.append(f"prompt template missing: {PROMPT_FILE}")

    if staging_dir.exists() and not force:
        issues.append(f"staging dir already exists (use --force to overwrite): {staging_dir}")

    if issues:
        raise PreExtractError("Pre-extraction validation failed:\n  - " + "\n  - ".join(issues))


def build_extraction_package(args: argparse.Namespace) -> int:
    config = load_config()

    if args.channel and args.transcript:
        print("ERROR: pass either a transcript path OR --channel, not both")
        return 2
    if not args.channel and not args.transcript:
        print("ERROR: pass a transcript path or --channel")
        return 2

    transcripts: list[Transcript] = []
    if args.transcript:
        transcripts.append(load_transcript(Path(args.transcript)))
    else:
        yt_root = find_youtube_transcription_root(config)
        if yt_root is None:
            print("ERROR: YouTube Transcription project not resolved (see forge doctor)")
            return 1
        channel_dir = yt_root / "Transcripts" / args.channel
        if not channel_dir.exists():
            print(f"ERROR: channel folder not found: {channel_dir}")
            return 1
        md_files = sorted(channel_dir.glob("*.md"))
        if not md_files:
            print(f"ERROR: no transcripts in {channel_dir}")
            return 1
        for f in md_files:
            try:
                transcripts.append(load_transcript(f))
            except Exception as e:  # noqa: BLE001
                print(f"WARN: skipping {f.name}: {e}")

    if not transcripts:
        print("No usable transcripts found.")
        return 1

    n_built = n_failed = 0
    for tr in transcripts:
        staging = staging_dir_for(tr)
        try:
            validate_package(tr, config, staging, force=args.force)
        except PreExtractError as e:
            print(f"\nSKIP {tr.title}\n  {e}")
            n_failed += 1
            continue

        _materialize_package(tr, staging)
        n_built += 1

    print()
    print(f"Built {n_built} extraction package(s); {n_failed} skipped.")
    if n_built > 0:
        print()
        print("Next: Claude (via the /forge skill) reads each package and writes")
        print("  proposed_skills.json + PROPOSED_SKILLS.md back into the staging dir.")
        print("Then run: forge materialize <staging-dir>  ->  forge validate <staging-dir>")
    return 0 if n_failed == 0 else 1


def _materialize_package(transcript: Transcript, staging_dir: Path) -> None:
    """Write the EXTRACT_REQUEST.md + copy prompt + reference transcript."""
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    # Copy prompt template
    shutil.copy2(PROMPT_FILE, staging_dir / "extract_skills.md")

    # Write request file
    transcript_rel = ""
    if transcript.path is not None:
        try:
            transcript_rel = str(transcript.path)
        except Exception:  # noqa: BLE001
            pass

    lines = [
        "# EXTRACT REQUEST",
        "",
        "## Inputs",
        "",
        f"- Transcript: `{transcript_rel}`",
        f"- Channel: {transcript.channel}",
        f"- Title: {transcript.title}",
        f"- Video ID: {transcript.video_id}",
        f"- URL: {transcript.url}",
        f"- Duration: {transcript.duration}",
        f"- Segments: {len(transcript.segments)}",
        f"- Body chars: {transcript.body_chars}",
        "",
        "## Task",
        "",
        "Read the transcript at the path above, then read `extract_skills.md` in this",
        "same directory for the extraction rules and few-shot example.",
        "",
        "Produce TWO files in this directory:",
        "",
        "1. `proposed_skills.json` — parser source of truth (must match the schema in the prompt)",
        "2. `PROPOSED_SKILLS.md` — human-readable review surface, with the same JSON",
        "   embedded as the final fenced ```json block",
        "",
        "Do NOT create the `skills/` tree manually. The next step (`forge materialize`)",
        "will generate it from your proposal.",
        "",
        "## Source metadata to copy into proposed_skills.json `source` field",
        "",
        "```json",
        "{",
        f'  "transcript_path": "{transcript_rel.replace(chr(92), chr(92)+chr(92))}",',
        f'  "video_id": "{transcript.video_id}",',
        f'  "title": "{transcript.title}",',
        f'  "channel": "{transcript.channel}",',
        f'  "url": "{transcript.url}"',
        "}",
        "```",
        "",
    ]
    (staging_dir / "EXTRACT_REQUEST.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"Built package: {staging_dir.relative_to(staging_dir.parent.parent.parent)}")
