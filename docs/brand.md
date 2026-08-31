# CoDev brand

CoDev should feel like a dependable engineering instrument: clear, quiet,
friendly, and precise. The identity takes inspiration from the restraint and
utility of mature developer tools without copying another company's marks,
typefaces, or product language.

## Name and message

- **Name:** CoDev
- **Descriptor:** Human-guided AI software delivery
- **Short promise:** Keep intent, code, evidence, and release on one visible path.
- **CLI:** `codev`
- **Package:** `open-codev-workflow`

Use “CoDev” as a proper noun. Avoid names such as “CoDev AI” or “CoDev
Agent Platform”; the product is a workflow kit and distribution tool, not an AI
model or autonomous engineering service.

## Visual system

The mark is a route through four checkpoints: Understand, Build, Review, and
Ship. Rounded geometry makes it approachable; the light Porcelain field keeps
the route legible as one self-contained badge on both light and dark
surfaces, without needing a separate dark-mode variant.

Surfaces are near-monochrome per theme rather than a fixed light/dark pair:
light mode runs white shading into Porcelain and Pastel Orange, warm in feel;
dark mode runs black shading into cool, blue-leaning gray — not a brown
inversion of the light palette. Pastel Orange stays the one accent in both.

| Token | Value | Purpose |
|---|---|---|
| Ink | `#14213D` | Dark ring accents in the mark |
| Pastel Orange | `#E3996A` | Primary accent — navigation, links, buttons |
| Indigo | `#5B5FEF` | Understand |
| Teal | `#008F7A` | Build and positive progress |
| Amber | `#F0A202` | Review and attention |
| Coral | `#F45B69` | Ship, stop, and authority boundary |
| Porcelain | `#FAF4EC` | Light surfaces, shading toward white |

Use [Onest](https://fonts.google.com/specimen/Onest) (SIL Open Font License,
distributed via Google Fonts) for documentation and interfaces, falling back
to the platform's system sans-serif when it isn't loaded. Use the user's
configured monospace font for commands and code. Do not bundle proprietary
fonts — Onest is open-licensed and freely embeddable, unlike a vendor's own
in-house product typeface.

## Writing system

- Lead with the outcome.
- Prefer short verbs and familiar engineering terms.
- Say what CoDev will preserve before asking for action.
- Distinguish errors, conflicts, and warnings precisely.
- Never describe an automated check as an approval.
- Never imply autonomous operation or guaranteed correctness.

Examples:

```text
Installed 29 managed files. Existing repository instructions were preserved.
Update stopped: 1 managed file has local changes.
No drift found. CoDev 0.1.1 is healthy.
```

The SVG asset is original and may be recolored for monochrome contexts as long
as the route and four-checkpoint form remain recognizable.
