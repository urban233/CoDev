# ADR-0036: The `codev` CLI is an agent interface, and phase guidance is computed

**Status:** Accepted
**Date:** 2026-09-02
**Owner:** Martin Urban
**Related design:** [docs/features/unified-workflow/brief.md](../features/unified-workflow/brief.md)

## Context

CoDev's documentation already states the intended relationship between a
developer, an agent, and the CLI.
`docs-site/src/content/docs/getting-started.md` calls `codev init` "the last
`codev` command you type today," the site's home page says the agents "run
the `codev` CLI on your behalf so you don't have to," and
`working-with-your-agent.mdx` has a section titled "What you'll never have
to type." No ADR records that as a decision, so it has the standing of a
description rather than a constraint, and the implementation has drifted
from it in two directions.

**The CLI is not fully machine-readable.** Of roughly forty leaf commands
in `src/codev_workflow/cli.py`, eight accept `--json`: `status`, `adapter
list`, `adapter verify`, `config get`, `config list`, `task check`, `task
status`, and `task size`. The `git` group — the group an agent is required
to use, because raw `git commit`, `git push`, and `gh pr create` are denied
to every role — emits none. `codev git commit` prints `Committed <sha> on
<id>'s branch`, and the agent's very next obligation is a check against that
exact head, so the value is either scraped out of an English sentence or
re-derived with the raw `git` the guarded surface exists to displace.
`codev git restack` reports its new head the same way. `codev task log` is
prose only.

**Two commands assume a human at the keyboard.** The brief catalogues the
carve-outs: `codev codeowners init` is documented as human-run in three
places, and `codev init` is a genuine bootstrap exception that nothing
distinguishes from it, so both read to a developer as "sometimes you do run
commands."

**Nothing obliges the agent to guide.**
`.codev/for-ai/ai-agent-guidelines.md`'s interaction contract asks the agent
to "state the current step and why it matters" and to "recommend a path or a
default," but both fire only once it is already acting on a request. There is
no obligation to volunteer a recommendation at a phase boundary. The
developer therefore supplies the sequencing knowledge — that a draft pull
request means outer-loop review is next, that outer-loop review is a separate
session they must start, that a blocking finding must be triaged before
anything else, that a merged slice means the next may begin. Every one of
those facts is already computable from `task.check`'s exit code and the pull
request's state. None is offered.

The accepted brief identifies the correlation that explains CoDev's uneven
feel: every part of the workflow that works well is a part where a `codev`
exit code, not prose, made the decision.

## Decision

The `codev` CLI is an **agent interface**. Three rules follow, and they bind
every future command.

**One: every command an agent invokes emits machine-readable output for every
value the agent will need next.** `--json` is a required part of a new
command's surface, not an optional convenience, whenever its result feeds a
subsequent invocation. Human-readable output stays the default and stays
byte-compatible, so recovery, CI, and debugging use is unaffected. No agent
instruction in the bundle may direct an agent to read a value out of prose or
to fall back to raw `git` for a value a guarded command already knows.

**Two: `codev init` is the single documented exception.** It is a bootstrap
that necessarily precedes any agent session, and it is named as such wherever
it appears. Every other command is agent-invocable, including `codev
codeowners init`, which gains an agent-invocable form under the ordinary
confirmation posture. A future command that cannot be agent-invoked must
amend this ADR and say why.

**Three: phase-boundary guidance is computed, not conventional.** A state
oracle reports the current position — branch, slice round state,
`task.check` outcome, pull-request and review state — together with a
recommended next action and its reason, as machine-readable output. The
agent consults it at the start of every turn and after every state change,
and renders it as one plain-language recommendation. The interaction contract
in `.codev/for-ai/ai-agent-guidelines.md` is amended to require position,
recommendation, and reason at every phase boundary, sourced from the oracle
rather than from the agent's own judgment.

The third rule is what makes the first two worth having. Because the
recommendation is computed, it is identical across adapters, stable across
sessions, and testable — which a prose convention asking a model to remember
a sequence is not.

## Alternatives considered

- **Strengthen the prose contract and leave the CLI as it is:** rejected.
  This is the status quo, and the accepted brief's central evidence is that
  the mechanized parts of CoDev behave and the prose parts drift. Asking more
  of a document that is already 2,800 words, and already duplicated into
  `orchestrator.md`, adds drift surface rather than reliability.
- **A developer-facing `codev next` command:** rejected, and explicitly
  superseded within the brief that proposed it. Framing the position report
  as something a developer types reintroduces exactly the CLI-shaped
  developer experience this decision exists to remove. The oracle's
  developer-facing form exists only for debugging and CI, and the
  documentation says so.
- **Have each agent compute the recommendation itself from `task.check`'s
  exit code:** rejected. That is a routing table reimplemented once per
  adapter, in prose, with no test covering it — the same failure mode as the
  Claude Code-only hooks the brief separately proposes to move into `codev`.
- **Emit JSON always, dropping human-readable output:** rejected. Recovery
  by hand and CI inspection are real uses, ADR-0007's recovery story depends
  on a human reading `codev task log`, and there is no cost to keeping both.

## Consequences

- Every existing command's human-readable output is now a compatibility
  surface. Adding `--json` is additive; changing default output is not, and
  needs the same care as any other observable behavior change.
- The oracle needs no new state. It is a pure read over the slice round state
  ([ADR-0035](0035-slice-is-the-unit-of-execution.md)), the git state, and
  GitHub's pull-request and review state. Whether every one of `task.check`'s
  thirteen outcomes maps to a distinct recommendation is an implementation
  question the brief records as an open assumption.
- The oracle must answer for positions that are not task states at all — no
  task, no branch, a merged slice with slices remaining — since those are
  precisely the boundaries where the developer currently supplies the
  knowledge.
- A computed recommendation can be wrong in a new way: consistently and
  confidently. The brief records a discovery step for whether each boundary
  recommendation is worth stating before the obligation is made binding.
- `.codev/for-ai/ai-agent-guidelines.md` gains one rule and should lose more
  than it gains. Once the oracle exists, the protocol steps duplicated between
  it and `bundle/.claude/agents/orchestrator.md` are largely expressible as
  exit codes and recommendations, which the brief tracks as follow-up work.
- This decision does not touch authority. Merge, deployment, migration,
  publication, and rollout expansion remain human decisions, and the oracle
  recommends rather than acts.

## Revisit when

Adopters are observed routinely reading the oracle themselves rather than
receiving its recommendation through the agent, which would mean the
conversational surface is failing and a developer-facing form is doing real
work. Also revisit if an adapter proves unable to consult the oracle at every
turn cheaply enough for the obligation to hold.
