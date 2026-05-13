"""Skill Forge — validator.

Validates a staged skill tree before promotion. Returns structured results;
does not print directly (except via report.print_summary).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from utils import find_claude_skills_dir, load_config

_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FRONTMATTER_KV_RE = re.compile(r"^([a-zA-Z_][\w-]*)\s*:\s*(.+?)\s*$", re.MULTILINE)


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


def validate_staging(staging_dir: Path) -> Report:
    """Run all validation checks against a staging directory."""
    report = Report()
    config = load_config()

    skills_dir = staging_dir / "skills"
    if not skills_dir.exists():
        report.add("FAIL", str(staging_dir), "missing skills/ directory (run materialize first)")
        return report

    promoted_root = find_claude_skills_dir(config)
    skill_dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir())

    if not skill_dirs:
        report.add("FAIL", str(skills_dir), "contains no skill folders")
        return report

    all_ref_slugs: dict[str, str] = {}  # slug -> first-seen skill name

    for skill_dir in skill_dirs:
        _validate_skill_folder(skill_dir, report, config, promoted_root, all_ref_slugs)

    return report


def _validate_skill_folder(
    skill_dir: Path,
    report: Report,
    config: dict,
    promoted_root: Path,
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

    # Check for existing promoted skill
    if (promoted_root / name).exists():
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

    for ref_file in ref_files:
        _validate_reference_file(ref_file, name, report, config, all_ref_slugs)


def _validate_reference_file(
    ref_file: Path,
    skill_name: str,
    report: Report,
    config: dict,
    all_ref_slugs: dict[str, str],
) -> None:
    slug = ref_file.stem
    target = f"{skill_name}/{slug}"

    # Cross-skill duplicate check
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

    # Required headings (case-insensitive search at line start)
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

    if not report.failures or report.failures[-1].target != target:
        report.add("PASS", target, "structure ok")
