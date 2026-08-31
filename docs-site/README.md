# CoDev docs site

Public documentation site, built with [Astro](https://astro.build) +
[Starlight](https://starlight.astro.build). Deploys to GitHub Pages at
https://urban233.github.io/CoDev/ via
[`.github/workflows/deploy-docs.yml`](../.github/workflows/deploy-docs.yml) on every push
to `main` that touches `docs-site/`.

This is intentionally **outside the Bazel graph** — it's a standalone Node project with
its own CI job, not wired into `bazel build //...`. See
[`docs/architecture.md`](../docs/architecture.md) and the Bazel migration design doc for
why the rest of the repo builds through Bazel; this directory doesn't need Bazel's
hermeticity/caching to justify the added ceremony.

Source pages live under `src/content/docs/`. This mirrors a curated, user-facing subset of
`docs/` — install/adoption/CLI/architecture. ADRs, feature briefs/designs, and plans stay
internal to the repository (linked to from here via GitHub, not migrated onto the site).

## Local development

```shell
npm install
npm run dev       # http://localhost:4321/CoDev/
```

## Build

```shell
npm run build      # outputs to dist/
npm run preview    # serve the production build locally
```

## Theming

`src/styles/custom.css` overrides Starlight's default palette/type with CoDev's own brand
tokens (`docs/brand.md`) — system sans-serif fonts only, no bundled proprietary typeface,
CoDev's indigo/ink palette instead of any other product's. The page structure (left nav,
content, right "On this page" TOC, top search) is Starlight's own default.
