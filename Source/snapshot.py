"""Skill Forge — snapshot.

I/O for loading and writing skill folders. The ONLY module that reads or
writes skill files on disk; merger.py is pure logic on these snapshots.

Splits the I/O from the merge logic so merger.py is trivially unit-testable.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FRONTMATTER_KV_RE = re.compile(r"^([a-zA-Z_][\w-]*)\s*:\s*(.+?)\s*$", re.MULTILINE)


def _normalise_lf(b: bytes) -> bytes:
    """Normalise CRLF -> LF so Dropbox flips don't make identical content look different."""
    return b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


@dataclass
class ReferenceFile:
    """A single reference file inside a skill's references/ folder."""
    slug: str
    content_bytes: bytes               # raw bytes from disk
    body_text: str                     # decoded text for validation/preview

    @property
    def normalised_bytes(self) -> bytes:
        """CRLF-normalised bytes for byte-level comparison."""
        return _normalise_lf(self.content_bytes)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.normalised_bytes).hexdigest()

    def preview(self, max_chars: int = 200) -> str:
        """First non-empty paragraph for chat display."""
        for chunk in self.body_text.split("\n\n"):
            chunk = chunk.strip()
            if chunk and not chunk.startswith("#") and not chunk.startswith("**"):
                if len(chunk) > max_chars:
                    return chunk[: max_chars - 1] + "..."
                return chunk
        return self.body_text[:max_chars]


@dataclass
class SkillSnapshot:
    """In-memory representation of one skill folder."""
    name: str
    description: str
    version: int
    references: dict[str, ReferenceFile] = field(default_factory=dict)
    # Capture the raw frontmatter so writers can preserve unknown keys
    extra_frontmatter: dict[str, str] = field(default_factory=dict)


def load_skill(path: Path) -> SkillSnapshot:
    """Load a skill folder into a SkillSnapshot."""
    if not path.exists():
        raise FileNotFoundError(f"Skill folder not found: {path}")
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found in {path}")

    text = skill_md.read_text(encoding="utf-8")
    fm_match = _FRONTMATTER_RE.match(text)
    if not fm_match:
        raise ValueError(f"{skill_md}: missing YAML frontmatter")

    fm: dict[str, str] = {}
    for m in _FRONTMATTER_KV_RE.finditer(fm_match.group(1)):
        fm[m.group(1).lower()] = m.group(2).strip()

    name = fm.pop("name", path.name)
    description = fm.pop("description", "")
    version_raw = fm.pop("version", "1")
    version = _parse_version(version_raw)

    references: dict[str, ReferenceFile] = {}
    refs_dir = path / "references"
    if refs_dir.exists():
        for ref_path in sorted(refs_dir.glob("*.md")):
            slug = ref_path.stem
            content_bytes = ref_path.read_bytes()
            body_text = content_bytes.decode("utf-8", errors="replace")
            references[slug] = ReferenceFile(
                slug=slug,
                content_bytes=content_bytes,
                body_text=body_text,
            )

    return SkillSnapshot(
        name=name,
        description=description,
        version=version,
        references=references,
        extra_frontmatter=fm,
    )


def write_skill(snapshot: SkillSnapshot, path: Path) -> None:
    """Write a SkillSnapshot to disk at `path`.

    Overwrites any existing content. Caller is responsible for backups
    and atomic-swap orchestration.
    """
    path.mkdir(parents=True, exist_ok=True)
    refs_dir = path / "references"
    refs_dir.mkdir(exist_ok=True)

    # Remove existing references not in the snapshot (clean rewrite)
    snapshot_slugs = set(snapshot.references)
    for existing_ref in refs_dir.glob("*.md"):
        if existing_ref.stem not in snapshot_slugs:
            existing_ref.unlink()

    # Write references
    for slug, ref in snapshot.references.items():
        (refs_dir / f"{slug}.md").write_bytes(ref.content_bytes)

    # Write SKILL.md
    skill_md_lines = [
        "---",
        f"name: {snapshot.name}",
        f"description: {_oneline(snapshot.description)}",
        f"version: {snapshot.version}",
    ]
    for key, value in snapshot.extra_frontmatter.items():
        skill_md_lines.append(f"{key}: {value}")
    skill_md_lines.extend([
        "---",
        "",
        f"# {snapshot.name}",
        "",
        "## References",
        "",
        "Load these on demand from `references/` as the situation requires:",
        "",
    ])
    for slug, ref in snapshot.references.items():
        # Use first sentence of body or first line of Technique section
        hint = _ref_hint(ref.body_text)
        skill_md_lines.append(f"- `references/{slug}.md` — {hint}")
    skill_md_lines.append("")

    (path / "SKILL.md").write_text("\n".join(skill_md_lines), encoding="utf-8")


# ---------- helpers ----------

def _parse_version(raw: str) -> int:
    """Accept either integer ('1', '2') or legacy semver-ish ('0.1.0', '0.2.0').

    Legacy semver maps minor -> integer (0.1.0 -> 1, 0.2.0 -> 2). Anything
    unparseable -> 1.
    """
    raw = str(raw).strip().strip('"').strip("'")
    # Pure integer
    try:
        return int(raw)
    except ValueError:
        pass
    # Semver-ish: 0.X.Y -> X
    parts = raw.split(".")
    if len(parts) >= 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 1


def _oneline(text: str) -> str:
    return " ".join(text.split())


def _ref_hint(body_text: str, max_chars: int = 120) -> str:
    """First sentence of the Technique section, for the SKILL.md bullet list."""
    if "## Technique" in body_text:
        after = body_text.split("## Technique", 1)[1]
        # Cut at next heading
        next_h = after.find("\n## ")
        if next_h != -1:
            after = after[:next_h]
        # First sentence
        for line in after.splitlines():
            line = line.strip()
            if line:
                # First sentence ends at '.', '?', or '!'
                for end in (". ", "? ", "! "):
                    idx = line.find(end)
                    if 0 < idx < max_chars:
                        return line[:idx]
                return line[:max_chars]
    return body_text.strip().splitlines()[0][:max_chars] if body_text.strip() else ""
