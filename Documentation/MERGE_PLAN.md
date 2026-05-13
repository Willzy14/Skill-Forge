# Skill Forge — Merge Plan

## Context

Right now, when `forge promote` encounters a staged skill whose `name` already exists in `~/.claude/skills/`, you have two options: skip it, or overwrite the whole thing (with `--force`). Neither handles the realistic case where a new transcript produces **complementary** knowledge for an existing skill — e.g. transcript 1 gave us `blender-lighting` with sun/sky/bounce references, transcript 2 covers HDRI environment lighting and area-light softboxes that should be added to the same skill rather than replacing it.

We need a third mode: **merge**. Combine the staging skill into the existing live skill, deduplicate references, and update the description so discovery surfaces the new techniques.

This plan covers `forge promote --merge`.

---

## Goals

1. Combine references from staging + live without losing either
2. Detect and resolve reference-slug collisions cleanly
3. Update the SKILL.md description so the discovery layer reflects the merged scope
4. Back up the previous live skill before any merge (so restore is always one copy away)
5. Validate the post-merge state, not just staging — staging-only validation can pass while the merged result fails
6. Keep the staging/promotion boundary intact: merge is still an explicit user step

---

## Out of scope (for v1)

- **Near-name matching.** `blender-lighting` vs `blender-light-setup` — a v1 merge only fires on exact name match. User renames in staging if they want them treated as the same.
- **Semantic dedup of reference content.** Two refs with different slugs but same technique — out of scope. User catches in review.
- **Cross-skill merge.** Merging refs from `blender-lighting-extended` into `blender-lighting` requires manual rename first.
- **Auto-merge prompts during batch.** `--channel` batch mode + `--merge` works, but every name collision still asks the user. No silent batch merging.

---

## CLI Surface

```powershell
# v1 — explicit merge flag
python Source/forge.py promote "Output/blender-guru/donut-finale" --merge
python Source/forge.py promote "Output/blender-guru/donut-finale" --merge --dry-run
python Source/forge.py promote "Output/blender-guru/donut-finale" --merge --force
```

| Flags | Behaviour |
|-------|-----------|
| (none) | Today: skip existing, install new |
| `--force` | Today: backup then overwrite (NO merge) |
| `--merge` | **New:** for existing names, merge instead of skip. For new names, install fresh. |
| `--merge --force` | Merge mode + auto-resolve slug collisions in favour of staging (no chat prompt) |
| `--merge --dry-run` | Print the full merge plan per skill without writing |

`--merge` and `--force` are NOT mutually exclusive: `--force` inside merge mode controls collision resolution, not overwrite-vs-skip.

---

## Merge Decision Table

For each skill in staging, after `forge validate` passes:

