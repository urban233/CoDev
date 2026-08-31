**Status:** Proposed
**Owner:** TBD
**Reviewers:** TBD
**Brief:** [brief.md](./brief.md)
**Last reviewed:** 2026-08-30
**Compatibility evidence:** Partial — verified 2026-08-30 against `@anthropic-ai/claude-code`
2.1.251 (commit `37534ac596d8`, darwin-arm64), run via `npx --yes @anthropic-ai/claude-code`
(the official npm package; no persistent global install — this machine's Nix-managed npm prefix
is read-only, and `npx` doesn't need to write to it). No live authenticated session was run —
this environment has no Anthropic credentials for a separately-spawned `claude` process, and
initiating a login flow on the user's behalf is out of bounds. Findings below come from the
CLI's own `--help`/`doctor` output and from `strings`-inspecting the actual shipped executable
for literal constants (hook event names, settings keys, hardcoded file paths) — real shipped
code, not documentation. Items still needing a live session are marked open below.

**Live-session update, 2026-08-31 (unplanned, gathered while implementing
`docs/features/production-readiness/`) — fully resolved:** Martin reported getting repeated real
permission-prompt dialogs while an agent session edited files on a branch with no matching
spec — exactly `require_plan.py`'s "ask" behavior, from a real Claude Code runtime, not a
simulation. This confirms the hook payload shape assumption and that the permission-prompt UI
correctly surfaces the hook's `ask` decision to a human. The matching "stays silent when a spec
exists" half is confirmed three ways: direct script execution against the real installed hook
after renaming the branch to match; this same session's own real tool calls subsequently
appearing as `allow` entries in `.codev/hooks/decisions.jsonl`; and Martin's explicit
confirmation that the dialogs actually stopped once the branch was renamed. Both halves of this
guardrail's claim are now live-verified, not simulated.

## Summary

Add Claude Code as a fifth adapter platform, following the existing four-platform pattern
(parallel hand-maintained bundle subtrees sharing one installer, not a rendered-from-one-source
abstraction — `adapter.py`'s own docstring already calls the current shape a stopgap, and per
prior guidance this repo prefers not to force a "cleaner" plugin architecture as a precondition
for adding a fifth entry to it). On top of that parity work, add one thing no existing platform
has: a `.claude/settings.json` + `.claude/hooks/` pairing that structurally discourages editing
before a plan exists, using Claude Code's own permission-mode and hook primitives.

## Goals and Non-goals

**Goals**
- `codev init/update/adapter add/adapter verify/adapter remove --agent-platform claude` behave
  identically in shape to the existing four platforms' commands.
- All 13 roles ported with unchanged shared body prose; only the frontmatter dialect is new.
- Shared skills, and the `pr-review` command, made natively discoverable by Claude Code.
- A real, tested, honestly-scoped guardrail against implementing before discussing — not a
  README claim.
- Zero behavior change for existing Codex/Junie/OpenCode/Antigravity installs.

**Non-goals** (see brief.md for full list and reasoning)
- `codev eval run` driving Claude Code as an acting agent.
- `.mcp.json`.
- Getting Claude Code to read `AGENTS.md`.
- Unbypassable plan-mode enforcement.

## Current System and Evidence

Confirmed by direct repository inspection (2026-08-30):

- `installer.VALID_PLATFORMS = frozenset({"antigravity", "codex", "junie", "opencode"})`
  (`installer.py:52`) — no `enum`, platforms are plain strings keyed into several independent
  dicts/tuples, kept in sync by convention rather than by a single source of truth.
- Six sites carry one entry per platform today: `installer.py:52` (`VALID_PLATFORMS`),
  `installer.py:58-72` (`AUDIT_AGENT_TEMPLATES`), `installer.py:78-95`
  (`PRE_PR_CLEANUP_AGENT_TEMPLATES`), `installer.py:470-493` (`_bundle_files()`'s four
  `if "<platform>" not in platforms:` filter blocks), `adapter.py:75-80`
  (`ADAPTER_ROLE_PATHS`), `cli.py:76` (`_AGENT_PLATFORMS`).
- Two more real sites are packaging metadata, not code: `pyproject.toml`'s
  `[tool.setuptools.package-data]` glob list (an explicit per-subdirectory list for the sdist
  build — `docs/architecture.md`'s claim that "adding a bundled file does not require
  maintaining a second file list" is true only for the Bazel `glob(["bundle/**"])` path and for
  `importlib.resources`' runtime walk, not for what setuptools actually packages), and
  `pyproject.toml`'s `keywords` list.
- The bundle is not one source rendered four ways. It is three genuinely separate per-platform
  trees (`.codex/agents/*.toml`, `.opencode/agents/*.md` + `.opencode/opencode.json`,
  `.junie/agents/*.md` + `.junie/commands/pr-review.md`) plus Antigravity sharing the root
  `.agents/` directory with the platform-agnostic skills (`.agents/agents/*.md` next to
  `.agents/skills/*/`). The only templating in the whole bundle is `code-audit`/`code-audit-gate`
  (`{{DESCRIPTION_SCOPE}}`/`{{SKILL_PERMISSIONS}}`/`{{LANGUAGE_INSTRUCTIONS}}`/`{{JUNIE_SKILLS}}`
  substitution via `_render_code_audit_agent`, `installer.py:378-422`). Every role file's body
  prose is otherwise byte-for-byte identical across all four platforms — only the
  frontmatter/wrapper format differs per platform's own convention.
- `.agents/skills/<name>/SKILL.md` (15 skills) is already in the exact shape Claude Code's own
  Skills feature consumes: YAML frontmatter (`name`, `description`, `license`) plus a Markdown
  body. Each skill also ships a `skill-card.md` (ADR-0029 governance metadata, platform-agnostic)
  and an `agents/openai.yaml` presentation manifest that no CoDev code reads or filters — it ships
  unconditionally today regardless of platform selection, with no per-platform analogue. This
  repo is a genuine blank slate for Claude Code: an exhaustive case-insensitive grep across
  `src/`, `docs/`, `tests/`, and every top-level doc found zero adapter code, zero TODOs, zero
  ADR proposing it, and zero CHANGELOG entries — the only "claude" hits anywhere are an unrelated
  external tool's own agent-name vocabulary and incidental `"anthropic/claude"` example
  model-slug strings in unrelated config tests.
- `.junie/commands/pr-review.md` uses a `description:` frontmatter key plus a `$argument`-style
  body — the same shape as Claude Code's own slash-command convention, and the strongest existing
  template to port from.
- The root `.claude/` directory in this repo is empty, untracked, and has never been committed —
  confirmed via `git log --all -- .claude` (no history) and `git check-ignore -v .claude` (not
  gitignored either). It's a side effect of opening this project in the Claude Code app locally,
  not evidence of any prior integration attempt.
- This repo pairs a new platform/engine integration with an ADR (next available number: 0030)
  and a brief/design pair, and — per `nvidia-skill-evaluator/design.md` — expects a dated
  "compatibility spike" of empirically verified facts about the external surface before the
  Decision section commits to anything, rather than trusting that surface's own public docs.

### Phase 0 — compatibility spike (dated findings, 2026-08-30, v2.1.251)

1. **Subagent frontmatter** — `.claude/agents/*.md` is confirmed as the real, hardcoded discovery
   path (literal `.claude/agents/*.md` string in the binary). `name`, `description`, `tools`,
   `model` remain high confidence. **New finding**: `"permissionMode"`, `"disallowedTools"`, and
   `"maxTurns"` all appear as literal string constants in the shipped binary too — real,
   implemented fields, not invented by a research pass. Not yet confirmed: whether
   `permissionMode` set in a *subagent's* frontmatter is actually honored per-subagent, or only
   read at the session level (a secondary source claimed the former is ignored by the auto-mode
   classifier) — this needs a live session to settle, and only matters if a future revision wants
   per-role permission tuning finer than the shared `tools:` allow-list already gives us. Not
   blocking for V1.
2. **Skills discovery path — resolved.** `.claude/skills/*/SKILL.md` is a hardcoded, literal path
   in the binary, alongside built-in skill names Claude Code itself ships (`commit`, `deploy`,
   `verify`, `pdf`, `run`) plus a `.claude/skills/.trash` and a `.claude/skills/synced` (cloud-sync
   related). No evidence anywhere in the binary of a configurable alternate skills-path setting.
   **Decision: copy `.agents/skills/*` into `.claude/skills/<name>/` at install time** — the
   "point elsewhere" alternative in the table below is no longer plausible; strike it. Confirmed
   no name collision between CoDev's 15 skills and Claude Code's 5 built-in ones.
3. **Hook I/O contract — substantially confirmed.** Event names present as literal constants:
   `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`, `SessionStart`, `SessionEnd`,
   `PreCompact`, `Notification`, `SubagentStop`, plus two not in the original research —
   `PermissionRequest` and `InstructionsLoaded` — both real strings, exact usage unconfirmed.
   Decision-output field names confirmed as literal constants: `hookEventName`,
   `permissionDecision`, `hookSpecificOutput`, `systemMessage`, `additionalContext` — this matches
   the shape this design already assumed. Separately confirmed via the CLI's own migration-tool
   messaging: *"Hook event names differ between Codex and Claude Code. Re-add via the `hooks` key
   in settings.json"* — confirms hooks live under a top-level `"hooks"` settings.json key, as
   designed. Still open: the exact full stdin payload shape on a live tool call — needs a real
   session (deferred to Implementation Plan step 13).
4. **`permissions.defaultMode: "plan"` — mechanism confirmed real, live behavior still open.**
   `claude --help`'s `--permission-mode` flag lists `plan` as a real choice (full set:
   `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan` — note the CLI itself
   calls the baseline mode `manual`, not `default`; earlier research used the wrong name for this
   one mode, worth double-checking anywhere this design used "default"). `defaultMode` and
   `"plan"` both appear as literal binary constants. Not yet confirmed without a live session:
   that a *project-committed* `.claude/settings.json`'s `defaultMode` is honored as the terminal
   session default rather than only a CLI-flag/user-setting concept — deferred to step 13.
5. **`AGENTS.md` awareness — resolved, and it changes this design.** Found in the binary's own
   `claude import codex` migration messaging: *"Claude Code hardcodes CLAUDE.md / AGENTS.md
   discovery"* — stated as the reason Codex's configurable `project_doc_*` settings have no Claude
   Code equivalent. **Claude Code reads `AGENTS.md` natively, unconditionally, the same as
   CLAUDE.md.** Since CoDev already installs and maintains an `AGENTS.md` managed policy block for
   every platform, Claude Code picks up part of CoDev's shared contract automatically, with zero
   Claude-specific bundle work. This overturns the original assumption (see revised CLAUDE.md
   design below and the corrected brief.md non-goal) and removes a previously-open risk: since
   `.claude/CLAUDE.md` no longer needs to carry the full shared contract via `@import`, whether
   that import mechanism resolves correctly from `.claude/CLAUDE.md`'s location is no longer
   load-bearing for this design. `CLAUDE.local.md` is also a confirmed real, separate concept.

## Minimal V1 Scope

Everything in brief.md's "First-release scope." Explicitly deferred: Windows verification, the
`codev eval` Claude Code driver, output styles, statusline customization, and any MCP
configuration — none of these are needed to make Claude Code follow CoDev's workflow, which is
the actual goal.

## Components and Ownership

| Component | Responsibility | Owner | State |
|---|---|---|---|
| `installer.VALID_PLATFORMS` + 5 sibling dict/tuple sites | Recognize `"claude"` as a valid platform | `installer.py`, `adapter.py`, `cli.py` | New entries |
| `pyproject.toml` package-data + keywords | Ship `.claude/**` in the sdist; PyPI discoverability | `pyproject.toml` | New glob lines |
| `.claude/agents/*.md` (13 files) | Role subagents, Claude Code frontmatter dialect | new bundle subtree | New, ported body prose |
| `.claude/skills/` | Shared skills, natively discoverable | new bundle subtree | New — copy step, mechanism resolved by Phase 0 |
| `.claude/commands/pr-review.md` | PR-review slash command | new bundle file | New, ported from `.junie/commands/pr-review.md` |
| `.claude/settings.json` | Plan-mode default, hook wiring | new bundle file | New — no existing platform has an analogue |
| `.claude/hooks/require_plan.py` | The guardrail's enforcement point | new bundle file | New |
| `.claude/CLAUDE.md` | Short Claude-Code-specific supplement (subagent/skill locations, guardrail note) | new bundle file | New — `AGENTS.md` already covers the shared contract, per Phase 0 |
| `test_installer.py`/`test_adapter.py`/`test_cli.py`/`test_claude_hook.py` additions | Parity and hook-behavior test coverage | tests | New, mirrors existing per-platform tests plus fixture-stdin subprocess tests for the hook |
| `scripts/verify_claude_code_compat.py` + `claude-code-compat` CI job | Automated replacement for the manual Phase 0 spike; fails CI on real Claude Code surface drift | `scripts/`, `.github/workflows/ci.yml`, `Justfile` | New, scheduled + release-gated (needs network) |
| `README.md`, `docs/architecture.md`, `AGENTS.md` | Human-facing docs | docs | Updated |
| ADR-0030 | Records the settings.json/hooks category and the AGENTS.md-is-already-native-to-Claude-Code finding | `docs/adr/` | New, filed once Accepted |

## Data and Control Flow

Unchanged from the existing four-platform flow — Claude Code slots into the same pipeline, not a
parallel one:

1. `codev init --agent-platform claude` → `cli.py` validates against `_AGENT_PLATFORM_CHOICES` →
   `installer.plan_init(target, platforms=("claude",), ...)`.
2. `plan_init` → `_bundle_files(platforms, programming_language)` walks the packaged bundle,
   renders `code-audit`/`code-audit-gate` for `"claude"` via the existing
   `_render_code_audit_agent`, and (new) does **not** filter out `.claude/`-prefixed paths since
   `"claude"` is in `platforms` — the four existing `if "<platform>" not in platforms` blocks each
   grow a fifth sibling for `.claude/`.
3. Preflight diff against `target` (add/keep/conflict), same SHA-256/atomic-write/lock-file
   machinery as every other platform — no new machinery needed here.
4. `apply_plan` writes files atomically — unchanged. `.claude/hooks/require_plan.py` is invoked as
   `python3 "${CLAUDE_PROJECT_DIR}/.claude/hooks/require_plan.py"` directly in
   `.claude/settings.json`'s hook command, not via its own shebang, so it only needs to be
   readable — the same guarantee every other bundle file already gets. No executable-bit handling
   needed anywhere in the installer.
5. `codev adapter verify claude` → `adapter.verify_adapter("claude", target=...)` — the existing
   `BundleParityTests` in `test_adapter.py` iterates `for platform in ADAPTER_ROLE_PATHS`, so this
   starts getting free coverage the moment `ADAPTER_ROLE_PATHS["claude"]` exists, before any
   Claude-specific test is written.
6. `codev adapter remove claude` → `plan_adapter_remove`, refuses if `claude` is the only
   installed platform, same as every other platform.

## Guardrail Design

This is the one genuinely new piece of behavior, not just a fifth copy of an existing pattern.
Two layers, deliberately not one:

**Layer 1 — `permissions.defaultMode: "plan"` in `.claude/settings.json`.** Every fresh session
against a CoDev-managed repository starts in Plan Mode: Claude Code explores and proposes a plan
before it's allowed to edit, and a human must explicitly approve before it exits plan mode. This
is a real, native Claude Code feature, costs one settings key, and is the honest, low-risk core of
"prevent starting without discussion." Its known limitation (per Phase 0 item 4, pending
confirmation): a session can leave plan mode via `Shift+Tab` without ever having produced a plan
Claude itself proposed — this layer nudges, it does not lock.

**Layer 2 — a `PreToolUse` hook on `Edit|Write|MultiEdit|NotebookEdit|Bash`** that pauses for
human confirmation (`permissionDecision: "ask"`, not `"deny"`) on the first source edit, or the
first repository-mutating git command, of a session if it can find no evidence a spec exists for
the active work. "Ask" rather than "deny" is a deliberate choice: a hard deny would block
legitimate small, spec-free fixes and would fight CoDev's own principle that trivial changes
don't need a full brief/design cycle; "ask" forces a human checkpoint — exactly the "without
discussion" gap named in the brief — without a false positive turning into a hard stop.

Hook script contract (field names confirmed present in the shipped binary per Phase 0; exact live
payload shape still to be confirmed against a real tool call, step 13):
- Read and JSON-parse stdin (a real parser, not shell string matching over untrusted tool input —
  avoids injection from adversarial file/command content).
- No-op (allow, exit 0) for `Edit`/`Write`/`MultiEdit`/`NotebookEdit` calls, unconditionally, and
  for `Bash` calls whose command doesn't start with one of a fixed set of repository-mutating git
  prefixes (`git commit`, `git push`, `git merge`, `git reset`, `git checkout`, `git clean`,
  `git rebase`, `rm -rf`, `rm -r `) — the exact same list OpenCode's own `builder` subagent
  already denies outright in favor of the guarded `codev git` surface (ADR-0002). Prefix matching,
  not a full shell parse: a command chained after the first `&&`/`;`/`|` is a known, accepted gap,
  not a security boundary — this hook only ever asks, it never blocks anything on its own.
- Spec-exists check, two independent layers, either is sufficient:
  1. **Precise**: if the branch follows `codev git branch`'s own `codev/<task-id>` naming
     (`git_ops.branch_name_for`), check for that exact task's own recorded plan at
     `docs/codev/task/<task-id>/implementation-plan.md` — the current convention per
     `.agents/skills/build-change/SKILL.md` (an earlier draft of this hook checked
     `docs/codev/work/*/implementation-plan.md`, the pre-ADR-0023 path from ADR-0004's table;
     fixed before this was ever exercised against a real branch, not a shipped regression).
  2. **Coarse fallback**: a loosely-matching `docs/features/*/design.md` or
     `docs/codev/features/*/design.md`, by branch-name substring — for planning work that
     predates a `codev task start`, or a branch that never went through `codev git branch`. Still
     repo-wide/branch-name-heuristic, not per-task-precise, for this fallback case only.
- On any internal hook error (unparseable stdin, unexpected shape), fail open — allow, but write
  a warning to stderr. A guardrail that can brick every edit on its own bug is worse than a
  guardrail that occasionally misses.
- Never inspects the actual file contents being written or the full argument list of a gated bash
  command beyond its prefix — asks "does a spec exist for this branch/task," not "does this
  specific edit or command match it."

## CLI Behavior

| Command | Behavior |
|---|---|
| `codev init --agent-platform claude` | Installs the `.claude/` bundle alone |
| `codev init --agent-platform all` | Installs all five platforms, including `.claude/` |
| `codev update --agent-platform claude` | Adds Claude Code to an existing install, same conflict-aware preflight as initial install |
| `codev adapter add claude` | Adds Claude Code to an existing multi-platform install |
| `codev adapter verify claude` | Structural conformance check via `ADAPTER_ROLE_PATHS["claude"]` |
| `codev adapter remove claude` | Removes only the Claude Code adapter; refuses if it's the last one installed |
| `codev adapter list` | Includes `claude` once installed |

## Alternatives and Trade-offs

| Decision | Option | Benefits | Costs/risks | Recommendation |
|---|---|---|---|---|
| Skills exposure | Copy `.agents/skills/*` into `.claude/skills/<name>/` | Matches how every other platform gets its own directory; no new mechanism (existing copy logic, new destination prefix); no cross-platform coupling | Physical duplication on disk; two copies to keep in sync (mitigated: both come from the same bundle source, copied at install time, not hand-maintained twice) | **Decided** — Phase 0 confirmed `.claude/skills/*/SKILL.md` is a hardcoded path with no configurable alternative |
| Skills exposure | Point Claude Code at `.agents/skills/` via a settings path | Zero duplication | Phase 0 found no such setting anywhere in the shipped binary, alongside a hardcoded `.claude/skills/*/SKILL.md` path and Claude Code's own built-in skills living there | Ruled out by Phase 0 |
| Skills exposure | Symlink `.claude/skills` → `.agents/skills` | Zero duplication, simple | No existing CoDev mechanism uses symlinks (everything is atomic per-file writes over a hash-verified lock); fragile across filesystems; breaks the existing conflict/diff model, which reasons about file contents, not links | Rejected |
| Guardrail strength | Plan-mode default only, no hook | Simplest; zero new file category; lowest risk of a buggy hook | Weakest guardrail — bypassable with one keystroke, no checkpoint at all if bypassed | Rejected alone, kept as Layer 1 |
| Guardrail strength | Plan-mode default + `ask` hook (this design) | Two independent layers; hook is a real checkpoint even if plan mode is bypassed; degrades gracefully (ask, not deny) | New file category (settings.json/hooks) with its own schema-drift risk | **Recommended** |
| Guardrail strength | Plan-mode default + `deny` hook | Strongest possible block | High false-positive cost on legitimate trivial fixes; contradicts CoDev's own principle that small changes don't need a full spec cycle | Rejected as default; document as an opt-in stricter variant |
| Guardrail scope | Edit/Write only, no Bash gating | Simplest; avoids a second axis of false positives | Leaves the exact category of raw git mutation ADR-0002 already treats as dangerous enough to deny outright for OpenCode's `builder` completely uncovered for Claude Code | Superseded |
| Guardrail scope | Also gate `Bash` calls matching ADR-0002's raw-mutation prefix list (`git commit`/`push`/`merge`/`reset`/`checkout`/`clean`/`rebase`, `rm -rf`) (this design) | Reuses an already-accepted, already-scoped command list instead of inventing a new one; prefix match is cheap and fails open the same way the edit check does | Prefix matching misses chained commands (`cmd1 && git commit`) — an accepted, named gap, not a security boundary given this hook only ever asks | **Implemented** |
| Compatibility verification | Manual, one-time (Phase 0 as originally run) | Zero infrastructure | No way to know when Claude Code's own surface drifts after that one check; exactly the "trust docs blindly" failure mode this whole design tries to avoid | Superseded |
| Compatibility verification | `scripts/verify_claude_code_compat.py`: resolve the real CLI via `npx`, substring-search its shipped binary for every marker this adapter depends on, fail loudly on drift; scheduled + release-gated CI job (needs network, so not part of the deterministic `test` job) | Turns the one-time spike into a repeatable, automated check; catches drift before a release, not after a user reports it | Verifies presence of literal markers, not full runtime behavior (still no substitute for the live-session items in Resolved Contracts and Deferred Risks) | **Implemented** |
| Spec-exists check | Branch-name-substring heuristic only | Simplest; no task-naming-convention dependency | Coarse — a loosely-matching filename is not proof the plan is *for* this change | Kept as the fallback layer, not the only layer |
| Spec-exists check | Exact match against `docs/codev/task/<task-id>/implementation-plan.md`, `<task-id>` derived from the branch via `git_ops.branch_name_for`'s own `codev/<task-id>` convention (this design) | Precise for any branch created through `codev git branch`; no new CLI surface — a plain filesystem check, since the branch↔task-id mapping is already public and exact | Only applies to branches following that convention; pre-task planning work still needs the fallback | **Implemented**, layered on top of the fallback, not instead of it |
| Spec-exists check | A new `codev task status --json`-style predicate the hook shells out to, instead of a direct filesystem check | Would also work; reusable by other platforms' hooks later | Adds a `codev`-on-PATH dependency to the hook's subprocess environment for no real gain — `describe()`'s existing JSON has no plan-file field either, so this would need its own new CLI surface, not just wiring an existing one | Rejected — the direct filesystem check above gets the same precision without the new dependency or CLI surface |
| CLAUDE.md content | Short Claude-Code-specific supplement (no import needed) | Phase 0 confirmed `AGENTS.md` is natively, hardcodedly read by Claude Code already — CoDev's shared contract arrives for free via the existing managed `AGENTS.md` block; CLAUDE.md only needs to add what's Claude-Code-specific (where role subagents/skills live, that the guardrail hook exists) | None identified | **Recommended** — settled by Phase 0, no longer dependent on `@import` behavior |
| CLAUDE.md content | Thin file that `@`-imports `.codev/for-ai/ai-agent-guidelines.md` | Would also work | Solves a problem Phase 0 showed doesn't exist — `AGENTS.md` is already read natively, so importing a second shared-contract file is redundant, and adds an untested dependency on import resolution for no benefit | Rejected — superseded by the finding above |
| CLAUDE.md content | Duplicate the guidelines prose directly | No dependency on import behavior | A hand-maintained copy of prose already duplicated four times across platform frontmatter bodies, now provably unnecessary since `AGENTS.md` is already read | Rejected |

## Quality and Risk

- **Security**: the hook script must JSON-parse stdin with a real parser, never interpolate tool
  input into a shell command it then executes, and must not need network access. It only reads
  repository-local file existence — no secrets, no credentials, consistent with every other part
  of this bundle.
- **False positive/negative risk**: the branch-name heuristic (V1) will sometimes ask when a spec
  genuinely exists but the filename doesn't match, and will sometimes stay silent when a stale,
  unrelated spec file happens to match. This is named explicitly as a known V1 limitation, not
  claimed as precise — same rhetorical move `skill-eval/design.md` uses for its own V1 scoping.
  It only ever asks (pauses for a human), never silently blocks, which bounds the damage of a
  false positive to one extra confirmation click.
- **Compatibility/schema drift**: Claude Code's settings/hook schema is outside CoDev's control.
  Treat it the way `eval_nvidia.py` treats the external SkillEvaluator CLI: re-verify against the
  installed tool, don't trust cached knowledge of its surface. If a `minimumVersion` settings key
  is confirmed real in Phase 0, consider setting it so an incompatible older Claude Code fails
  loudly rather than silently mis-parsing the bundle's settings.json.
  Concretely: whatever the actually-verified version turns out to be in Phase 0, record it here
  and treat later Claude Code releases the same way `nvidia-skill-evaluator` treats SkillEvaluator
  releases — re-verify before assuming continued compatibility, don't assume forward-compatibility
  silently.
- **Reliability**: hook fails open on its own internal errors (see Guardrail Design) — a bug in
  the guardrail script degrades to "no guardrail," never to "no edits possible."
  the hook does not target `docs/` writes when specs live in `docs/` — Edit/Write on files under
  `docs/features/**` or `docs/codev/**` themselves should not be gated, or writing the plan doc
  that would satisfy the check becomes impossible. Confirm this exclusion is implemented, not just
  assumed, before this ships.
- **Observability**: consider a local, gitignored log under `.codev/` for hook decisions, mirroring
  the existing managed `.gitignore` block's local-escalation-log pattern already established for
  the other platforms.
- **Compatibility (platform)**: macOS-verified V1; Linux plausible but unverified (hook scripts
  are POSIX shell); Windows deferred, matching `skill-eval`'s own precedent for exactly this kind
  of gap.

## Implementation Plan

1. **Phase 0 spike**: install/update a real Claude Code CLI, empirically resolve the five open
   questions above, and rewrite this doc's "Compatibility evidence" header and Phase 0 section
   with dated findings before writing implementation code.
2. Add `"claude"` to `installer.VALID_PLATFORMS`, `cli.py`'s `_AGENT_PLATFORMS`, and a skeleton
   `adapter.ADAPTER_ROLE_PATHS["claude"]` entry pointing at not-yet-created paths. Run
   `BundleParityTests` expecting failure — a deliberate red baseline before any bundle content
   exists.
3. Port the 11 static role files' shared body prose into `.claude/agents/<role>.md` with Claude
   Code subagent frontmatter (`name`/`description`/`tools`/`model`, informed by Phase 0 findings;
   Junie's `tools:` array is the closest existing format to port from, per-role, since it's
   already an explicit tool allow-list rather than a coarse sandbox mode).
4. Add `.claude/agents/code-audit.md.template` and `.claude/agents/code-audit-gate.md.template`;
   wire both into `AUDIT_AGENT_TEMPLATES`/`PRE_PR_CLEANUP_AGENT_TEMPLATES`; confirm
   `_render_code_audit_agent` needs no changes.
5. Extend `_bundle_files()`'s four-block filter chain with a fifth `.claude/`-prefixed block.
6. Implement the skills-exposure decision from Phase 0/Alternatives (default assumption: copy
   `.agents/skills/*` content into `.claude/skills/<name>/` at bundle-build time).
7. Port `.junie/commands/pr-review.md` → `.claude/commands/pr-review.md`.
8. Author `.claude/settings.json` and `.claude/hooks/require_plan.py` (invoked explicitly via
   `python3`, sidestepping any executable-bit question); add the new `pyproject.toml`
   package-data glob lines this new file category needs.
9. Author `.claude/CLAUDE.md` as a short Claude-Code-specific supplement — not a copy or import of
   the shared contract, since Phase 0 confirmed `AGENTS.md` is already natively read. Content:
   where role subagents/skills/commands live, and a note that the plan-first guardrail is enforced
   via `.claude/settings.json`/hooks. Keep under CLAUDE.md's own recommended length (roughly
   200 lines) precisely because it isn't carrying the full contract.
10. Update `pyproject.toml` keywords; confirm `BUILD.bazel`'s `glob(["bundle/**"])` needs no
    change (it's already recursive).
11. Update `README.md` (the `--agent-platform` explanation, the "what gets installed" tree, and
    the "official workspace location" sentence — following the same phrasing already used for
    Codex/Antigravity), `docs/architecture.md`'s Bundle section, `AGENTS.md` if relevant.
12. Tests: mirror `test_installer.py`'s per-platform pattern
    (`test_claude_adapter_installs_valid_agents_without_other_adapters`,
    `test_bundle_filters_claude_adapter_files`, inclusion in
    `test_all_adapters_render_selected_audit_language`, `test_remove_deletes_claude_agents`,
    `test_remove_claude_from_multi_platform_install`); add hook-script-level tests in
    `test_claude_hook.py` (fixture stdin → assert exit code and stdout shape, independent of a
    real Claude Code install) covering the file-edit path, the precise task-plan path, the coarse
    fallback path, and the `Bash` destructive-prefix path; add `test_cli.py` adapter
    add/verify/remove coverage. `BundleParityTests` extends automatically.
13. Manual end-to-end verification: real `codev init --agent-platform claude` into a scratch repo,
    a real Claude Code session against it, confirming plan-mode fires by default, the hook asks
    correctly in both the spec-exists and no-spec-exists cases, and subagents/skills/commands are
    all discoverable. Record this as dated "Compatibility evidence" in the header, the way
    `nvidia-skill-evaluator` cites its exact pinned, tested commit.
14. `scripts/verify_claude_code_compat.py`: automate the static half of Phase 0 (marker presence
    in the shipped binary, not live runtime behavior) so future drift is caught by CI, not the
    next person to trust this adapter blindly. Wire it as a scheduled + release-gated CI job,
    matching `live-eval`'s trigger condition, since it needs network access `test`/`quality` don't.
15. CHANGELOG entry matching v0.3.0's evidence-bearing density; file ADR-0030; flip this doc's
    Status to Accepted.

## Test Strategy

Unit tests mirror the existing per-platform matrix in `test_installer.py`/`test_adapter.py`
exactly (install-alone, filter-correctness, multi-platform remove, code-audit-language rendering)
plus new hook-script tests that don't require a real Claude Code install — the hook is a plain
script tested against fixture JSON on stdin, the same "pin the external contract in tests against
a fake, not the real tool" pattern `skill-eval` already uses for its OpenCode driver. CLI-level
tests mirror the existing `adapter list/add/verify/remove` round-trip tests.
`scripts/verify_claude_code_compat.py` automates the static half of Phase 0 going forward —
literal marker presence in the real, currently-published CLI's shipped binary, on a schedule and
before every release — but that is deliberately not the same claim as verified runtime behavior.
End-to-end verification against a real, live Claude Code *session* (step 13 above) stays manual
and one-time, recorded as dated evidence in this doc — CoDev does not automate against a real
Claude Code session any more than it automates credentialed runs elsewhere in the codebase.

## Migration, Rollout, Rollback, and Cleanup

Purely additive: no existing install is touched until a user opts in via
`--agent-platform claude` or `all`. Rollback is `codev adapter remove claude`. The one real
behavior change: `--agent-platform all` will include a fifth platform going forward, so anyone
who periodically re-runs `codev update --agent-platform all` gains a new adapter on their next
update — call this out explicitly in the CHANGELOG, the same way Junie+Antigravity's simultaneous
addition was called out rather than left implicit.

## Resolved Contracts and Deferred Risks

| Item | Status |
|---|---|
| Exact subagent/hook/settings JSON schema | Substantially resolved by Phase 0 static/binary inspection (2026-08-30, v2.1.251); full live tool-call payload shape and project-level `defaultMode` behavior still need a live authenticated session — deferred to Implementation Plan step 13, not blocking further design/build work |
| Skills exposure mechanism (copy vs. point-at vs. symlink) | Resolved by Phase 0 — copy, no alternative exists |
| Whether `AGENTS.md` is read by Claude Code | Resolved by Phase 0 — yes, hardcoded; CLAUDE.md redesigned as a short supplement, not an import wrapper |
| Windows support | Deferred risk, not V1 acceptance requirement |
| `codev eval run` driving Claude Code as an acting agent | Deferred — separate, comparably-sized future effort, own brief/design if pursued |
| Precise (non-branch-heuristic) spec-exists check | Resolved — a direct filesystem check against `docs/codev/task/<task-id>/implementation-plan.md`, `<task-id>` derived from the branch via `git_ops.branch_name_for`'s own convention, layered on top of (not instead of) the coarse fallback |
| Destructive-`Bash` gating (git push/commit, rm) in the hook | Resolved — the same command list ADR-0002 already denies outright for OpenCode's `builder`, matcher broadened to `Edit\|Write\|MultiEdit\|NotebookEdit\|Bash` |
| Automated compatibility verification (replacing the one-time manual Phase 0 spike) | Resolved — `scripts/verify_claude_code_compat.py`, wired as a scheduled + release-gated CI job (`claude-code-compat` in `ci.yml`, in `prepare-release`'s `needs`) |
| Executable-bit preservation through `_atomic_write` | Moot — the hook is invoked via explicit `python3 <path>`, not its own shebang, so it only needs to be readable |

## Acceptance

- [ ] Phase 0 compatibility spike complete; header and Phase 0 section updated with dated findings
- [ ] `codev init --agent-platform claude` installs a conformant `.claude/` bundle
- [ ] `codev init --agent-platform all` includes Claude Code
- [ ] `codev adapter add/verify/remove claude` all pass against a fresh install
- [ ] `BundleParityTests` passes for `"claude"` with zero platform-specific test-file changes
      needed beyond the `ADAPTER_ROLE_PATHS` entry
- [ ] Plan-mode default confirmed active on a real Claude Code session against an installed bundle
- [x] Guardrail hook confirmed to `ask` when no spec exists and stay silent when one does, against
      a real Claude Code session -- **confirmed 2026-08-31**, see the live-session update in this
      document's header
- [x] Full existing test suite passes unmodified
- [x] New Claude Code test coverage passes (installer, adapter-remove, CLI, hook script)
- [x] `scripts/verify_claude_code_compat.py` passes against the real, currently-published CLI
- [x] README.md, docs/architecture.md, ADR-0030, CHANGELOG.md all updated (AGENTS.md needs no
      change -- confirmed no new safe-merge integration file, unlike OpenCode's `opencode.json`)
- [x] Existing Codex/Junie/OpenCode/Antigravity installs verified unaffected
