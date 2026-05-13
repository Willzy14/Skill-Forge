# Skill Extraction Prompt

You are extracting reusable, transferable techniques from a tutorial transcript and turning them into Claude skills. Your output will be reviewed by a human and, if approved, become live skills that Claude auto-invokes in any future session.

**The user's goal:** when shown a reference image of (e.g.) a concrete dam, Claude should think *"I have a skill for realistic concrete"*. When shown a grass field, *"I have a skill for scatter-on-surface with weight paint masking."* Same skills must apply across many subjects — dam, bridge, cliff, plaza, hangar.

So extract **techniques**, not **recipes**. The donut is the worked example; the techniques are the value.

---

## Core rules

### What counts as a skill (and what doesn't)

**YES:** A transferable technique that could apply to many subjects.
- "Sun lamps in Blender: only rotation matters, position is ignored"
- "Subsurface scattering radius should be 1,1,1 for non-character organics"
- "Weight paint a vertex group, then Distribution Mask (not Density) to control scatter placement"

**NO:** Donut-specific or recipe-style instructions.
- "Match the sprinkle colour to the icing" — recipe, not transferable
- "Drop radius to 0.057" — magic number, not transferable
- "I prefer the long sprinkles over round ones" — preference, not technique

### Hierarchy

Group related techniques under **overview clusters** (these become top-level skills). Each cluster gets a handful of **granular references** (these become files inside the cluster's `references/` folder).

Aim for:
- 1–2 overview clusters per video
- 5–15 granular references per cluster (target ~6–10)

**Never** put every granular technique at the top level. Discovery breaks if Claude has 80 sibling skills competing for attention. Always nest.

### Naming

- Skill names: lowercase, hyphenated, domain-prefixed. `blender-lighting`, `blender-materials`, `mixing-low-end-control`.
- Reference slugs: action-phrase. `sun-lamp-rotation-only`, `weight-paint-distribution-mask`, `kelvin-time-of-day`. Never `lighting-tip-3` or `useful-thing`.

### Descriptions

The `description:` field on each skill is what Claude reads to decide whether to invoke it. Be precise about both **what the skill does** and **when it applies**.

- Start with: `This skill should be used when`
- 60–600 characters
- List the major sub-techniques inline so semantic matches surface across them
- Name the situations where it applies (outdoor scenes, dams, bridges, time-of-day work)

**Good:**
> This skill should be used when working on lighting setups in Blender — three-light photographic rigs, sun lamp behaviour, shadow softness via light radius, Kelvin colour temperature for time of day, EEVEE light probes vs Cycles path tracing, blocker planes for fake window shadows. Apply when lighting any 3D scene, especially photorealistic outdoor work (dams, bridges, landscapes) or time-of-day cinematography.

**Bad:**
> This skill is useful for lighting. (too vague)
> This skill is for the donut tutorial finale where Andrew Price discusses lighting setups. (subject-specific)

### Source attribution

Every reference MUST have:
- `source_video_id` (e.g. `WobATxh3i-g`) — exactly the video ID from the transcript metadata
- `timestamp` in `HH:MM:SS` format — approximate moment the technique appears in the transcript

### Filter rules

Skip:
- Channel intros, outros, sign-offs
- Sponsor reads, "buy my course" pitches
- "What's coming next time" tease
- Andrew Price talking about his cat / Australian childhood / etc
- Pure UI navigation that's identical across all tutorials (how to orbit the viewport, where the X key is, etc) — except when teaching a non-obvious workflow shortcut

### Cross-references

When two references complement each other, list each in the other's `related` array. Use the slug (no `.md`, no path).

---

## Output schema — `proposed_skills.json`

```json
{
  "schema_version": 1,
  "source": {
    "transcript_path": "<copy from EXTRACT_REQUEST.md>",
    "video_id": "<from request>",
    "title": "<from request>",
    "channel": "<from request>",
    "url": "<from request>"
  },
  "skills": [
    {
      "name": "blender-lighting",
      "description": "This skill should be used when working on lighting setups in Blender — three-light photographic rigs, sun lamp behaviour, shadow softness via light radius, Kelvin colour temperature for time of day, EEVEE light probes vs Cycles path tracing, blocker planes for fake window shadows. Apply when lighting any 3D scene, especially photorealistic outdoor work (dams, bridges, landscapes) or time-of-day cinematography.",
      "version": "0.1.0",
      "references": [
        {
          "slug": "sun-lamp-rotation-only",
          "source_video_id": "WobATxh3i-g",
          "timestamp": "00:03:30",
          "technique": "Sun lamps simulate parallel rays from a distant source. Position has zero effect — only rotation matters. Set time-of-day angle without worrying about where the lamp object sits in the scene.",
          "when_to_apply": "Any outdoor scene with directional sunlight: sunrise, midday, sunset, overcast (combine with sky-tinted point lamp).",
          "settings": [
            "Kelvin 2500K-3500K for sunrise / golden hour",
            "Kelvin 5500K for noon daylight",
            "Kelvin 7000K+ for overcast / blue hour",
            "Power around 5-10 W/m^2"
          ],
          "related": ["light-radius-shadow-softness", "kelvin-time-of-day"]
        }
      ]
    }
  ]
}
```

### Required fields

Every skill: `name`, `description`, `references`.
Every reference: `slug`, `source_video_id`, `timestamp`, `technique`, `when_to_apply`.

Optional: `version` (defaults to `0.1.0`), `settings`, `related`.

### Constraints

- `name` and `slug`: lowercase, hyphenated, ASCII (regex `^[a-z0-9]+(?:-[a-z0-9]+)*$`)
- `timestamp`: `HH:MM:SS` exactly
- Reference slugs must be **unique across all skills** in this proposal
- Within a skill, references are listed in the order Claude should read them

---

## Output schema — `PROPOSED_SKILLS.md`

Human review surface. Mirror the JSON in human-readable form, with the JSON embedded as the final fenced code block for round-trip safety.

```markdown
# Proposed Skills — <video title> [<video_id>]

Source: <video title>
Channel: <channel>
URL: <url>

---

## Skill: <skill-name>

Name: <skill-name>
Description: <description text>

References:
- <slug-1>
- <slug-2>
- ...

### Reference: <slug>

Source: <channel> — <title> [<video_id>]
Timestamp: <HH:MM:SS>

Technique:
<technique paragraph>

When to apply:
<when-to-apply paragraph>

Settings:
- <setting 1>
- <setting 2>

Related: <slug-a>, <slug-b>

### Reference: <next-slug>
...

---

## Skill: <next-skill-name>
...

---

```json
{
  ...full proposed_skills.json content here...
}
```
```

---

## Few-shot example — Donut Tutorial Finale

To calibrate granularity and depth, here's a fully-worked example for one cluster from the donut lighting finale (video ID `WobATxh3i-g`).

```json
{
  "schema_version": 1,
  "source": {
    "transcript_path": "F:\\...\\Transcripts\\Blender Guru\\The Basics of Lighting and Rendering in Blender (Donut Finale) [WobATxh3i-g].md",
    "video_id": "WobATxh3i-g",
    "title": "The Basics of Lighting and Rendering in Blender (Donut Finale)",
    "channel": "Blender Guru",
    "url": "https://www.youtube.com/watch?v=WobATxh3i-g"
  },
  "skills": [
    {
      "name": "blender-lighting",
      "description": "This skill should be used when working on lighting setups in Blender — three-light photographic rigs (sun + sky + bounce), sun lamp behaviour, shadow softness via light radius, Kelvin colour temperature for time of day, working lights in isolation, blocker planes for fake window shadows. Apply when lighting any 3D scene, especially photorealistic outdoor or interior work, dams, bridges, landscapes, or time-of-day cinematography.",
      "version": "0.1.0",
      "references": [
        {
          "slug": "sun-lamp-rotation-only",
          "source_video_id": "WobATxh3i-g",
          "timestamp": "00:03:30",
          "technique": "Sun lamps in Blender simulate parallel rays from a distant source. Their world position has zero effect on the render — only the rotation matters. Use this to set time-of-day angle freely without worrying about where the lamp object lives in the scene hierarchy.",
          "when_to_apply": "Any outdoor scene with directional sunlight. Sunrise, midday, sunset, overcast (combine with a sky-tinted point lamp). Also good for any 'practically infinite' light source: stadium floods at distance, moonlight.",
          "settings": [
            "Kelvin 2500K-3500K for sunrise / golden hour",
            "Kelvin 5500K for noon daylight",
            "Kelvin 7000K+ for overcast or blue-hour",
            "Power around 5-10 W/m^2 for daylight"
          ],
          "related": ["light-radius-shadow-softness", "kelvin-time-of-day", "three-light-photographic-setup"]
        },
        {
          "slug": "light-radius-shadow-softness",
          "source_video_id": "WobATxh3i-g",
          "timestamp": "00:11:20",
          "technique": "A lamp's radius controls the softness of its shadows. Sharp shadow (small radius) reveals surface detail and texture. Soft shadow (large radius) reveals form and silhouette. This is one of the most underused values in Blender lighting and has a huge effect on the final feel.",
          "when_to_apply": "Use small radius when showcasing material detail (textures, sprinkles, micro-surface). Use large radius for overcast / soft cinematic looks, or when the implied light source is large (sky dome, big window).",
          "settings": [
            "Radius 0.01-0.05 for detail-revealing harsh shadows",
            "Radius 1-5 for soft overcast feel",
            "Radius 10+ for sky-dome-style fill light"
          ],
          "related": ["sun-lamp-rotation-only", "work-lights-in-isolation"]
        },
        {
          "slug": "kelvin-time-of-day",
          "source_video_id": "WobATxh3i-g",
          "timestamp": "00:05:10",
          "technique": "Blender lamps support a Kelvin colour temperature input. Use it to set time-of-day mood without manually balancing RGB. Lower Kelvin = warmer (sunrise, candlelight); higher Kelvin = cooler (overcast, blue hour). Combine warm key with cool fill for natural-feeling sunlight + skylight interplay.",
          "when_to_apply": "Any time-of-day scene. Mandatory whenever you want a consistent cinematographic mood without colour-grading in post.",
          "settings": [
            "1800K candle / firelight",
            "2500-3500K sunrise / sunset / golden hour",
            "4500-5500K daylight",
            "6500K cool daylight / shaded outdoor",
            "7500-10000K overcast / blue hour / moonlight"
          ],
          "related": ["sun-lamp-rotation-only", "three-light-photographic-setup"]
        },
        {
          "slug": "work-lights-in-isolation",
          "source_video_id": "WobATxh3i-g",
          "timestamp": "00:08:45",
          "technique": "When building a multi-light scene, solo each lamp in turn and check it in isolation before adding the next. This forces a conscious purpose for every light — key, fill, bounce, rim — and prevents the common beginner mistake of stacking lights until 'it looks bright' without any of them earning their place.",
          "when_to_apply": "Always, when building any multi-light setup. Especially valuable for three-point setups and exterior scenes with sun + sky + bounce.",
          "settings": [],
          "related": ["three-light-photographic-setup", "light-radius-shadow-softness"]
        },
        {
          "slug": "three-light-photographic-setup",
          "source_video_id": "WobATxh3i-g",
          "timestamp": "00:14:00",
          "technique": "Photographic three-light setup adapted for 3D: 1) Sun lamp as key (directional, warm Kelvin, time-of-day rotation). 2) Sky-tinted point lamp as fill (cool Kelvin, large radius, positioned to imply sky-dome). 3) Bounce point lamp as low-intensity reflection from off-screen surfaces (neutral Kelvin, very large radius). Each contributes a distinct role; together they avoid the 'flashlight in a void' look.",
          "when_to_apply": "Any scene where realism matters more than stylisation. Especially exterior shots (dams, bridges, landscapes), interiors near windows, golden-hour or blue-hour cinematography.",
          "settings": [
            "Key: Sun lamp, 5-10 W/m^2, Kelvin per time-of-day, radius for desired shadow softness",
            "Fill: Point lamp, cool Kelvin (~7000K), large radius (5-15), positioned high",
            "Bounce: Point lamp, neutral Kelvin, very large radius (10-25), low power, positioned where an off-screen reflective surface would be"
          ],
          "related": ["sun-lamp-rotation-only", "kelvin-time-of-day", "work-lights-in-isolation"]
        },
        {
          "slug": "blocker-planes-for-fake-windows",
          "source_video_id": "WobATxh3i-g",
          "timestamp": "00:09:30",
          "technique": "To imply offscreen architecture (windows, doorways, blinds) without modelling it, place simple planes between the sun lamp and the scene. They cast shadows that read as window mullions or curtains in the final frame. Cheap, fast, infinitely tweakable.",
          "when_to_apply": "Interior scenes near implied windows. Any scene where sunlight should be 'shaped' by offscreen geometry. Strongly recommended for cafe / studio / room interiors.",
          "settings": [
            "Plane scale ~ 5x scene width",
            "Position between sun and subject",
            "Rotation tilts the shadow shape (wide vs narrow slashes of light)"
          ],
          "related": ["sun-lamp-rotation-only", "light-radius-shadow-softness"]
        }
      ]
    }
  ]
}
```

Note: this example has only ONE skill cluster. A real extraction from the same finale would also produce `blender-rendering` (EEVEE vs Cycles, light probes, jitter shadows, GPU device selection, denoising, depth of field) as a second cluster. Aim for that ratio.

---

## Final checklist before writing your output

- [ ] At least one overview skill cluster
- [ ] Each cluster has 5–15 references (target ~6–10)
- [ ] No top-level skill is a single technique (always nest)
- [ ] No reference is donut/sprinkle/icing-specific
- [ ] Each `description:` starts with "This skill should be used when" and is 60–600 chars
- [ ] Each reference has a real HH:MM:SS timestamp from the transcript
- [ ] All slugs are valid (`^[a-z0-9]+(?:-[a-z0-9]+)*$`) and unique across the proposal
- [ ] Both `proposed_skills.json` and `PROPOSED_SKILLS.md` written to the staging dir
- [ ] The MD ends with the same JSON in a fenced ```json block