| Live skill exists? | `--merge`? | Action |
|---|---|---|
| No | n/a | `INSTALL` (today's behaviour) |
| Yes | No | `SKIP` with warning (today's behaviour without `--force`) |
| Yes | No, but `--force` | `OVERWRITE` with backup (today's behaviour with `--force`) |
| Yes | Yes | `MERGE` (new) |
| Yes | Yes + `--force` | `MERGE` with auto-resolve collisions (new) |

---

## Merge Algorithm

For a single skill (`<name>`) that exists in both staging and live:

### 1. Snapshot the live skill

Copy `~/.claude/skills/<name>/` to `Skill Forge/Backup/Promoted Skills/<YYYY-MM-DD HHMMSS>/<name>/`. **Always**, before any write — even with `--dry-run` skipping the write, the plan reports where the backup *would* go.

(Note: timestamp granularity drops from `YYYY-MM-DD HHMM` to `YYYY-MM-DD HHMMSS` to handle multiple merges within one minute. Migrate the existing format too.)

### 2. Classify references

For each reference file (`references/*.md`):

| Live has slug? | Staging has slug? | Action |
|---|---|---|
| Yes | No | `KEEP` — copy from live as-is |
| No | Yes | `ADD` — copy from staging |
| Yes | Yes, identical content | `KEEP` — no change |
| Yes | Yes, different content | `COLLISION` — see resolution below |

### 3. Resolve collisions

For each `COLLISION`:

- **With `--force`:** silently use staging version, log to report.
- **Without `--force`:** stop and ask the user via chat (Claude in the `/forge` skill orchestrates this). Three options offered:
  1. `staging` — use the new version
  2. `live` — keep the existing version
  3. `rename` — rename the staging slug (e.g. `slug` → `slug-v2`) and add both

In dry-run mode, all collisions report as `NEEDS RESOLUTION` and exit without writing.

### 4. Merge description

The SKILL.md description is the discovery hook — must cover the union of techniques. Three paths:

**A. Identical descriptions** → no change.

**B. Staging description is a superset** (contains all topic-keywords of the live description) → use staging.

**C. Otherwise** → hand off to the `/forge` chat flow. Output to chat:
```
Description collision for skill: <name>

Live description (currently active):
  <existing description>

Staging description (proposed):
  <new description>

Reply with one of:
- "use staging"
- "use live"
- "write merged: <text>"
- "draft a merged version" (Claude generates a unified description, max 600 chars)
```

In dry-run mode, mark as `DESCRIPTION CONFLICT — would prompt in non-dry-run`.

### 5. Update SKILL.md

Once references are settled and description is chosen:

- Rewrite SKILL.md with the merged description
- Bump `version` in frontmatter:
  - Added at least one reference → minor bump (0.1.0 → 0.2.0)
  - Only description changed → patch bump (0.1.0 → 0.1.1)
- Regenerate the `## Available references` bullet list at the bottom from the final merged reference set

### 6. Post-merge validation

After the in-memory merge is computed but BEFORE files are written:

- Construct a virtual "post-merge" skill folder in a temp directory
- Run `validator.validate_skill_folder()` against it
- Fail closed if validation fails — restore from backup is automatic in this case (no live skill was touched yet since merge writes happen via temp dir → atomic move)

### 7. Execute (or dry-run)

- Write the merged result to a temp dir
- Validate again (paranoia)
- Atomic rename: `~/.claude/skills/<name>` → backup location, temp dir → live location
- This ensures the live skill is never in a half-merged state visible to Claude

---

## Architecture Changes

```
Source/
├── forge.py             # +1 flag: --merge on promote
├── extractor.py         # unchanged
├── parser.py            # unchanged
├── writer.py            # +merge_skill(); refactor promote() to delegate
├── validator.py         # +validate_skill_folder_at(path) helper for post-merge check
├── merger.py            # NEW — pure merge logic, no I/O
└── utils.py             # timestamp format bumped to HHMMSS
```

**Why a separate `merger.py`?** Pure logic — given two skill data structures, return the merged structure plus a list of decisions/collisions. Easy to unit-test. `writer.py` does the file I/O around it.

---

## Data Types

```python
@dataclass
class ReferenceFile:
    slug: str
    content: str          # full file text
    front_matter: dict    # parsed metadata (timestamp, source)

@dataclass
class SkillSnapshot:
    name: str
    description: str
    version: str
    references: dict[str, ReferenceFile]   # slug -> file

@dataclass
class Collision:
    slug: str
    live_content: str
    staging_content: str
    resolution: str | None    # "staging" | "live" | "rename" | None

@dataclass
class MergeResult:
    name: str
    description_action: str          # "kept" | "replaced" | "merged" | "needs-resolution"
    description: str
    references_added: list[str]
    references_kept: list[str]
    references_collided: list[Collision]
    new_version: str
    backup_path: Path
    needs_user_input: bool
```

`MergeResult` is what `merger.compute_merge(live, staging)` returns. `writer.execute_merge(result)` applies it. The split makes dry-run trivial: compute, print, don't execute.

---

## Validation Updates

Two new checks added to `validator.py`:

1. **`validate_skill_folder_at(path: Path) -> Report`** — same checks as today's `_validate_skill_folder`, but operates on any path (not just staging). Used for the post-merge dry-run validation.

2. **Cross-reference integrity after merge** — when a merged skill's reference points to a slug in its `Related:` field, that slug must still exist in the merged reference set. Catches the "I removed `foo.md` but `bar.md` still says `Related: foo`" case.

---

## `/forge` Skill Updates

The `Commands/forge.md` global skill needs the chat-orchestration flow for merge conflicts:

1. After `promote --merge --dry-run`, parse the dry-run report
2. For each `NEEDS RESOLUTION` collision, prompt the user inline (as described in step 3 above)
3. For each `DESCRIPTION CONFLICT`, prompt inline (step 4)
4. Once all resolutions gathered, call `promote --merge` for real with a `--resolutions <json-file>` flag carrying the user's decisions
5. New CLI flag on `promote`: `--resolutions PATH` reads a JSON map of slug-or-description-key → choice

This keeps the merge step interactive and review-driven without forcing the user out of the chat.

---

## Implementation Steps

### Step 1 — Refactor existing code
- Move `Backup/Promoted Skills/YYYY-MM-DD HHMM/` → `Backup/Promoted Skills/YYYY-MM-DD HHMMSS/` everywhere (writer, plan, docs)
- Extract `_validate_skill_folder` core into `validate_skill_folder_at(path)` so it's reusable

### Step 2 — Build `Source/merger.py`
- `SkillSnapshot.from_disk(path) -> SkillSnapshot` — load existing skill
- `compute_merge(live, staging, allow_force_collision: bool) -> MergeResult` — pure logic
- Unit-testable in isolation

### Step 3 — Wire merge into `writer.promote()`
- Add `--merge` arg in `forge.py`
- In `promote()`: detect collision, branch into `_promote_merge()` when `--merge`
- `_promote_merge()` calls `merger.compute_merge`, runs post-merge validation, executes via atomic rename

### Step 4 — Resolutions file format
- JSON map written by the `/forge` skill after the chat conversation
- `{"collisions": {"slug": "staging|live|rename"}, "description": "use staging|use live|<custom text>"}`
- Read by `--resolutions PATH`

### Step 5 — Update `Commands/forge.md`
- New section: "If merge promotion has conflicts, run a sub-dialog in chat"
- Parses the dry-run report's structured output (add a `--report-json` mode to dry-run for easy parsing)

### Step 6 — Test cases
1. New skill (no live conflict) + `--merge` → behaves identical to plain promote
2. Existing skill, no slug collisions, identical description → minor version bump, refs union
3. Existing skill, slug collisions, no `--force` → exits with NEEDS RESOLUTION
4. Existing skill, slug collisions, `--force` → silently picks staging
5. Description differs → prompts in chat
6. Description identical → no prompt
7. Dry-run produces full report, writes nothing
8. Post-merge validation catches a Related: pointing to a removed slug

### Step 7 — Verification
Re-extract `blender-lighting` from a different (real or synthetic) transcript so the proposal has 3 overlapping refs and 4 new ones. Promote with `--merge`. Verify:
- Backup exists at `Backup/Promoted Skills/<timestamp>/blender-lighting/`
- `~/.claude/skills/blender-lighting/references/` contains the union (no duplicates by slug)
- SKILL.md description was updated (via chat flow)
- Version bumped 0.1.0 → 0.2.0
- Post-merge validate passes

---

## Risks

1. **Description merging via chat could go wrong** — Claude proposes a bad merged description that loses topic keywords. Mitigated by showing the diff in chat before accepting; user can edit inline.
2. **Atomic rename on Windows can fail under Dropbox lock** — already saw this with the venv. Fallback: copy → verify → delete-original, in a transaction-like wrapper. Acceptable v1 to accept the small race window.
3. **Backups accumulate fast** — every merge adds another backup folder. No cleanup yet. Same as today's `--force` behaviour; we can add `forge gc-backups --older-than 30d` later.
4. **Reference content collision wording is subtle** — "different content" needs a real byte-by-byte comparison (after normalising line endings) to avoid false positives from Dropbox CRLF flips.

---

## Open Questions for Codex / for Sam

1. **Default behaviour:** should `--merge` be opt-in (this plan) or eventually become the default for collision handling, with `--no-merge` going back to skip-or-overwrite? Lean opt-in for v1 to avoid surprising the user.

2. **Description merging:** is "ask Claude in chat for a merged version, max 600 chars" the right approach, or should we be more conservative (always keep the existing description unless the user explicitly says "replace")?

3. **Rename collision resolution:** when a user picks `rename`, what slug do we generate? Append `-v2` blindly? Look at existing slugs and pick the next free integer? Or always prompt the user for the new slug name?

4. **Version semantics:** is the major/minor/patch split useful for skills, or is a single integer counter (`v1`, `v2`, `v3`) clearer? Skills don't have an API surface that breaks compatibility, so semver might be overkill.

5. **Cross-skill merge later:** worth designing now to leave room, or YAGNI? My instinct: YAGNI, but flag it as a known future direction.

---

## Estimated Effort

- Step 1 (refactor): 15 min
- Step 2 (`merger.py`): 45 min
- Step 3 (wire into `writer.py`): 30 min
- Step 4 (resolutions file): 15 min
- Step 5 (`Commands/forge.md` update): 20 min
- Step 6 (tests): 30 min
- Step 7 (verification): 15 min

**Total: ~2 hours 30 minutes.** Plus iteration time on Codex/Sam review.

This is a real feature, not a 30-minute add — partly because the post-merge validation and the chat-orchestrated conflict resolution are doing real work.
