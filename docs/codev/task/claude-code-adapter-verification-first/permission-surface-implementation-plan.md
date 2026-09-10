# Slice 2: Permission Surface - Implementation Plan

**Status:** Accepted
**Owner:** urban233
**Reviewer:** independent reviewer, to be named before the pull request is marked ready
**Risk:** normal. Small diff, but it changes what an agent may run without asking, and a wrong `allow` widens that silently.
**Containment:** every rule is reversible by editing one JSON file; `deny` is additive and cannot be widened by a later `allow`.
**Work style:** `delegate` (recorded) -- hence this written plan, per the tiering slice 1 shipped
**Slices:** 5, per the parent plan
**Slice:** `permission-surface` (2 of 5)
**Base commit:** `4e0d2e9` (head of the merged slice 1 branch; stacked on it)
**Issue/work item:** [urban233/CoDev#47](https://github.com/urban233/CoDev/issues/47)
**Brief/design/API:** [docs/plans/claude-code-adapter-verification-first.md](../../../plans/claude-code-adapter-verification-first.md), Accepted 2026-09-08 -- D6

## Focus card

- **Change:** give `.claude/settings.json` a `permissions.allow` list covering
  the read-only and verification surface CoDev's own workflow generates
  constantly, and a `permissions.deny` list covering the two publish recipes
  an agent must never run.
- **Success:** a routine loop turn -- `codev next --json`, `codev task check`,
  `just test` -- stops raising permission prompts; `just publish-pypi` is
  refused rather than prompted.
- **Non-goals:** hooks (slice 3), scientific gates (slice 4), recovery and
  statusline (slice 5); any other adapter; changing what the gates decide.
- **Allowed scope:** `src/codev_workflow/bundle/.claude/settings.json` and its
  installed copy, `AGENTS.md`, `tests/`, `CHANGELOG.md`.
- **Validation:** full test suite; `scripts/verify_self_install.py`; a test
  asserting the deny rules exist and that the settings file parses.
- **Stop if:** the `allow` list would cover a command that can mutate the
  repository or the outside world.

## Repository evidence

Confirmed against the Claude Code documentation:

- **Rule syntax.** `Bash(git diff *)` and `Bash(just test:*)` are both valid;
  the `:*` suffix is an equivalent way to write a trailing wildcard. Without a
  wildcard the match is exact. A colon *inside* a pattern is a literal
  character, not a separator.
- **Compound commands do not inherit an allow.** Claude Code splits a compound
  command and evaluates each subcommand separately, so `Bash(just test:*)`
  does **not** approve `just test && rm -rf /`. `deny` and `ask` rules, by
  contrast, apply to subcommands nested anywhere -- inside subshells, command
  substitutions, and control-flow bodies. This is the property that makes an
  allow list safe to add at all, and it is why this slice is worth doing.
- **Precedence is `deny` > `ask` > `allow`**, first match wins regardless of
  specificity, and `deny` still applies under `bypassPermissions`. A broad
  deny cannot carry allowlist exceptions.
- **Project `allow` rules take effect only after the workspace trust dialog is
  accepted.** `deny` and `ask` apply without it. This materially limits what
  this slice delivers on a fresh clone -- stated in the CHANGELOG rather than
  discovered later.
- **Undocumented, and treated as unknown:** whether a `deny` rule can be
  evaded by invoking the command differently (a wrapper script, a symlink, an
  env var). First-hand reports gathered for the parent plan show agents *do*
  work around blocked actions -- one discovered `HUSKY=0 git commit` to bypass
  a commit hook -- so this slice treats `deny` as defence in depth over the
  existing prose instruction, never as a guarantee.
- `AGENTS.md` currently instructs an agent never to run `just publish-pypi` /
  `just publish-testpypi` in prose only, including the parenthetical "even if
  asked indirectly (e.g. 'run the full ci suite including publishing')".
- `.claude/settings.json` today carries only `permissions.defaultMode: "plan"`
  and three `PreToolUse` hooks. There is no `allow`, `deny`, or `ask` list.

## Proposed change

1. **`permissions.deny`** -- `Bash(just publish-pypi:*)` and
   `Bash(just publish-testpypi:*)`. This turns an existing stated invariant
   into an enforced one. Because deny applies to nested subcommands, it also
   covers `just ci && just publish-pypi`, which is the indirect phrasing
   `AGENTS.md` already warns about.
2. **`permissions.allow`** -- only commands that read or validate, never ones
   that mutate the repository or reach outside it:
   - `Bash(codev next:*)`, `Bash(codev task check:*)`, `Bash(codev task log:*)`
   - `Bash(just test:*)`, `Bash(just lint:*)`, `Bash(just typecheck:*)`,
     `Bash(just fmt-check:*)`, `Bash(just validate-catalog:*)`
   - `Bash(git diff:*)`, `Bash(git status:*)`, `Bash(git log:*)`,
     `Bash(git show:*)`
   - `Bash(gh pr view:*)`, `Bash(gh run view:*)`
   Deliberately excluded: every `codev git *` command, every `codev task
   record`/`round close`/`slice *` command, `just fmt` (mutates), `just dist`,
   anything under `gh pr create|merge|edit`. Those are exactly the mutations
   the guarded surface exists to make visible.
3. **`AGENTS.md`** -- replace the prose warning against the publish recipes
   with a pointer to the deny rule that now enforces it, keeping the table's
   "human-run only" marking.
4. **A new test** (`tests/test_permission_surface.py`) pinning: the bundle
   settings file parses; both deny rules are present; the bundle and
   installed copies stay byte-identical; `defaultMode` and the three
   `PreToolUse` hooks are untouched.

## Validation

- Full test suite (`bazel test //tests/...`).
- `scripts/verify_self_install.py` -- slice 1's CI failure was exactly this
  check catching a managed file whose bundle source had drifted, and this
  slice edits a managed file.
- The new test asserting `.claude/settings.json` parses and that both deny
  rules are present, so the enforcement cannot be silently deleted.
- Manual: confirm a `just test` turn no longer prompts, and that
  `just publish-pypi` is refused. **Do not actually publish anything** --
  observe the refusal, nothing further.

## Risks and rollout

- **The allow list may deliver nothing on a fresh clone.** Project `allow`
  rules require the workspace trust dialog. A developer who has not accepted
  it gets the deny rules but not the allow rules, so the prompt reduction --
  the actual point of D6 -- will not appear. Stated in the CHANGELOG rather
  than left to be discovered.
- **An allow rule is a standing grant.** The compound-command split makes it
  much safer than it first appears, but the list should stay short and
  read-only, and any addition deserves the same scrutiny as this one.
- **`deny` evasion is unverified.** Treated as defence in depth; the prose
  instruction is replaced by a pointer, not deleted outright.
- **Rollback** is editing one JSON file.

## Decisions needed

None blocking. One thing to note rather than decide: the parent plan's ledger
credits this slice with retiring roughly 180 tokens from `AGENTS.md`, but the
budget was measured against the *bundle's* `AGENTS.md`, while the publish
paragraph lives in this repository's own root `AGENTS.md`. The retirement is
real for this repository and does not reduce the shipped always-on payload.
The ledger's arithmetic is therefore optimistic by about 180 tokens against
whatever headroom slice 1 actually left (measured at 275 tokens against the
7,500 ceiling once PR #49's cost was absorbed into the relocated skill body,
per slice 1's own completion evidence). Slice 3 will need genuine retirement,
not this.

**Provenance note:** this slice was implemented once already (2026-09-08) and
independently reviewed clean -- inner loop READY_FOR_OUTER_LOOP, zero
findings. Its pull request (#51) was closed not for a code problem but
because CoDev's own coverage-waiver scoping bug (fixed since, task
`waivers-are-slice-scoped`) rendered a stale, unrelated waiver reason from
slice 1 into its coverage block. This plan and the diff it describes reuse
that already-reviewed work verbatim, rebuilt on the current `main` and going
through inner- and outer-loop review again fresh, since the earlier review's
evidence trail was against a now-superseded head.

## Completion evidence

- [ ] Full suite green
- [ ] `verify_self_install.py` clean (bundle source and installed copy in sync)
- [ ] Deny rules covered by a test
- [ ] Manual check: routine loop turn prompts less; publish recipe refused
- [ ] CHANGELOG entry, including the workspace-trust caveat
- [ ] `git diff` confirms no change outside the allowed scope
