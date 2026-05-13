"""Skill Forge — CLI orchestrator.

Subcommands:
  doctor          Environment health check
  extract         Prepare extraction package for Claude
  materialize    Parse PROPOSED_SKILLS.* and write skill file tree
  validate        Validate staged skills
  promote         Copy validated skills to ~/.claude/skills/ (with backup)
  sync-command    Install Commands/forge.md to global locations
  list            Show what's staged in Output/
  discard         Remove a staging directory
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles that default to cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

# Allow direct execution: `python Source/forge.py ...`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BACKUP_DIR,
    COMMANDS_DIR,
    LOCAL_SETTINGS_PATH,
    OUTPUT_DIR,
    PROJECT_ROOT,
    PROMPTS_DIR,
    SETTINGS_PATH,
    find_claude_commands_dir,
    find_claude_skills_dir,
    find_youtube_transcription_root,
    load_config,
)

PROMPT_FILE = PROMPTS_DIR / "extract_skills.md"


# ---------- doctor ----------

class _Check:
    def __init__(self, name: str):
        self.name = name
        self.status: str = "PASS"  # PASS | WARN | FAIL
        self.detail: str = ""

    def warn(self, detail: str) -> None:
        self.status = "WARN"
        self.detail = detail

    def fail(self, detail: str) -> None:
        self.status = "FAIL"
        self.detail = detail


def _check(name: str, predicate, on_fail: str, warn_only: bool = False) -> _Check:
    c = _Check(name)
    try:
        ok, detail = predicate()
        if not ok:
            if warn_only:
                c.warn(detail or on_fail)
            else:
                c.fail(detail or on_fail)
        elif detail:
            c.detail = detail
    except Exception as e:  # noqa: BLE001
        c.fail(f"{on_fail} ({e})")
    return c


def cmd_doctor(_args: argparse.Namespace) -> int:
    print("Skill Forge — doctor")
    print("=" * 60)

    config: dict | None = None
    config_error: str = ""
    try:
        config = load_config()
    except Exception as e:  # noqa: BLE001
        config_error = str(e)

    def _project_root_ok():
        return PROJECT_ROOT.exists(), str(PROJECT_ROOT)

    def _python_ok():
        major, minor = sys.version_info.major, sys.version_info.minor
        ok = (major, minor) >= (3, 10)
        return ok, f"Python {major}.{minor}"

    def _config_ok():
        if config_error:
            return False, config_error
        return True, f"loaded {len(config or {})} settings"

    def _yt_ok():
        if not config:
            return False, "config not loaded"
        p = find_youtube_transcription_root(config)
        if p is None:
            return False, "not found (set youtube_transcription_project in local.settings.json)"
        return True, str(p)

    def _skills_dir_ok():
        if not config:
            return False, "config not loaded"
        p = find_claude_skills_dir(config)
        if p.exists():
            return True, str(p)
        # Test creatable
        try:
            p.mkdir(parents=True, exist_ok=True)
            (p / ".forge_writetest").write_text("ok", encoding="utf-8")
            (p / ".forge_writetest").unlink()
            return True, f"created {p}"
        except Exception as e:  # noqa: BLE001
            return False, f"cannot create {p}: {e}"

    def _commands_dir_ok():
        if not config:
            return False, "config not loaded"
        p = find_claude_commands_dir(config)
        return p.exists(), str(p)

    def _prompt_ok():
        if not PROMPT_FILE.exists():
            return False, f"missing {PROMPT_FILE}"
        size = PROMPT_FILE.stat().st_size
        if size < 200:
            return False, f"too short ({size} bytes)"
        return True, f"{size} bytes"

    def _output_ok():
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            (OUTPUT_DIR / ".forge_writetest").write_text("ok", encoding="utf-8")
            (OUTPUT_DIR / ".forge_writetest").unlink()
            return True, str(OUTPUT_DIR)
        except Exception as e:  # noqa: BLE001
            return False, f"cannot write to {OUTPUT_DIR}: {e}"

    def _backup_ok():
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            return True, str(BACKUP_DIR)
        except Exception as e:  # noqa: BLE001
            return False, f"cannot create {BACKUP_DIR}: {e}"

    def _local_settings_ok():
        if LOCAL_SETTINGS_PATH.exists():
            return True, "present"
        return False, "missing — using defaults / detection (run forge sync-command after creating)"

    checks = [
        _check("Skill Forge project root", _project_root_ok, "missing"),
        _check("Python >= 3.10", _python_ok, "needs Python 3.10+"),
        _check("Config loads", _config_ok, "see error"),
        _check("local.settings.json", _local_settings_ok, "missing", warn_only=True),
        _check("YouTube Transcription project", _yt_ok, "not found"),
        _check("~/.claude/skills/ writable", _skills_dir_ok, "not writable"),
        _check("~/.claude/commands/ exists", _commands_dir_ok, "missing"),
        _check("Prompts/extract_skills.md", _prompt_ok, "missing or too short", warn_only=True),
        _check("Output/ writable", _output_ok, "not writable"),
        _check("Backup/Promoted Skills/ writable", _backup_ok, "not writable"),
    ]

    # Print
    fail_count = warn_count = 0
    for c in checks:
        symbol = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[c.status]
        line = f"{symbol} {c.name}"
        if c.detail:
            line += f"  ({c.detail})"
        print(line)
        if c.status == "FAIL":
            fail_count += 1
        elif c.status == "WARN":
            warn_count += 1

    print("=" * 60)
    print(f"{len(checks)} checks — {fail_count} FAIL, {warn_count} WARN")
    return 1 if fail_count else 0


# ---------- stubs (wired in later step) ----------

def cmd_extract(args: argparse.Namespace) -> int:
    from extractor import build_extraction_package
    return build_extraction_package(args)


def cmd_materialize(args: argparse.Namespace) -> int:
    from parser import parse_proposed_skills
    from writer import materialize
    data = parse_proposed_skills(Path(args.staging_dir))
    materialize(data, Path(args.staging_dir), preserve_rejected=not args.no_preserve_rejected)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from validator import validate_staging
    report = validate_staging(Path(args.staging_dir))
    return report.print_and_status()


def cmd_promote(args: argparse.Namespace) -> int:
    from writer import promote
    return promote(
        Path(args.staging_dir),
        force=args.force,
        dry_run=args.dry_run,
    )


def cmd_sync_command(args: argparse.Namespace) -> int:
    from writer import sync_command
    return sync_command(dry_run=args.dry_run)


def cmd_list(_args: argparse.Namespace) -> int:
    if not OUTPUT_DIR.exists():
        print("(Output/ is empty)")
        return 0
    found = False
    for channel_dir in sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir()):
        for video_dir in sorted(p for p in channel_dir.iterdir() if p.is_dir()):
            found = True
            rel = video_dir.relative_to(PROJECT_ROOT)
            has_json = (video_dir / "proposed_skills.json").exists()
            has_md = (video_dir / "PROPOSED_SKILLS.md").exists()
            has_skills = (video_dir / "skills").exists()
            tags = []
            if has_json: tags.append("json")
            if has_md: tags.append("md")
            if has_skills: tags.append("skills/")
            tag_str = ", ".join(tags) if tags else "empty"
            print(f"  {rel}  [{tag_str}]")
    if not found:
        print("(Output/ is empty)")
    return 0


def cmd_discard(args: argparse.Namespace) -> int:
    import shutil
    target = Path(args.staging_dir)
    if not target.exists():
        print(f"Not found: {target}")
        return 1
    if not str(target.resolve()).startswith(str(OUTPUT_DIR.resolve())):
        print(f"Refusing to discard outside Output/: {target}")
        return 1
    shutil.rmtree(target)
    print(f"Discarded: {target}")
    return 0


# ---------- main ----------

def main() -> int:
    parser = argparse.ArgumentParser(prog="forge", description="Skill Forge CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Environment health check").set_defaults(func=cmd_doctor)

    p_extract = sub.add_parser("extract", help="Prepare extraction package")
    p_extract.add_argument("transcript", nargs="?", help="Path to transcript .md")
    p_extract.add_argument("--channel", help="Channel folder name (batch all videos)")
    p_extract.add_argument("--force", action="store_true", help="Overwrite existing staging dir")
    p_extract.set_defaults(func=cmd_extract)

    p_mat = sub.add_parser("materialize", help="Parse PROPOSED_SKILLS.* → skill file tree")
    p_mat.add_argument("staging_dir")
    p_mat.add_argument("--no-preserve-rejected", action="store_true")
    p_mat.set_defaults(func=cmd_materialize)

    p_val = sub.add_parser("validate", help="Validate staged skills")
    p_val.add_argument("staging_dir")
    p_val.set_defaults(func=cmd_validate)

    p_prom = sub.add_parser("promote", help="Promote validated skills to ~/.claude/skills/")
    p_prom.add_argument("staging_dir")
    p_prom.add_argument("--force", action="store_true", help="Overwrite existing skills (backup first)")
    p_prom.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p_prom.set_defaults(func=cmd_promote)

    p_sync = sub.add_parser("sync-command", help="Sync Commands/forge.md to global locations")
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.set_defaults(func=cmd_sync_command)

    sub.add_parser("list", help="List staged extractions").set_defaults(func=cmd_list)

    p_dis = sub.add_parser("discard", help="Remove a staging directory")
    p_dis.add_argument("staging_dir")
    p_dis.set_defaults(func=cmd_discard)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
