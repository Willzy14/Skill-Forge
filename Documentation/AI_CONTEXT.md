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
# Not yet built — see What's Next
```

## Current State
- Project bootstrapped — directory structure, context files, git, GitHub remote
- No code yet — planning phase

## What's Next
1. Design the skill extraction approach — what makes a good "skill" from a transcript?
2. Build the extraction pipeline
3. Test with Blender Guru donut tutorial transcripts
4. Add Cortex integration (push extracted skills directly)
5. Add `/forge` global skill so it can be run from any project

## Key Decisions
- **Separate project from YouTube Transcription** — transcription has one job (download + format), this has another (extract + structure). Clean separation.
- **Reads from YouTube Transcription's Transcripts/ folder** — doesn't duplicate transcripts, just consumes them as input.

## Connections
- **YouTube Transcription** — upstream. Provides the raw transcript files this project consumes.
- **Cortex** — downstream. Extracted skills are pushed here for cross-project reuse.
- **Blender-Content-Engine / Blender-World-Building** — first use case. Blender tutorial skills feed these projects.
- **Any Claude Code session** — extracted skills surface via `cortex_search` in any project.
