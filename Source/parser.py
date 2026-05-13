"""Parse PROPOSED_SKILLS into a structured dict.

Precedence:
  1. proposed_skills.json if present and schema-valid
  2. Fenced ```json block extracted from PROPOSED_SKILLS.md
  3. If both exist but differ, prefer JSON file and emit a warning

Schema validation is hand-rolled (no jsonschema dependency).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

REQUIRED_TOP_KEYS = {"schema_version", "source", "skills"}
REQUIRED_SOURCE_KEYS = {"transcript_path", "video_id", "title", "channel", "url"}
REQUIRED_SKILL_KEYS = {"name", "description", "references"}
REQUIRED_REF_KEYS = {"slug", "source_video_id", "timestamp", "technique", "when_to_apply"}
OPTIONAL_REF_KEYS = {"settings", "related"}

_FENCED_JSON_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ParseError(Exception):
    """Raised when proposal cannot be parsed or schema-validated."""


def parse_proposed_skills(staging_dir: Path) -> dict[str, Any]:
    """Load and validate the proposal from a staging directory."""
    if not staging_dir.exists():
        raise ParseError(f"Staging directory not found: {staging_dir}")

    json_path = staging_dir / "proposed_skills.json"
    md_path = staging_dir / "PROPOSED_SKILLS.md"

    json_data: dict[str, Any] | None = None
    md_data: dict[str, Any] | None = None
    json_error: str = ""
    md_error: str = ""

    # Try JSON file first
    if json_path.exists():
        try:
            json_data = json.loads(json_path.read_text(encoding="utf-8"))
            _validate_schema(json_data, source=str(json_path))
        except (json.JSONDecodeError, ParseError) as e:
            json_error = str(e)
            json_data = None

    # Try MD fenced block
    if md_path.exists():
        try:
            md_data = _extract_json_from_md(md_path)
            if md_data is not None:
                _validate_schema(md_data, source=str(md_path))
        except (json.JSONDecodeError, ParseError) as e:
            md_error = str(e)
            md_data = None

    # Decide which to use
    if json_data is not None:
        if md_data is not None and json.dumps(json_data, sort_keys=True) != json.dumps(md_data, sort_keys=True):
            print(f"WARN: proposed_skills.json and PROPOSED_SKILLS.md differ. Using JSON.")
        return json_data

    if md_data is not None:
        if json_path.exists():
            print(f"WARN: proposed_skills.json invalid ({json_error}). Falling back to PROPOSED_SKILLS.md fenced block.")
        return md_data

    # Both failed
    err_parts = []
    if json_path.exists():
        err_parts.append(f"proposed_skills.json: {json_error or 'unreadable'}")
    else:
        err_parts.append("proposed_skills.json: missing")
    if md_path.exists():
        err_parts.append(f"PROPOSED_SKILLS.md: {md_error or 'no fenced JSON block found'}")
    else:
        err_parts.append("PROPOSED_SKILLS.md: missing")
    raise ParseError("; ".join(err_parts))


def _extract_json_from_md(md_path: Path) -> dict[str, Any] | None:
    text = md_path.read_text(encoding="utf-8")
    matches = _FENCED_JSON_RE.findall(text)
    if not matches:
        return None
    # Use the last fenced block (most likely the canonical one at the bottom)
    return json.loads(matches[-1])


def _validate_schema(data: Any, source: str) -> None:
    """Hand-rolled schema validation. Raises ParseError on issues."""
    if not isinstance(data, dict):
        raise ParseError(f"{source}: top-level must be object, got {type(data).__name__}")

    missing_top = REQUIRED_TOP_KEYS - data.keys()
    if missing_top:
        raise ParseError(f"{source}: missing top-level keys: {sorted(missing_top)}")

    if data["schema_version"] != SCHEMA_VERSION:
        raise ParseError(f"{source}: schema_version must be {SCHEMA_VERSION}, got {data['schema_version']}")

    src = data["source"]
    if not isinstance(src, dict):
        raise ParseError(f"{source}: source must be object")
    missing_src = REQUIRED_SOURCE_KEYS - src.keys()
    if missing_src:
        raise ParseError(f"{source}: source missing keys: {sorted(missing_src)}")

    skills = data["skills"]
    if not isinstance(skills, list) or not skills:
        raise ParseError(f"{source}: skills must be non-empty list")

    seen_skill_names: set[str] = set()
    seen_ref_slugs: set[str] = set()

    for i, skill in enumerate(skills):
        ctx = f"{source}: skills[{i}]"
        if not isinstance(skill, dict):
            raise ParseError(f"{ctx}: must be object")
        missing = REQUIRED_SKILL_KEYS - skill.keys()
        if missing:
            raise ParseError(f"{ctx}: missing keys: {sorted(missing)}")

        name = skill["name"]
        if not isinstance(name, str) or not _SLUG_RE.match(name):
            raise ParseError(f"{ctx}: name must be a slug (lowercase, hyphens), got {name!r}")
        if name in seen_skill_names:
            raise ParseError(f"{ctx}: duplicate skill name {name!r}")
        seen_skill_names.add(name)

        desc = skill["description"]
        if not isinstance(desc, str) or not desc.strip():
            raise ParseError(f"{ctx}: description must be non-empty string")

        refs = skill["references"]
        if not isinstance(refs, list) or not refs:
            raise ParseError(f"{ctx}: references must be non-empty list")

        for j, ref in enumerate(refs):
            rctx = f"{ctx}.references[{j}]"
            if not isinstance(ref, dict):
                raise ParseError(f"{rctx}: must be object")
            missing_ref = REQUIRED_REF_KEYS - ref.keys()
            if missing_ref:
                raise ParseError(f"{rctx}: missing keys: {sorted(missing_ref)}")

            slug = ref["slug"]
            if not isinstance(slug, str) or not _SLUG_RE.match(slug):
                raise ParseError(f"{rctx}: slug must be a slug, got {slug!r}")
            if slug in seen_ref_slugs:
                raise ParseError(f"{rctx}: duplicate reference slug {slug!r} (must be unique across all skills)")
            seen_ref_slugs.add(slug)

            ts = ref["timestamp"]
            if not isinstance(ts, str) or not _TIMESTAMP_RE.match(ts):
                raise ParseError(f"{rctx}: timestamp must be HH:MM:SS, got {ts!r}")

            for key in ("technique", "when_to_apply"):
                v = ref[key]
                if not isinstance(v, str) or not v.strip():
                    raise ParseError(f"{rctx}: {key} must be non-empty string")

            settings = ref.get("settings", [])
            if not isinstance(settings, list):
                raise ParseError(f"{rctx}: settings must be list of strings")
            for s in settings:
                if not isinstance(s, str):
                    raise ParseError(f"{rctx}: settings entries must be strings")

            related = ref.get("related", [])
            if not isinstance(related, list):
                raise ParseError(f"{rctx}: related must be list of strings")
            for r in related:
                if not isinstance(r, str):
                    raise ParseError(f"{rctx}: related entries must be strings")
