"""Skill Forge — validator.

Validates a skill folder or staged skill tree. Returns structured results;
does not print directly (except via report.print_and_status).

Public API:
  validate_skill_folder_at(skill_dir, config, check_already_promoted=False) -> Report
      Validate a single skill folder at any path. Used by both staging
      validation (per-skill) and post-merge validation (against a temp dir).

  validate_staging(staging_dir) -> Report
      Validate all skills in a staging directory's skills/ subfolder.
      Adds cross-skill checks (slug uniqueness across skills).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from utils import find_claude_skills_dir, load_config

_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FRONTMATTER_KV_RE = re.compile(r"^([a-zA-Z_][\w-]*)\s*:\s*(.+?)\s*$", re.MULTILINE)
_RELATED_LINE_RE = re.compile(r"^\s*-\s*`?([a-z0-9][a-z0-9-]*)(?:\.md)?`?", re.MULTILINE)
_RELATED_INLINE_RE = re.compile(r"^Related:\s*(.+?)$", re.MULTILINE | re.IGNORECASE)


@dataclass
class Issue:
    level: str   # PASS | WARN | FAIL
    target: str  # path or skill name
    message: str


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def add(self, level: str, target: str, message: str) -> None:
        self.issues.append(Issue(level, target, message))

    @property
    def failures(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "FAIL"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "WARN"]

    def has_failures(self) -> bool:
        return any(i.level == "FAIL" for i in self.issues)

    def extend(self, other: Report) -> None:
        self.issues.extend(other.issues)

    def print_summary(self) -> None:
        for issue in self.issues:
            if issue.level == "PASS":
                continue
            print(f"  [{issue.level}] {issue.target}: {issue.message}")
        n_fail = len(self.failures)
        n_warn = len(self.warnings)
        n_pass = sum(1 for i in self.issues if i.level == "PASS")
        print(f"Validation: {n_pass} PASS, {n_warn} WARN, {n_fail} FAIL")

    def print_and_status(self) -> int:
        self.print_summary()
        return 1 if self.has_failures() else 0


# ---------- public API ----------

def validate_skill_folder_at(
    skill_dir: Path,
    config: dict | None = None,
    check_already_promoted: bool = False,
    all_ref_slugs: dict[str, str] | None = None,
) -> Report:
    """Validate a single skill folder. Returns a structured Report.

    - check_already_promoted: when True, emit a WARN if the same skill name
      already exists in ~/.claude/skills/. Used during staging validation.
      For post-merge temp-dir validation, set False.
    - all_ref_slugs: optional shared dict for cross-skill slug uniqueness
      checks (used by validate_staging). When None, only intra-skill
      slug uniqueness is checked.
    """
    if config is None:
        config = load_config()
    report = Report()
    if all_ref_slugs is None:
        all_ref_slugs = {}

    promoted_root: Path | None = None
    if check_already_promoted:
        promoted_root = find_claude_skills_dir(config)

    _validate_skill_folder(
        skill_dir=skill_dir,
        report=report,
        config=config,
        promoted_root=promoted_root,
        all_ref_slugs=all_ref_slugs,
    )
    return report


def validate_staging(staging_dir: Path) -> Report:
    """Run all validation checks against a staging directory."""
    report = Report()
    config = load_config()

    skills_dir = staging_dir / "skills"
    if not skills_dir.exists():
        report.add("FAIL", str(staging_dir), "missing skills/ directory (run materialize first)")
        return report

    skill_dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir())

    if not skill_dirs:
        report.add("FAIL", str(skills_dir), "contains no skill folders")
        return report

    all_ref_slugs: dict[str, str] = {}
    promoted_root = find_claude_skills_dir(config)

    for skill_dir in skill_dirs:
        _validate_skill_folder(
            skill_dir=skill_dir,
            report=report,
            config=config,
            promoted_root=promoted_root,
            all_ref_slugs=all_ref_slugs,
        )

    return report


# ---------- internal ----------

def _validate_skill_folder(
    skill_dir: Path,
    report: Report,
    config: dict,
    promoted_root: Path | None,
    all_ref_slugs: dict[str, str],
) -> None:
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    refs_dir = skill_dir / "references"

    if not skill_md.exists():
        report.add("FAIL", name, "missing SKILL.md")
        return

    text = skill_md.read_text(encoding="utf-8")
    fm_match = _FRONTMATTER_RE.match(text)
    if not fm_match:
        report.add("FAIL", name, "SKILL.md missing YAML frontmatter")
        return

    fm: dict[str, str] = {}
    for m in _FRONTMATTER_KV_RE.finditer(fm_match.group(1)):
        fm[m.group(1)] = m.group(2)

    if "name" not in fm:
        report.add("FAIL", name, "frontmatter missing name:")
    elif fm["name"] != name:
        report.add("FAIL", name, f"frontmatter name '{fm['name']}' does not match folder name")
    else:
        report.add("PASS", name, "name matches folder")

    if "description" not in fm:
        report.add("FAIL", name, "frontmatter missing description:")
    else:
        desc = fm["description"]
        min_len = config.get("description_min_chars", 60)
        max_len = config.get("description_max_chars", 600)
        if len(desc) < min_len:
            report.add("FAIL", name, f"description too short ({len(desc)} < {min_len} chars)")
        elif len(desc) > max_len:
            report.add("FAIL", name, f"description too long ({len(desc)} > {max_len} chars)")
        else:
            report.add("PASS", name, f"description length {len(desc)} chars")

        prefix = config.get("description_prefix", "This skill should be used when")
        if not desc.startswith(prefix):
            report.add("FAIL", name, f"description must start with '{prefix}'")

    # Check for existing promoted skill (only in staging context)
    if promoted_root is not None and (promoted_root / name).exists():
        report.add(
            "WARN",
            name,
            f"already promoted at {promoted_root / name} (promote will skip without --force)",
        )

    # References dir
    if not refs_dir.exists():
        report.add("FAIL", name, "missing references/ directory")
        return
    ref_files = sorted(p for p in refs_dir.glob("*.md"))
    if not ref_files:
        report.add("FAIL", name, "references/ contains no .md files")
        return

    min_refs = config.get("min_references_per_skill", 3)
    max_refs = config.get("max_references_per_skill", 15)
    if len(ref_files) < min_refs:
        report.add("WARN", name, f"only {len(ref_files)} references (min recommended: {min_refs})")
    elif len(ref_files) > max_refs:
        report.add("WARN", name, f"{len(ref_files)} references (max recommended: {max_refs})")

    # Local slug set for cross-reference integrity
    local_slugs = {p.stem for p in ref_files}

    for ref_file in ref_files:
        _validate_reference_file(
            ref_file=ref_file,
            skill_name=name,
            report=report,
            config=config,
            all_ref_slugs=all_ref_slugs,
            local_slugs=local_slugs,
        )


def _validate_reference_file(
    ref_file: Path,
    skill_name: str,
    report: Report,
    config: dict,
    all_ref_slugs: dict[str, str],
    local_slugs: set[str],
) -> None:
    slug = ref_file.stem
    target = f"{skill_name}/{slug}"

    # Cross-skill duplicate check (only when all_ref_slugs is shared across skills)
    if slug in all_ref_slugs and all_ref_slugs[slug] != skill_name:
        report.add(
            "FAIL",
            target,
            f"slug '{slug}' also used in skill '{all_ref_slugs[slug]}' (must be unique)",
        )
    else:
        all_ref_slugs[slug] = skill_name

    text = ref_file.read_text(encoding="utf-8")
    body = text.strip()

    min_chars = config.get("reference_body_min_chars", 80)
    if len(body) < min_chars:
        report.add("FAIL", target, f"body too short ({len(body)} < {min_chars} chars)")

    # Required sections
    required = ["**Source:**", "**Timestamp:**", "## Technique", "## When to apply"]
    for req in required:
        if req not in text:
            report.add("FAIL", target, f"missing required section: {req}")

    # Timestamp format
    ts_match = re.search(r"\*\*Timestamp:\*\*\s+(\S+)", text)
    if ts_match and not _TIMESTAMP_RE.match(ts_match.group(1)):
        report.add("FAIL", target, f"timestamp '{ts_match.group(1)}' must be HH:MM:SS")

    # Source field present and non-trivial
    src_match = re.search(r"\*\*Source:\*\*\s+(.+)", text)
    if src_match and len(src_match.group(1).strip()) < 5:
        report.add("FAIL", target, "source citation too short")

    # Cross-reference integrity: Related: slugs must resolve.
    # Intra-skill (same folder) is the strong case. Cross-skill links are valid
    # but we can't always verify them here (the other skill might live in
    # ~/.claude/skills/ rather than the same staging tree), so downgrade to WARN.
    related_slugs = _extract_related_slugs(text)
    for related in related_slugs:
        if related == slug:
            continue
        if related in local_slugs:
            continue
        # Try cross-skill: search siblings under the parent skills dir
        cross_skill_match = _find_cross_skill_ref(ref_file, related)
        if cross_skill_match is None:
            report.add(
                "WARN",
                target,
                f"Related: '{related}' does not resolve locally or in sibling skills",
            )

    if not report.failures or report.failures[-1].target != target:
        report.add("PASS", target, "structure ok")


def _find_cross_skill_ref(ref_file: Path, target_slug: str) -> Path | None:
    """Search sibling skill folders under the same parent for `target_slug.md`.

    Also checks the live ~/.claude/skills/ tree as a fallback so cross-skill
    links to already-promoted skills validate cleanly.
    """
    # ref_file lives at <some-root>/<skill>/references/<slug>.md
    # Walk up to <some-root> and search */references/<target_slug>.md
    skill_folder = ref_file.parent.parent
    skills_root = skill_folder.parent
    candidate = skills_root.rglob(f"references/{target_slug}.md")
    for c in candidate:
        if c != ref_file:
            return c

    # Also check the live skills directory
    try:
        config = load_config()
        live_root = find_claude_skills_dir(config)
        if live_root.exists():
            for c in live_root.rglob(f"references/{target_slug}.md"):
                return c
    except Exception:
        pass

    return None


def _extract_related_slugs(text: str) -> set[str]:
    """Extract slugs referenced from a Related section.

    Handles two layouts:
      ## Related
      - `slug-a.md`
      - `slug-b.md`

    And inline:
      Related: slug-a, slug-b
    """
    slugs: set[str] = set()

    # Bullet form under ## Related heading
    if "## Related" in text:
        after = text.split("## Related", 1)[1]
        # Stop at next H2 heading
        next_h = after.find("\n## ")
        if next_h != -1:
            after = after[:next_h]
        for m in _RELATED_LINE_RE.finditer(after):
            slugs.add(m.group(1))

    # Inline "Related: a, b" form
    for m in _RELATED_INLINE_RE.finditer(text):
        for part in m.group(1).split(","):
            slug = part.strip().lstrip("`").rstrip("`").removesuffix(".md").strip()
            if slug:
                slugs.add(slug)

    return slugs
