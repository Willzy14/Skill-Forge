# Forge — Extract Skills from Transcripts

Turn a YouTube tutorial transcript into a library of reusable Claude skills. Extraction writes to project-local staging (`Skill Forge/Output/`). Promotion to `~/.claude/skills/` is always a separate explicit step.

## Arguments

$ARGUMENTS — typically a transcript path or `--channel "Channel Name"`. Other flags:
- `--force` — overwrite existing staging dir
- `--promote PATH` — promote a previously-extracted package
- `--dry-run` — preview a promote without writing

## Examples

- `/forge "F:\...\Transcripts\Blender Guru\Donut Finale.md"` — extract one transcript
- `/forge --channel "Blender Guru"` — batch all transcripts in the channel
- `/forge --promote "Output/blender-guru/donut-finale"` — promote a reviewed package
- `/forge --promote "Output/blender-guru/donut-finale" --dry-run` — preview

## Instructions

### 1. Locate the Skill Forge project

The project lives in the Dropbox project hub. Detect the path:

- **Windows (Carillon AC-1):** `F:\Wired Masters Dropbox\Sam Wills\0.1---GIT HUB---\Skill Forge`
- **Mac:** `/Users/samuelwills/Wired Masters Dropbox/Sam Wills/0.1---GIT HUB---/Skill Forge`

If neither exists, check under the user's home directory for `Wired Masters Dropbox`. If still not found, tell the user and stop.

Set `$SF_PROJECT` to the resolved path. The Python venv is at `$SF_PROJECT/.venv/Scripts/python.exe` (Windows) or `$SF_PROJECT/.venv/bin/python` (Mac).

### 2. Parse the arguments

From `$ARGUMENTS`:
- `--promote PATH` → go to step 6
- `--channel NAME` → channel batch mode
- Otherwise → treat the first positional arg as a transcript path

### 3. Pre-flight: doctor

Run `forge doctor` first. If it reports any FAIL, surface the issues to the user and stop.

```
python "$SF_PROJECT/Source/forge.py" doctor
```

### 4. Build the extraction package

```
python "$SF_PROJECT/Source/forge.py" extract "<transcript-path>"
```

Or for a whole channel:

```
python "$SF_PROJECT/Source/forge.py" extract --channel "<channel-name>"
```

This writes `EXTRACT_REQUEST.md` + a copy of the extraction prompt into a staging directory under `Skill Forge/Output/<channel-slug>/<video-slug>/`. Note the staging path from the output — you'll need it next.

### 5. Perform the extraction (this is the work Claude does)

For each staged package:

1. Read `<staging-dir>/EXTRACT_REQUEST.md` for the inputs and the source metadata to copy into the proposal
2. Read `<staging-dir>/extract_skills.md` for the rules and few-shot example
3. Read the actual transcript file referenced in EXTRACT_REQUEST.md
4. Extract reusable techniques following the rules in `extract_skills.md`
5. Write TWO files into `<staging-dir>/`:
   - `proposed_skills.json` — parser source of truth, matches the schema in the prompt
   - `PROPOSED_SKILLS.md` — human-readable mirror, ending with the same JSON in a fenced ```json block

Then materialize and validate:

```
python "$SF_PROJECT/Source/forge.py" materialize "<staging-dir>"
python "$SF_PROJECT/Source/forge.py" validate "<staging-dir>"
```

If validate reports FAIL, surface the errors and stop. If WARN only, list the warnings and continue.

### 6. Report

Tell the user:
- How many skills were proposed
- How many references in total
- Staging directory path (so they can review)
- Validation status (PASS / WARN with count / FAIL with count)
- Next step: review `PROPOSED_SKILLS.md`, optionally move weak skills to `<staging-dir>/rejected/`, then run `/forge --promote "<staging-dir>"`

**Do NOT promote.** Promotion is always a separate explicit `/forge --promote` invocation.

### 7. Promote (separate invocation: `/forge --promote PATH`)

```
python "$SF_PROJECT/Source/forge.py" promote "<staging-dir>" [--dry-run] [--force]
```

`promote` runs validation first and aborts on FAIL. With `--dry-run`, it prints the action plan without writing. With `--force`, it backs up any existing skill of the same name to `Backup/Promoted Skills/YYYY-MM-DD HHMM/` before overwriting. Without `--force`, existing skills are skipped with a warning.

Always run with `--dry-run` first to show the user the plan, then ask for explicit confirmation before running the real promote.
