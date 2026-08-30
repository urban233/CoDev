# ADR-0030: Claude Code adapter, and settings.json/hooks as a new bundled-content category

**Status:** Proposed
**Date:** 2026-08-30
**Owner:** CoDev maintainers
**Related design:** [../features/claude-code/design.md](../features/claude-code/design.md)

## Context

CoDev supports four agent platforms (Codex, Junie, OpenCode, Antigravity) as
hand-maintained, parallel per-platform bundle subtrees sharing one installer
-- not one source rendered four ways (`adapter.py`'s own docstring calls the
verification layer "a second line of defense... not a substitute for
eventually rendering adapters from one config source"). Claude Code,
Anthropic's own first-party CLI, had no adapter at all.

Two decisions here are durable enough to outlive the design doc and worth
settling once:

1. Does adding a fifth platform justify finally rendering adapters from one
   config source, or does it just add a fifth hand-maintained tree following
   the existing pattern?
2. Claude Code is the first platform whose native config surface
   (`.claude/settings.json`, hooks) can structurally gate *when* an agent is
   allowed to edit, not just *what* it's allowed to touch. Does CoDev use
   that, and if so, how strongly?

A compatibility spike against the real, installed Claude Code CLI (v2.1.251,
commit `37534ac596d8`, 2026-08-30 -- see design.md's Phase 0) also settled a
question that changes what `.claude/CLAUDE.md` needs to contain: Claude Code
hardcodes discovery of both `CLAUDE.md` and `AGENTS.md`, unconditionally
("Claude Code hardcodes CLAUDE.md / AGENTS.md discovery" -- found in the
CLI's own `claude import codex` migration messaging).

## Decision

- **A fifth hand-maintained bundle subtree, not a rendered-from-one-source
  refactor.** `.claude/agents/*.md` joins `.codex/agents/*.toml`,
  `.opencode/agents/*.md`, and `.junie/agents/*.md` as its own tree, sharing
  only the same body prose (already identical across all four prior
  platforms) and the same `_render_code_audit_agent` templating mechanism
  for `code-audit`/`code-audit-gate`. Per prior guidance, the existing
  adapter pattern is not a precedent to avoid for *this* addition -- it is
  the addition. A real rendering abstraction stays deferred until a second
  consumer actually needs one, the same posture ADR-0026 took for engine
  wrappers.
- **`.claude/settings.json` + `.claude/hooks/require_plan.py` is a new
  bundled-content category**, distinct from every existing agent-role file:
  `permissions.defaultMode: "plan"` defaults every session into Plan Mode,
  and a `PreToolUse` hook pauses for human confirmation
  (`permissionDecision: "ask"`, deliberately never `"deny"`) before the
  first source edit, or the first repository-mutating git command, of a
  session when no design/plan document can be found for the active branch.
  Two independent layers, not one: the settings default is a native,
  low-effort nudge with a known bypass (`Shift+Tab`); the hook is the real
  checkpoint that survives that bypass. "Ask" rather than "deny" is
  deliberate -- a hard block would punish legitimate small, spec-free fixes
  and contradict CoDev's own principle that trivial changes don't need a
  full brief/design cycle. The spec-exists check itself is two layers: an
  exact match against the active task's own recorded plan
  (`docs/codev/task/<task-id>/implementation-plan.md`, `<task-id>` derived
  from a `codev git branch`-created branch's own `codev/<task-id>` naming)
  when that convention applies, falling back to a coarser branch-name
  substring match against `docs/features/*/design.md` for planning work
  that predates a task. The gated `Bash` command list
  (`git commit`/`push`/`merge`/`reset`/`checkout`/`clean`/`rebase`,
  `rm -rf`) is deliberately the same one ADR-0002 already denies outright
  for OpenCode's `builder`, not a newly invented list.
- **`.claude/CLAUDE.md` is a short, Claude-Code-specific supplement, not a
  copy or an import of the shared contract.** Since Claude Code already
  reads `AGENTS.md` natively and unconditionally, and CoDev already
  installs an `AGENTS.md` managed block for every platform, Claude Code
  picks up CoDev's shared contract for free. `.claude/CLAUDE.md` only adds
  what AGENTS.md doesn't cover: where Claude-Code-specific role
  subagents/skills/commands live, and a pointer to the guardrail above.
- **Skills are mirrored into `.claude/skills/`, not referenced in place.**
  Unlike Antigravity, which shares CoDev's `.agents/skills/` directory
  directly, Claude Code hardcodes `.claude/skills/*/SKILL.md` as its only
  skill-discovery path (confirmed by inspecting the shipped binary; no
  configurable alternative exists). `_bundle_files()` copies every already
  language-filtered file under `.agents/skills/` to a parallel
  `.claude/skills/` path at install time, so there is exactly one
  hand-maintained skill source, not two.

## Alternatives considered

- **Render all five (or four) platforms' agent files from one shared
  template/config source now:** rejected for this change. Nothing in this
  codebase currently renders adapters from one source; retrofitting that
  while also adding a fifth platform conflates two unrelated, both
  nontrivial changes. `adapter.py`'s docstring already names this as a
  future direction, not a blocking prerequisite.
- **Hard `permissionDecision: "deny"` instead of `"ask"` for the plan-first
  hook:** rejected as the default. Considered and documented as a
  stricter opt-in variant in design.md's Alternatives table; the false-positive
  cost on legitimate small changes outweighs the marginal enforcement gain
  for a guardrail that already has a real, working softer form.
  Plan-mode-only, no hook at all: rejected too -- bypassable with one
  keystroke and no checkpoint at all once bypassed.
- **`.claude/CLAUDE.md` importing `.codev/for-ai/ai-agent-guidelines.md` via
  Claude Code's `@import` syntax:** this was the original design before the
  compatibility spike. Superseded once the spike showed `AGENTS.md` is
  already natively read -- importing a second shared-contract file would
  have been redundant and added an untested dependency on import resolution
  for no benefit.
- **Pointing Claude Code at `.agents/skills/` directly, matching
  Antigravity's pattern:** ruled out by the same spike -- no such
  configurable path exists for Claude Code; `.claude/skills/*/SKILL.md` is
  hardcoded.

## Consequences

- A sixth platform, if one is ever added, most likely becomes a sixth
  hand-maintained tree following this same pattern, not a forcing function
  for a rendering abstraction on its own -- that decision stays deferred
  until a concrete second consumer of one makes it a real simplification
  rather than a speculative one.
- CoDev's bundle now has one file category (`.claude/settings.json` and its
  hook) that is genuinely new in kind, not just in platform: it changes
  *when* Claude Code may edit, not only what it is allowed to touch. Any
  future guardrail work for other platforms should treat this as the
  reference implementation, not reinvent the ask-vs-deny tradeoff from
  scratch.
- `.claude/skills/` is a second physical copy of every shared skill's
  content, generated at install time from the same bundle source, not
  hand-maintained twice. A change to a shared skill's `SKILL.md` needs no
  Claude-specific follow-up; the copy step picks it up automatically on the
  next install or update.
- `scripts/verify_claude_code_compat.py`, scheduled and release-gated in CI,
  is the durable answer to "how does anyone find out Claude Code's surface
  drifted without re-running the whole Phase 0 spike by hand" -- it checks
  literal marker presence in the real, currently-published CLI's shipped
  binary, not runtime behavior, so a passing run is evidence this adapter's
  *assumptions* still hold, not proof the adapter still *works* end to end.
  Treat a failure as "go re-run Phase 0," not as a false alarm to silence.
- `pyproject.toml`'s `[tool.setuptools.package-data]` needs its own new
  glob line for any future bundled `.claude/**` file type (`.json`, `.py`)
  that doesn't already match an existing pattern -- the Bazel build and the
  installer's runtime walk do not need this, only the setuptools sdist
  build does. This asymmetry already existed before this change; it is not
  new, but it is easy to miss when only checked against the Bazel or
  runtime behavior.

## Revisit when

A second platform's native config surface offers a comparable structural
plan-first mechanism, at which point the ask-vs-deny and
branch-name-heuristic decisions above should be shared rather than
reinvented per platform; or when a sixth platform's addition makes three
consecutive hand-maintained trees feel like the wrong call after all.
