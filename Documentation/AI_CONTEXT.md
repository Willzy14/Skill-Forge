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
- `forge doctor` reports 10/10 PASS
- `/forge` global skill installed in `~/.claude/commands/` + brain folders
- First successful extraction: Donut Finale transcript -> 2 skills (`blender-lighting`, `blender-rendering`) with 17 references total
- Skills promoted to `~/.claude/skills/` and ready for Claude auto-discovery
- Hard staging/promotion boundary working (extract writes ONLY to Output/; promote is separate explicit step)
- Validation catches over-long descriptions (caught one on first run; iterated and re-validated)
- Backup-on-overwrite with `YYYY-MM-DD HHMM` timestamps tested via dry-run

## What's Next
1. **Discovery test** — fresh chat: "I'm lighting a concrete dam at golden hour" — does Claude reference `blender-lighting`?
2. Iterate the extraction prompt if discovery is weak
3. Batch-process the remaining 7 donut transcripts (`/forge --channel "Blender Guru"`)
4. Try a non-Blender domain — e.g. a mixing tutorial — to validate the prompt works domain-agnostic

## Key Decisions
- **Separate project from YouTube Transcription** — transcription has one job (download + format), this has another (extract + structure). Clean separation.
- **Reads from YouTube Transcription's Transcripts/ folder** — doesn't duplicate transcripts, just consumes them as input.
- **Hard staging/promotion boundary** — extraction only writes to project-local `Output/`. The ONLY command that touches `~/.claude/skills/` is `forge promote`. Bad skills can't pollute Claude's discovery layer accidentally.
- **JSON as parser source of truth** — Claude writes both `proposed_skills.json` (canonical) and `PROPOSED_SKILLS.md` (human review). Parser prefers JSON, falls back to fenced block in MD.
- **Output Claude skills (not Cortex)** — pivoted from original plan after user feedback. The pipeline produces SKILL.md + references/*.md folders in the format Claude Code auto-discovers via `name`/`description` frontmatter matching.
- **Hierarchy is mandatory** — overview clusters become top-level skills, granular techniques are reference files nested inside. Never flat 80-skill discovery pool.
- **Promote runs validate first** — fails closed on any FAIL. Validation WARNs about existing-promoted-skill, only `promote --force` overwrites (with backup).

## Connections
- **YouTube Transcription** — upstream. Provides the raw transcript files this project consumes.
- **Cortex** — downstream. Extracted skills are pushed here for cross-project reuse.
- **Blender-Content-Engine / Blender-World-Building** — first use case. Blender tutorial skills feed these projects.
- **Any Claude Code session** — extracted skills surface via `cortex_search` in any project.
