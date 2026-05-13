"""Skill Forge — writer.

Three responsibilities:
  - materialize: parsed proposal -> skills/ file tree
  - promote:     staged skills -> ~/.claude/skills/ (with backup, dry-run)
  - sync_command: Commands/forge.md -> global command locations
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from utils import (
    BACKUP_DIR,
    COMMANDS_DIR,
    PROJECT_ROOT,
    find_claude_commands_dir,
    find_claude_skills_dir,
    load_config,
)


# ---------- materialize ----------

def materialize(parsed: dict[str, Any], staging_dir: Path, preserve_rejected: bool = True) -> None:
    """Write the skills/ file tree from a parsed proposal."""
    skills_dir = staging_dir / "skills"
    rejected_names: set[str] = set()
    rejected_dir = staging_dir / "rejected"
    if preserve_rejected and rejected_dir.exists():
        rejected_names = {p.name for p in rejected_dir.iterdir() if p.is_dir()}
        if rejected_names:
            print(f"Preserving {len(rejected_names)} rejected skill(s): {sorted(rejected_names)}")

    skills_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for skill in parsed["skills"]:
        name = skill["name"]
        if name in rejected_names:
            skipped += 1
            continue
        skill_root = skills_dir / name
        # Clear and rewrite
        if skill_root.exists():
            shutil.rmtree(skill_root)
        skill_root.mkdir(parents=True)

        _write_skill_md(skill_root / "SKILL.md", skill)

        refs_dir = skill_root / "references"
        refs_dir.mkdir()
        for ref in skill["references"]:
            _write_reference_md(refs_dir / f"{ref['slug']}.md", ref, parsed["source"])
        written += 1

    print(f"Materialized {written} skill(s) to {skills_dir} ({skipped} preserved as rejected)")


def _write_skill_md(path: Path, skill: dict[str, Any]) -> None:
    name = skill["name"]
    description = skill["description"].strip()
    version = skill.get("version", "0.1.0")
    refs = skill["references"]

    # Render description on one line (frontmatter constraint)
    description_oneline = " ".join(description.split())

    lines = [
        "---",
        f"name: {name}",
        f"description: {description_oneline}",
        f"version: {version}",
        "---",
        "",
        f"# {name}",
        "",
        description_oneline,
        "",
        "## When to use this skill",
        "",
        description_oneline,
        "",
        "## Available references",
        "",
        "Load these on demand from `references/` as the situation requires:",
        "",
    ]
    for ref in refs:
        lines.append(f"- `references/{ref['slug']}.md` — {ref['technique'].split('.')[0].strip()[:120]}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_reference_md(path: Path, ref: dict[str, Any], source: dict[str, Any]) -> None:
    slug = ref["slug"]
    timestamp = ref["timestamp"]
    technique = ref["technique"].strip()
    when_to_apply = ref["when_to_apply"].strip()
    settings = ref.get("settings", [])
    related = ref.get("related", [])

    title = slug.replace("-", " ").title()

    lines = [
        f"# {title}",
        "",
        f"**Source:** {source['channel']} — {source['title']} [{source['video_id']}]",
        f"**Timestamp:** {timestamp}",
        f"**URL:** {source['url']}",
        "",
        "## Technique",
        "",
        technique,
        "",
        "## When to apply",
        "",
        when_to_apply,
        "",
    ]

    if settings:
        lines.append("## Settings")
        lines.append("")
        for s in settings:
            lines.append(f"- {s}")
        lines.append("")

    if related:
        lines.append("## Related")
        lines.append("")
        for r in related:
            lines.append(f"- `{r}.md`")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------- promote ----------

def promote(staging_dir: Path, force: bool = False, dry_run: bool = False) -> int:
    """Promote validated skills from staging to ~/.claude/skills/."""
    # Validate first
    from validator import validate_staging
    report = validate_staging(staging_dir)
    if report.has_failures():
        print("Validation FAILED. Aborting promotion.")
        report.print_summary()
        return 1
    if report.warnings:
        print(f"Validation passed with {len(report.warnings)} warning(s).")

    config = load_config()
    target_root = find_claude_skills_dir(config)

    skills_dir = staging_dir / "skills"
    if not skills_dir.exists():
        print(f"No skills/ directory in {staging_dir} (run materialize first)")
        return 1

    skill_dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    if not skill_dirs:
        print("No skills to promote.")
        return 0

    timestamp = datetime.now().strftime("%Y-%m-%d %H%M")
    backup_root = BACKUP_DIR / timestamp

    plan_promote: list[tuple[Path, Path]] = []
    plan_backup: list[tuple[Path, Path]] = []
    plan_skip: list[Path] = []

    for src in skill_dirs:
        dst = target_root / src.name
        if dst.exists():
            if not force:
                plan_skip.append(src)
                continue
            plan_backup.append((dst, backup_root / src.name))
            plan_promote.append((src, dst))
        else:
            plan_promote.append((src, dst))

    # Print plan
    print(f"Promotion plan ({'DRY RUN' if dry_run else 'EXECUTE'}):")
    print(f"  Target:  {target_root}")
    print(f"  Backup:  {backup_root if plan_backup else '(none needed)'}")
    print()
    for src in plan_skip:
        print(f"  SKIP    {src.name}  (already exists; use --force to overwrite)")
    for old, bk in plan_backup:
        print(f"  BACKUP  {old.name}  ->  Backup/Promoted Skills/{timestamp}/{bk.name}")
    for src, dst in plan_promote:
        flag = "OVERWRITE" if any(p[0].name == src.name for p in plan_backup) else "INSTALL"
        print(f"  {flag}  {src.name}")
    print()

    if dry_run:
        print("Dry run complete. No files written.")
        return 0

    # Execute
    if plan_backup:
        backup_root.mkdir(parents=True, exist_ok=True)
        for old, bk in plan_backup:
            shutil.copytree(old, bk)
            shutil.rmtree(old)

    target_root.mkdir(parents=True, exist_ok=True)
    for src, dst in plan_promote:
        shutil.copytree(src, dst)

    print(f"Promoted {len(plan_promote)} skill(s); backed up {len(plan_backup)}; skipped {len(plan_skip)}.")
    return 0


# ---------- sync-command ----------

def sync_command(dry_run: bool = False) -> int:
    """Install Commands/forge.md to global locations."""
    src = COMMANDS_DIR / "forge.md"
    if not src.exists():
        print(f"Source skill missing: {src}")
        return 1

    config = load_config()
    targets: list[tuple[str, Path]] = []

    cc = find_claude_commands_dir(config)
    targets.append(("~/.claude/commands", cc))

    ccb = config.get("claude_code_brain_commands_dir")
    if ccb:
        targets.append(("Claude Code Brain/commands", Path(ccb)))

    ag = config.get("antigravity_brain_commands_dir")
    if ag:
        targets.append(("Antigravity Brain/commands", Path(ag)))

    print(f"sync-command plan ({'DRY RUN' if dry_run else 'EXECUTE'}):")
    print(f"  Source: {src}")
    print()

    plan = []
    for label, dst_dir in targets:
        dst = dst_dir / "forge.md"
        action = "UPDATE" if dst.exists() else "INSTALL"
        plan.append((label, dst, action))
        print(f"  {action}  {label}: {dst}")
    print()

    if dry_run:
        print("Dry run complete. No files written.")
        return 0

    for label, dst, _action in plan:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print(f"Synced to {len(plan)} location(s).")
    return 0
