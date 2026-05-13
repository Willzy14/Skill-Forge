"""Skill Forge — writer.

Responsibilities:
  - materialize: parsed proposal -> staging/skills/ file tree
  - promote: staged skills -> ~/.claude/skills/ with backup, dry-run, merge, --report-json
  - sync_command: Commands/forge.md -> global command locations

Merge orchestration:
  1. Load live + staging snapshots (via snapshot.py)
  2. Compute merge (via merger.py, pure)
  3. Apply resolutions (from --resolutions JSON, or --force, or chat via /forge)
  4. Write merged snapshot to a temp dir
  5. Validate temp dir (validator.validate_skill_folder_at)
  6. Copy live -> backup
  7. Controlled directory swap with rollback
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
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
    version = skill.get("version", 1)
    if isinstance(version, str):
        # Allow legacy "0.1.0" or quoted "1"
        from snapshot import _parse_version  # type: ignore  # noqa
        version = _parse_version(version)
    refs = skill["references"]

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


# ---------- promote (with merge) ----------

@dataclass
class SkillPlan:
    name: str
    action: str                        # INSTALL | SKIP | OVERWRITE | MERGE
    src: Path                          # staging skill dir
    dst: Path                          # live skill dir
    backup_path: Path | None = None
    # Merge-specific
    needs_user_input: bool = False
    description_action: str | None = None
    references_kept: list[str] = field(default_factory=list)
    references_added: list[str] = field(default_factory=list)
    references_collided: list[dict] = field(default_factory=list)
    new_version: int | None = None
    notes: list[str] = field(default_factory=list)


def promote(
    staging_dir: Path,
    force: bool = False,
    dry_run: bool = False,
    merge: bool = False,
    resolutions_path: Path | None = None,
    report_json: bool = False,
) -> int:
    """Promote validated skills from staging to ~/.claude/skills/."""
    # CLI invariant: --resolutions implies --merge
    if resolutions_path is not None and not merge:
        _emit_error("--resolutions requires --merge", report_json)
        return 2

    # Validate staging first
    from validator import validate_staging
    report = validate_staging(staging_dir)
    if report.has_failures():
        if report_json:
            _emit_json({"mode": "promote", "error": "validation_failed",
                        "issues": [_issue_dict(i) for i in report.issues]})
        else:
            print("Validation FAILED. Aborting promotion.")
            report.print_summary()
        return 1
    if report.warnings and not report_json:
        print(f"Validation passed with {len(report.warnings)} warning(s).")

    config = load_config()
    target_root = find_claude_skills_dir(config)
    skills_dir = staging_dir / "skills"

    if not skills_dir.exists():
        _emit_error(f"No skills/ in {staging_dir} (run materialize first)", report_json)
        return 1

    skill_dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    if not skill_dirs:
        _emit_error("No skills to promote.", report_json)
        return 0

    timestamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    backup_root = BACKUP_DIR / timestamp

    # Load resolutions if provided
    resolutions: dict[str, Any] = {}
    if resolutions_path is not None:
        try:
            resolutions = json.loads(resolutions_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            _emit_error(f"failed to read resolutions JSON: {e}", report_json)
            return 2

    # Plan each skill
    plans: list[SkillPlan] = []
    merge_contexts: dict[str, dict] = {}   # name -> merger artefacts for execution

    for src in skill_dirs:
        plan = _plan_skill(
            src=src,
            target_root=target_root,
            backup_root=backup_root,
            force=force,
            merge=merge,
            resolutions_for_skill=_resolutions_for(resolutions, src.name),
            merge_contexts=merge_contexts,
        )
        plans.append(plan)

    # Output report
    if report_json:
        _emit_json(_build_json_report(plans, merge=merge, dry_run=dry_run, mode_label=_mode_label(merge, force, dry_run)))
    else:
        _print_human_plan(plans, target_root, backup_root, dry_run=dry_run, force=force, merge=merge)

    if dry_run:
        return 0

    # Abort if any merge plan needs user input
    blockers = [p for p in plans if p.needs_user_input]
    if blockers:
        msg = (
            "merge plans need resolution before execution: "
            + ", ".join(b.name for b in blockers)
            + " (run with --dry-run --report-json to capture the plan, then pass --resolutions)"
        )
        _emit_error(msg, report_json)
        return 1

    # Execute
    n_installed = n_merged = n_overwritten = n_skipped = 0
    for plan in plans:
        if plan.action == "SKIP":
            n_skipped += 1
            continue
        if plan.action == "INSTALL":
            target_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(plan.src, plan.dst)
            n_installed += 1
        elif plan.action == "OVERWRITE":
            backup_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(plan.dst, backup_root / plan.dst.name)
            shutil.rmtree(plan.dst)
            shutil.copytree(plan.src, plan.dst)
            n_overwritten += 1
        elif plan.action == "MERGE":
            _execute_merge(plan, merge_contexts[plan.name], backup_root, config)
            n_merged += 1

    if not report_json:
        print(
            f"Promoted {n_installed + n_overwritten + n_merged} skill(s) "
            f"(installed: {n_installed}, merged: {n_merged}, overwritten: {n_overwritten}, "
            f"skipped: {n_skipped})."
        )
    return 0


# ---------- planning ----------

def _plan_skill(
    src: Path,
    target_root: Path,
    backup_root: Path,
    force: bool,
    merge: bool,
    resolutions_for_skill: dict[str, Any],
    merge_contexts: dict[str, dict],
) -> SkillPlan:
    name = src.name
    dst = target_root / name

    if not dst.exists():
        return SkillPlan(name=name, action="INSTALL", src=src, dst=dst)

    if not merge:
        if force:
            return SkillPlan(
                name=name, action="OVERWRITE", src=src, dst=dst,
                backup_path=backup_root / name,
                notes=["use --merge to combine instead of overwrite"],
            )
        return SkillPlan(
            name=name, action="SKIP", src=src, dst=dst,
            notes=["already exists; use --force to overwrite or --merge to combine"],
        )

    # ---- Merge planning ----
    from snapshot import load_skill
    from merger import (
        Collision,
        apply_resolutions,
        compute_merge,
    )

    try:
        live = load_skill(dst)
        staging = load_skill(src)
    except Exception as e:  # noqa: BLE001
        return SkillPlan(
            name=name, action="SKIP", src=src, dst=dst,
            notes=[f"failed to load snapshots for merge: {e}"],
        )

    result = compute_merge(live, staging, force_staging_on_collision=force)

    # Try to apply resolutions if any were provided
    resolution_error: str | None = None
    if resolutions_for_skill or force:
        try:
            apply_resolutions(
                result,
                collision_resolutions=resolutions_for_skill.get("collisions", {}),
                description_resolution=resolutions_for_skill.get("description"),
            )
        except ValueError as e:
            resolution_error = str(e)

    plan = SkillPlan(
        name=name,
        action="MERGE",
        src=src,
        dst=dst,
        backup_path=backup_root / name,
        needs_user_input=result.needs_user_input or resolution_error is not None,
        description_action=result.description_action,
        references_kept=list(result.references_kept),
        references_added=list(result.references_added),
        new_version=result.new_version,
        notes=[],
    )

    if force and result.references_collided:
        plan.notes.append(
            f"FORCE MERGE: {len(result.references_collided)} reference collisions will use staging versions"
        )

    plan.references_collided = []
    for c in result.references_collided:
        plan.references_collided.append({
            "slug": c.slug,
            "needs_resolution": c.needs_resolution,
            "resolution": c.resolution,
            "live_path": str(dst / "references" / f"{c.slug}.md"),
            "staging_path": str(src / "references" / f"{c.slug}.md"),
            "live_sha256": c.live_ref.sha256,
            "staging_sha256": c.staging_ref.sha256,
            "live_preview": c.live_ref.preview(),
            "staging_preview": c.staging_ref.preview(),
        })

    if resolution_error:
        plan.notes.append(f"resolution error: {resolution_error}")

    # Cache merger artefacts for the execution phase
    merge_contexts[name] = {
        "live": live,
        "staging": staging,
        "result": result,
    }

    return plan


# ---------- merge execution ----------

def _execute_merge(plan: SkillPlan, ctx: dict, backup_root: Path, config: dict) -> None:
    """Steps 3-7 of the merge algorithm: temp dir, validate, backup, swap."""
    from snapshot import write_skill
    from merger import materialize_merged_snapshot
    from validator import validate_skill_folder_at

    live = ctx["live"]
    staging = ctx["staging"]
    result = ctx["result"]

    # 3. Build merged snapshot and write to temp dir
    merged = materialize_merged_snapshot(result, live, staging)
    temp_root = Path(tempfile.mkdtemp(prefix="skill-forge-merge-"))
    temp_skill_dir = temp_root / plan.name
    write_skill(merged, temp_skill_dir)

    # 4. Validate temp dir
    temp_report = validate_skill_folder_at(temp_skill_dir, config=config, check_already_promoted=False)
    if temp_report.has_failures():
        # No live skill was touched. Surface validation errors and abort.
        msg = (
            f"post-merge validation FAILED for {plan.name}. "
            "Live skill not modified. Issues:"
        )
        print(msg)
        temp_report.print_summary()
        shutil.rmtree(temp_root, ignore_errors=True)
        raise RuntimeError(f"post-merge validation failed for {plan.name}")

    # 5. Copy live -> backup
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / plan.name
    if backup_path.exists():
        shutil.rmtree(backup_path)
    shutil.copytree(plan.dst, backup_path)

    # 6. Controlled directory swap with rollback
    timestamp_suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    old_live_path = plan.dst.with_name(plan.dst.name + f".old-live-{timestamp_suffix}")

    try:
        shutil.move(str(plan.dst), str(old_live_path))
    except Exception as e:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise RuntimeError(f"failed to move live skill aside: {e}") from e

    try:
        shutil.move(str(temp_skill_dir), str(plan.dst))
    except Exception as e:
        # Rollback: move old-live back
        try:
            shutil.move(str(old_live_path), str(plan.dst))
        except Exception:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)
        raise RuntimeError(f"failed to move merged skill into live location: {e}") from e

    # 7. Paranoia: validate the now-live skill before committing to deletion
    post_report = validate_skill_folder_at(plan.dst, config=config, check_already_promoted=False)
    if post_report.has_failures():
        # Roll back
        try:
            shutil.rmtree(plan.dst)
        except Exception:
            pass
        shutil.move(str(old_live_path), str(plan.dst))
        shutil.rmtree(temp_root, ignore_errors=True)
        raise RuntimeError(
            f"post-swap validation FAILED for {plan.name}; rolled back to pre-merge state"
        )

    # 8. Delete old-live (the backup is the canonical archive)
    shutil.rmtree(old_live_path, ignore_errors=True)
    shutil.rmtree(temp_root, ignore_errors=True)


# ---------- reporting ----------

def _print_human_plan(
    plans: list[SkillPlan],
    target_root: Path,
    backup_root: Path,
    dry_run: bool,
    force: bool,
    merge: bool,
) -> None:
    mode = _mode_label(merge, force, dry_run)
    print(f"Promotion plan ({mode}):")
    print(f"  Target:  {target_root}")
    needs_backup = any(p.backup_path for p in plans)
    print(f"  Backup:  {backup_root if needs_backup else '(none needed)'}")
    print()

    for p in plans:
        print(f"  {p.action:<10} {p.name}")
        for note in p.notes:
            print(f"             - {note}")
        if p.action == "MERGE":
            if p.references_added:
                print(f"             refs added:    {', '.join(p.references_added)}")
            if p.references_kept:
                print(f"             refs kept:     {', '.join(p.references_kept)}")
            if p.references_collided:
                for c in p.references_collided:
                    status = (
                        f"resolution={c['resolution']}"
                        if not c["needs_resolution"]
                        else "NEEDS RESOLUTION"
                    )
                    print(f"             collision:    {c['slug']}  [{status}]")
            if p.description_action:
                marker = "NEEDS RESOLUTION" if p.description_action == "needs-resolution" else p.description_action
                print(f"             description:  {marker}")
            print(f"             new version:  {p.new_version}")
    print()

    if dry_run:
        blockers = [p.name for p in plans if p.needs_user_input]
        if blockers:
            print(f"NEEDS RESOLUTION: {', '.join(blockers)}")
            print("Re-run with --resolutions <file> to apply decisions.")
        else:
            print("Dry run complete. No files written.")


def _build_json_report(
    plans: list[SkillPlan], merge: bool, dry_run: bool, mode_label: str
) -> dict:
    skills_out = []
    for p in plans:
        entry: dict[str, Any] = {
            "name": p.name,
            "action": p.action,
            "needs_user_input": p.needs_user_input,
            "notes": p.notes,
        }
        if p.backup_path is not None:
            entry["backup_path"] = str(p.backup_path)
        if p.action == "MERGE":
            entry.update({
                "references_kept": p.references_kept,
                "references_added": p.references_added,
                "references_collided": p.references_collided,
                "description_action": p.description_action,
                "new_version": p.new_version,
            })
        skills_out.append(entry)

    summary = {
        "installed": sum(1 for p in plans if p.action == "INSTALL"),
        "overwritten": sum(1 for p in plans if p.action == "OVERWRITE"),
        "merged": sum(1 for p in plans if p.action == "MERGE"),
        "skipped": sum(1 for p in plans if p.action == "SKIP"),
        "needs_resolution": any(p.needs_user_input for p in plans),
    }
    return {
        "mode": "merge" if merge else "promote",
        "mode_label": mode_label,
        "dry_run": dry_run,
        "skills": skills_out,
        "summary": summary,
    }


def _emit_json(data: dict) -> None:
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _emit_error(msg: str, report_json: bool) -> None:
    if report_json:
        _emit_json({"error": msg})
    else:
        print(f"ERROR: {msg}", file=sys.stderr)


def _issue_dict(issue) -> dict:
    return {"level": issue.level, "target": issue.target, "message": issue.message}


def _mode_label(merge: bool, force: bool, dry_run: bool) -> str:
    parts = []
    if merge:
        parts.append("MERGE")
    if force:
        parts.append("FORCE")
    if dry_run:
        parts.append("DRY RUN")
    return " ".join(parts) if parts else "EXECUTE"


def _resolutions_for(resolutions: dict, skill_name: str) -> dict:
    """Resolutions JSON may be either a single-skill object or a multi-skill map."""
    if not resolutions:
        return {}
    # Single-skill form: {"schema_version": 1, "skill_name": "...", "collisions": {...}, "description": {...}}
    if "skill_name" in resolutions:
        if resolutions["skill_name"] == skill_name:
            return resolutions
        return {}
    # Multi-skill form: {"<skill-name>": {"collisions": {...}, "description": {...}}, ...}
    return resolutions.get(skill_name, {})


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
