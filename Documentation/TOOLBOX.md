# Toolbox — Skill Forge

## Modules

### Source/forge.py
Main CLI orchestrator. Argparse with subcommands: `doctor`, `extract`, `materialize`, `validate`, `promote`, `sync-command`, `list`, `discard`. Forces UTF-8 stdout on Windows. Each subcommand delegates to the appropriate module.

### Source/utils.py
Shared utilities:
- `PROJECT_ROOT`, `CONFIG_DIR`, `OUTPUT_DIR`, `BACKUP_DIR`, `COMMANDS_DIR`, `PROMPTS_DIR` — path constants
- `load_config()` — merges `settings.json` + `local.settings.json` over `DEFAULT_SETTINGS`
- `slugify(text)` — filesystem-safe ASCII slug
- `Transcript`, `TranscriptSegment` dataclasses + `load_transcript(path)` for parsing YouTube Transcription markdown
- `find_youtube_transcription_root(config)` / `find_claude_skills_dir(config)` / `find_claude_commands_dir(config)` — path resolution with config override + fallbacks
- `staging_dir_for(transcript)` — where a transcript's extraction lives in `Output/`

### Source/parser.py
Loads and validates the proposal. `parse_proposed_skills(staging_dir)`:
1. Prefers `proposed_skills.json` if present and schema-valid
2. Falls back to fenced ```json block in `PROPOSED_SKILLS.md`
3. Warns if both exist but differ; uses JSON as canonical
- Hand-rolled JSON schema validation (no jsonschema dependency)
- `ParseError` raised with explicit messages on failures

### Source/writer.py
Three responsibilities:
- `materialize(parsed, staging_dir, preserve_rejected=True)` — writes the `skills/` file tree from a parsed proposal. Preserves any skill name in `rejected/` by default.
- `promote(staging_dir, force, dry_run)` — copies validated skills to `~/.claude/skills/`. Runs `validator.validate_staging` first. Backs up overwrites to `Backup/Promoted Skills/YYYY-MM-DD HHMM/`.
- `sync_command(dry_run)` — installs `Commands/forge.md` to `~/.claude/commands/`, Claude Code Brain, and Antigravity Brain command folders.

### Source/validator.py
Validates a staged skill tree. `validate_staging(staging_dir) -> Report`. Checks per-skill folder (SKILL.md exists, frontmatter `name` matches folder, `description` length + prefix), per-reference file (required sections, HH:MM:SS timestamp, body length, slug uniqueness across skills), cross-skill (duplicate slugs). `Report.print_and_status()` returns exit code.

### Source/extractor.py
Builds the extraction package Claude will consume. `build_extraction_package(args)`:
1. Loads transcript(s) (single file or `--channel` batch)
2. Runs pre-extraction validation (body chars, prompt exists, staging dir clean)
3. Copies the prompt template + writes `EXTRACT_REQUEST.md` into the staging dir
- `PreExtractError` for sanity-check failures

### Config/settings.json
Committed defaults: granularity, min/max references, description constraints, transcript thresholds.

### Config/local.settings.json
Gitignored, machine-specific: YouTube Transcription project path, Claude skills/commands directories, brain folder locations. `local.settings.example.json` is committed as a template.

### Prompts/extract_skills.md
The extraction prompt template. Contains the rules, schema, naming conventions, filter rules, and a fully-worked few-shot example from the Donut Finale (`blender-lighting` cluster with 6 references). Copied into each staging dir alongside `EXTRACT_REQUEST.md`.

### Commands/forge.md
Source-controlled global skill. Synced to `~/.claude/commands/forge.md` (and brain folders) via `forge sync-command`. Thin wrapper that calls into `forge.py` subcommands.

## Output Format

```
~/.claude/skills/
└── <skill-name>/
    ├── SKILL.md          # YAML frontmatter: name, description, version
    └── references/*.md   # Granular techniques, loaded on demand
```

`SKILL.md` description is the discovery hook — must start with "This skill should be used when" and be 60-600 chars.

## Dependencies

Standard library only. No third-party packages.
