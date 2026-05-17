# Skill Forge

## What This Is
A pipeline that reads YouTube transcripts (and potentially other text sources) and extracts structured, reusable skills for Cortex. Takes raw tutorial knowledge and turns it into actionable, searchable skill entries. Part of Sam's knowledge ecosystem — the step between "I watched a tutorial" and "I can use that knowledge in any project."

## Tech Stack
- Python 3.14
- Cortex MCP (Neon PostgreSQL) — skill storage via `cortex_add`
- Reads from YouTube Transcription project's `Transcripts/` folder

## Architecture
```
Skill Forge/
├── Source/
│   ├── forge.py             # Main CLI — reads transcripts, extracts skills
│   └── utils.py             # Text chunking, skill formatting helpers
├── Config/
│   └── settings.json        # Extraction tunables
├── Documentation/
│   ├── AI_CONTEXT.md        # This file
│   └── TOOLBOX.md           # Module reference
├── .github/
│   ├── memory.json
│   ├── ai-activity-log.md
│   └── copilot-instructions.md
└── .gitignore
```

**Data flow:** Transcript file (markdown) → parse into sections → identify discrete skills/techniques → format as Cortex skill entries → push to Cortex (or output as structured markdown)

## How to Run
```powershell
# Activate venv
.\.venv\Scripts\Activate.ps1

# Environment check
python Source/forge.py doctor

# Build extraction package (Claude does the actual extraction next)
python Source/forge.py extract "path/to/transcript.md"
python Source/forge.py extract --channel "Blender Guru"

# After Claude writes proposed_skills.json + PROPOSED_SKILLS.md:
python Source/forge.py materialize "Output/<channel>/<video>"
python Source/forge.py validate "Output/<channel>/<video>"

# Preview then promote to ~/.claude/skills/
python Source/forge.py promote "Output/<channel>/<video>" --dry-run
python Source/forge.py promote "Output/<channel>/<video>"
python Source/forge.py promote "Output/<channel>/<video>" --force   # overwrite

# Sync the /forge global skill to ~/.claude/commands/ (and brain folders)
python Source/forge.py sync-command --dry-run
python Source/forge.py sync-command

# From any project: /forge "path/to/transcript.md"
```

## Current State
- Pipeline fully functional and tested end-to-end
- `forge doctor` reports 10/10 PASS (WARN for local.settings.json, FAIL for YouTube Transcription project path — both non-blocking for inline transcripts)
- `/forge` global skill installed in `~/.claude/commands/` + brain folders
- First successful extraction: Donut Finale transcript -> 2 skills (`blender-lighting`, `blender-rendering`) with 17 references total
- Second successful extraction: Max Hay "Wet Concrete Textures" -> 1 skill (`blender-reflective-surfaces`) with 7 references
- Skills promoted to `~/.claude/skills/` which is now **symlinked to Dropbox** (`Claude Code Brain/skills/`) for cross-machine sync
- Forge can accept inline transcripts (saved to `Input/` folder) — doesn't require YouTube Transcription project
- Hard staging/promotion boundary working (extract writes ONLY to Output/; promote is separate explicit step)
- Validation catches over-long descriptions (caught one on first run; iterated and re-validated)
- Backup-on-overwrite with `YYYY-MM-DD HHMM` timestamps tested via dry-run
- `SYMLINK_SETUP.md` created in Dropbox Claude Code Brain folder with Mac/Windows symlink instructions
- **179 global skills installed** across all categories (SEO, marketing, ads, social, YouTube, Blender, Spotify, unslop)
- **Spotify MCP server** configured — code lives in Dropbox `Claude Code Brain/mcp-servers/`, .env credentials synced cross-machine
- External skill scouting research saved to `Research/External Skill Scouting 2026-05-17.md` (on main)

## What's Next
1. **Batch-process remaining donut transcripts** — `/forge --channel "Blender Guru"` for the other 7 videos
2. **Process more Max Hay tutorials** — proven source of high-quality Blender techniques
3. Try a non-Blender domain — e.g. a mixing tutorial — to validate the prompt works domain-agnostic
4. Set up Mac symlinks using `SYMLINK_SETUP.md` instructions so both machines share skills
5. **Custom skill gaps** — build skills for: OBS streaming, Beatport research, DAW mixing, DJ automation (no good open-source options found)
6. **Spotify MCP first use** — test playlist creation/management after restart

## Key Decisions
- **Separate project from YouTube Transcription** — transcription has one job (download + format), this has another (extract + structure). Clean separation.
- **Reads from YouTube Transcription's Transcripts/ folder** — doesn't duplicate transcripts, just consumes them as input.
- **Hard staging/promotion boundary** — extraction only writes to project-local `Output/`. The ONLY command that touches `~/.claude/skills/` is `forge promote`. Bad skills can't pollute Claude's discovery layer accidentally.
- **JSON as parser source of truth** — Claude writes both `proposed_skills.json` (canonical) and `PROPOSED_SKILLS.md` (human review). Parser prefers JSON, falls back to fenced block in MD.
- **Output Claude skills (not Cortex)** — pivoted from original plan after user feedback. The pipeline produces SKILL.md + references/*.md folders in the format Claude Code auto-discovers via `name`/`description` frontmatter matching.
- **Hierarchy is mandatory** — overview clusters become top-level skills, granular techniques are reference files nested inside. Never flat 80-skill discovery pool.
- **Promote runs validate first** — fails closed on any FAIL. Validation WARNs about existing-promoted-skill, only `promote --force` overwrites (with backup).
- **Skills live in Dropbox** — `~/.claude/skills/` is symlinked to `Claude Code Brain/skills/` in Dropbox. Promotes land in Dropbox automatically and sync across all machines. No config change needed in forge — it writes to `~/.claude/skills/` which resolves through the symlink.
- **Inline transcripts accepted** — forge can process transcripts saved directly to `Input/<channel>/` when the YouTube Transcription project isn't configured. Transcript must use `[HH:MM:SS] text` segment format and metadata table.

## Connections
- **YouTube Transcription** — upstream. Provides the raw transcript files this project consumes.
- **Cortex** — downstream. Extracted skills are pushed here for cross-project reuse.
- **Blender-Content-Engine / Blender-World-Building** — first use case. Blender tutorial skills feed these projects.
- **Any Claude Code session** — extracted skills surface via `cortex_search` in any project.
