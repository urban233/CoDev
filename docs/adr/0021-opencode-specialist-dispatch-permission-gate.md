# ADR-0021: OpenCode specialist-dispatch permission gate

**Status:** Accepted
**Date:** 2026-08-14

## Context

ADR-0016 specified `outer-loop-runner` should present the five specialists as
a numbered menu and let a human pick a subset. ADR-0018, written from a real
session's saved transcript, found the model skipping the menu entirely —
"from the CI gate directly to 'I'm proceeding with a fresh five-specialist
pass,' no menu, no waiver question, anywhere in the conversation" — and
concluded plainly: "`codev` has no way to gate *dispatching a subagent* ...
No new `check()` outcome or CLI command can force the pause itself." 0.2.2
shipped the only mitigation available at that layer: an optional
`--selection` audit field making the omission visible after the fact.

A second real session (CLIP, work item L-03 / PR #12), run on 0.2.2 with the
fixed prompt text confirmed present, reproduced the identical failure
verbatim: *"Gate passed... I'm dispatching all five authorized specialists
against this exact snapshot."* No menu, no question — the same pattern the
pre-0.2.2 session showed. The `--selection` record faithfully showed all five
ran, exactly as ADR-0018 predicted it would either way: the field cannot
distinguish "the human picked all five" from "the human was never asked."

ADR-0018's own conclusion was too narrow in one respect: it framed the gap as
"no CLI mechanism reaches" subagent dispatch, full stop. That's true of
`codev`'s own CLI — but OpenCode's bundled agent files already carry a
`permission` block that *is* a real gate on tool/subagent invocation, and the
same file already uses it for exactly this purpose elsewhere: `bash: "*":
ask` forces a pause before arbitrary shell commands. `outer-loop-runner.md`'s
`task` permissions for all five specialists (and `builder`) were set to
`allow` — the one lever available was configured to rubber-stamp precisely
the decision ADR-0016 says must be a human call.

Checked directly: Codex (`outer-loop-runner.toml`), Antigravity
(`.agents/agents/outer-loop-runner.md`), and Junie
(`.junie/agents/outer-loop-runner.md`) have no equivalent per-subagent
permission block in what CoDev currently configures for them — Codex exposes
`commandExecutionPolicy: sandbox` at the process level, nothing per-subagent;
Antigravity and Junie's agent files carry no permission block at all. This
fix is available on exactly one of the four platforms today.

## Decision

In `src/codev_workflow/bundle/.opencode/agents/outer-loop-runner.md`, the
five specialist entries under `permission.task` move from `allow` to `ask`:
`correctness-tests-specialist`, `security-data-specialist`,
`concurrency-specialist`, `architecture-maintainability-specialist`,
`rollout-specialist`. `builder: allow` is unchanged — its dispatch inside the
outer loop is already gated by an explicit prior human triage decision (step
4), a different checkpoint this ADR doesn't touch.

This means OpenCode itself now pauses for a real permission decision before
every specialist invocation, independent of whether the model rendered the
numbered menu first. It is not equivalent to the intended UX — even on the
happy path, where the human already answered the menu in chat, OpenCode's
tool-permission system doesn't know that answer satisfied anything, so each
selected specialist still produces its own confirmation prompt. Accepted
directly: a real mechanical backstop, even a redundant one on the correct
path, closes a gap the prompt-only 0.2.2 fix demonstrably did not. One
sentence was added to `outer-loop-runner.md`'s step 2 (OpenCode only) telling
the agent to expect this and proceed through it rather than treat it as a
malfunction to explain away or route around.

Codex, Antigravity, and Junie keep prompt-only enforcement for this
checkpoint, unchanged, until each platform's own adapter file gains an
equivalent lever — the same kind of documented, deliberate cross-platform
asymmetry ADR-0013 already established for `git.pr_base` resolution.

**Guard against silent regression:** `adapter.py` gains
`_SPECIALIST_ALLOW_MARKERS`, checked the same way
`_UNRESTRICTED_BASH_MARKERS`/`_RAW_MUTATION_MARKERS`/
`_HANDWRITTEN_PR_BODY_MARKERS` already are — a future edit that quietly
reverts any of the five specialists back to `allow` now fails
`codev adapter verify`/the bundle-parity test, the same "cannot silently
regress on any platform again" protection `_HANDWRITTEN_PR_BODY_MARKERS`
already gives the PR-body fix.

## Consequences

- No `work.py`/`git_ops.py`/schema change: this is entirely bundle-file and
  conformance-checker surface, the same class of change as ADR-0010/0019.
- A real increase in friction on OpenCode specifically, accepted with the
  maintainer directly: every fresh outer-loop pass now costs one permission
  click per selected specialist, even when the model behaves correctly.
- This does not, and cannot, guarantee the numbered menu itself still
  appears in chat — the model can still skip straight to invoking a
  specialist. What changes is that the invocation itself now stops for a
  real human decision on OpenCode, rather than proceeding silently the way
  ADR-0018's audit-only mitigation left it able to.
- Codex/Antigravity/Junie are unaffected and remain exactly as exposed to
  this gap as before — not a regression, since they had no lever to begin
  with, but a known, documented limitation rather than a silent one.
- Testing needs (added): `tests/test_adapter.py` — a specialist reverted to
  `allow` is flagged with the ADR-0021 message; `ask` is not flagged.
  `tests/test_adapter.py::BundleParityTests` already re-runs against the
  live bundle on every test run, confirming the shipped file itself passes.
