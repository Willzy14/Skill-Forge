"""Skill Forge — merger.

Pure merge logic. No I/O. Given two SkillSnapshot instances (live + staging),
returns a MergeResult describing what the merged skill would look like and
which resolutions still need user input.

writer.py is the only caller and is responsible for:
  - loading snapshots from disk (via snapshot.py)
  - applying resolutions from the resolutions JSON or chat
  - writing the merged result back to disk
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from snapshot import ReferenceFile, SkillSnapshot

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_SLUG_LEN = 60


@dataclass
class Collision:
    """A reference slug that exists in both live and staging with different content."""
    slug: str
    live_ref: ReferenceFile
    staging_ref: ReferenceFile
    resolution: str | None = None      # "staging" | "live" | "rename:<slug>" | None

    @property
    def needs_resolution(self) -> bool:
        return self.resolution is None


@dataclass
class MergeResult:
    """The intended outcome of merging live + staging for a single skill."""
    name: str
    # Description resolution
    description_action: str            # "kept" | "use_staging" | "use_live" | "custom" | "needs-resolution"
    live_description: str
    staging_description: str
    final_description: str | None      # set once resolved; None while pending
    staging_is_broader: bool           # heuristic hint for the chat flow
    # Reference resolution
    references_kept: list[str] = field(default_factory=list)
    references_added: list[str] = field(default_factory=list)
    references_collided: list[Collision] = field(default_factory=list)
    # Bookkeeping
    new_version: int = 1
    backup_path_hint: str = ""         # filled by writer with a planned path

    @property
    def needs_user_input(self) -> bool:
        if self.description_action == "needs-resolution":
            return True
        return any(c.needs_resolution for c in self.references_collided)


def compute_merge(
    live: SkillSnapshot,
    staging: SkillSnapshot,
    force_staging_on_collision: bool = False,
) -> MergeResult:
    """Classify the merge. Pure: no I/O, no side effects."""
    if live.name != staging.name:
        raise ValueError(
            f"compute_merge requires same skill name, got '{live.name}' vs '{staging.name}'"
        )

    # ---- References classification ----
    kept: list[str] = []
    added: list[str] = []
    collided: list[Collision] = []

    all_slugs = sorted(set(live.references) | set(staging.references))
    for slug in all_slugs:
        live_ref = live.references.get(slug)
        staging_ref = staging.references.get(slug)
        if live_ref and not staging_ref:
            kept.append(slug)
        elif staging_ref and not live_ref:
            added.append(slug)
        else:
            # In both — compare normalised bytes
            assert live_ref is not None and staging_ref is not None
            if live_ref.normalised_bytes == staging_ref.normalised_bytes:
                kept.append(slug)
            else:
                resolution = "staging" if force_staging_on_collision else None
                collided.append(
                    Collision(
                        slug=slug,
                        live_ref=live_ref,
                        staging_ref=staging_ref,
                        resolution=resolution,
                    )
                )

    # ---- Description classification ----
    live_desc = _oneline(live.description)
    staging_desc = _oneline(staging.description)
    staging_is_broader = _staging_is_broader(live_desc, staging_desc)

    if live_desc == staging_desc:
        description_action = "kept"
        final_description = live_desc
    elif force_staging_on_collision:
        # --force resolves description too
        description_action = "use_staging"
        final_description = staging_desc
    else:
        description_action = "needs-resolution"
        final_description = None

    # ---- Version bump ----
    # Only bump if something actually changes. No-op merges (byte-identical refs
    # + identical description) keep the live version untouched.
    has_changes = bool(added) or bool(collided) or description_action != "kept"
    if has_changes:
        new_version = max(live.version, staging.version) + 1
    else:
        new_version = live.version

    return MergeResult(
        name=live.name,
        description_action=description_action,
        live_description=live_desc,
        staging_description=staging_desc,
        final_description=final_description,
        staging_is_broader=staging_is_broader,
        references_kept=kept,
        references_added=added,
        references_collided=collided,
        new_version=new_version,
    )


def is_valid_slug(slug: str) -> bool:
    if len(slug) > _MAX_SLUG_LEN:
        return False
    return _SLUG_RE.match(slug) is not None


def suggest_rename_slug(original: str, existing: Iterable[str]) -> str:
    """Suggest '<original>-v2', '<original>-v3' etc until one is free."""
    existing = set(existing)
    i = 2
    while True:
        candidate = f"{original}-v{i}"
        if candidate not in existing:
            return candidate
        i += 1


def apply_resolutions(
    result: MergeResult,
    collision_resolutions: dict[str, str],
    description_resolution: dict | None,
) -> None:
    """Mutate `result` to apply the user's resolutions.

    Raises ValueError on:
      - missing resolution for any collision
      - invalid custom rename slug
      - missing description resolution when needs-resolution
      - rename target colliding with an existing slug
    """
    # Apply collision resolutions
    final_slug_set = (
        set(result.references_kept)
        | set(result.references_added)
        | {c.slug for c in result.references_collided}
    )
    rename_targets: set[str] = set()

    for c in result.references_collided:
        if c.resolution is not None:
            # Already set (e.g. by --force)
            continue
        choice = collision_resolutions.get(c.slug)
        if choice is None:
            raise ValueError(f"missing resolution for collision: {c.slug}")
        if choice == "staging" or choice == "live":
            c.resolution = choice
        elif choice.startswith("rename:"):
            new_slug = choice.split(":", 1)[1].strip()
            if not is_valid_slug(new_slug):
                raise ValueError(
                    f"invalid rename slug '{new_slug}' for collision '{c.slug}' "
                    f"(must match ^[a-z0-9]+(-[a-z0-9]+)*$, max {_MAX_SLUG_LEN} chars)"
                )
            if new_slug in final_slug_set or new_slug in rename_targets:
                raise ValueError(
                    f"rename target '{new_slug}' collides with an existing slug"
                )
            c.resolution = choice
            rename_targets.add(new_slug)
        else:
            raise ValueError(
                f"unknown resolution '{choice}' for collision '{c.slug}' "
                f"(expected: 'staging', 'live', or 'rename:<slug>')"
            )

    # Apply description resolution
    if result.description_action == "needs-resolution":
        if description_resolution is None:
            raise ValueError("missing description resolution")
        action = description_resolution.get("action")
        if action == "use_staging":
            result.final_description = result.staging_description
            result.description_action = "use_staging"
        elif action == "use_live":
            result.final_description = result.live_description
            result.description_action = "use_live"
        elif action == "custom":
            value = description_resolution.get("value", "")
            value = _oneline(value)
            if not value:
                raise ValueError("description resolution 'custom' requires non-empty value")
            result.final_description = value
            result.description_action = "custom"
        else:
            raise ValueError(
                f"unknown description action '{action}' "
                f"(expected: 'use_staging', 'use_live', 'custom')"
            )


def materialize_merged_snapshot(
    result: MergeResult,
    live: SkillSnapshot,
    staging: SkillSnapshot,
) -> SkillSnapshot:
    """Build the final merged SkillSnapshot from resolved MergeResult + sources.

    Requires `result.needs_user_input == False`. Caller responsible for
    `apply_resolutions` first.
    """
    if result.needs_user_input:
        raise ValueError(
            "materialize_merged_snapshot called before all resolutions applied"
        )
    if result.final_description is None:
        raise ValueError("final_description not set")

    references: dict[str, ReferenceFile] = {}

    # Kept refs come from whichever side had them
    for slug in result.references_kept:
        if slug in live.references:
            references[slug] = live.references[slug]
        else:
            references[slug] = staging.references[slug]

    # Added refs come from staging
    for slug in result.references_added:
        references[slug] = staging.references[slug]

    # Collision-resolved refs
    for c in result.references_collided:
        if c.resolution == "staging":
            references[c.slug] = c.staging_ref
        elif c.resolution == "live":
            references[c.slug] = c.live_ref
        elif c.resolution and c.resolution.startswith("rename:"):
            new_slug = c.resolution.split(":", 1)[1].strip()
            # Keep live under its original slug, add staging under the new one
            references[c.slug] = c.live_ref
            renamed = ReferenceFile(
                slug=new_slug,
                content_bytes=c.staging_ref.content_bytes,
                body_text=c.staging_ref.body_text,
            )
            references[new_slug] = renamed
        else:
            raise ValueError(f"unresolved collision: {c.slug}")

    return SkillSnapshot(
        name=result.name,
        description=result.final_description,
        version=result.new_version,
        references=references,
        extra_frontmatter=dict(live.extra_frontmatter),  # preserve any custom keys
    )


# ---------- helpers ----------

def _oneline(text: str) -> str:
    return " ".join(text.split())


_WORD_RE = re.compile(r"[a-z0-9][a-z0-9-]+")


def _staging_is_broader(live_desc: str, staging_desc: str) -> bool:
    """Heuristic: every meaningful word in live appears in staging."""
    if not live_desc or not staging_desc:
        return False
    live_words = set(_WORD_RE.findall(live_desc.lower()))
    staging_words = set(_WORD_RE.findall(staging_desc.lower()))
    # Filter common stop words
    stop = {
        "this", "skill", "should", "be", "used", "when", "the", "and", "for",
        "of", "in", "to", "a", "any", "is", "or", "with", "on", "by", "an",
    }
    live_words -= stop
    if not live_words:
        return False
    missing = live_words - staging_words
    # Staging is "clearly broader" if it covers all live keywords AND adds new ones
    return len(missing) == 0 and bool(staging_words - live_words)
