# Skill Forge — Copilot Instructions

---

## AI ACTIVITY LOG — READ AND UPDATE EVERY TASK

**Do this at the start of every conversation and before every task:**

1. Read `.github/ai-activity-log.md` — check the last 5 entries
2. Before starting: append `[YYYY-MM-DD HH:MM] Copilot - STARTED: brief description`
3. After finishing: append `[YYYY-MM-DD HH:MM] Copilot - DONE: what changed and which files`
4. If abandoned: append `[YYYY-MM-DD HH:MM] Copilot - ABANDONED: reason`

> This log is shared with Claude Code. Never delete entries — append only.

---

## Project Location

This project lives inside Sam's Dropbox under `Wired Masters Dropbox/Sam Wills/0.1---GIT HUB---/Skill Forge`.
The drive letter / prefix changes per computer (e.g. `F:\...` on Carillon AC-1, `/Users/samuelwills/...` on Mac), but the `Wired Masters Dropbox/Sam Wills/0.1---GIT HUB---/` portion is constant.

## Project Overview

Skill Forge reads YouTube transcripts (and potentially other text sources) and extracts structured, reusable skills for Cortex. It consumes transcripts from the YouTube Transcription project and outputs actionable skill entries.

## Current Status

Bootstrapped — no code yet, planning phase.

## Key Files

| File | Purpose |
|------|---------|
| Source/forge.py | Main extraction pipeline (TBD) |
| Source/utils.py | Text processing helpers (TBD) |
| Config/settings.json | Extraction settings (TBD) |
| Documentation/AI_CONTEXT.md | Living project brain |
| Documentation/TOOLBOX.md | Module reference |

## Connections

- **Upstream:** YouTube Transcription project provides transcript files
- **Downstream:** Cortex (Neon PostgreSQL) stores extracted skills
- **Consumers:** Any Claude Code session via `cortex_search`
