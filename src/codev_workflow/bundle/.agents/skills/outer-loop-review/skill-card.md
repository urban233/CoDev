# Skill Card: outer-loop-review

**Description:** Takes a task with an open pull request through CI gating, five-specialist review, human-triaged correction, and a merge-ready state.

**Owner:** CoDev maintainers

**License / Terms of Use:** BSD-3-Clause (this repository's own `LICENSE`; matches this skill's `SKILL.md` frontmatter `license` field).

**Use Case:** Use when a pull request is open and needs outer-loop review, or when a developer explicitly asks to act on a PR's existing review comments instead of running a fresh specialist pass. Not for a PR's first, inner-loop review, for a working-tree or branch review with no open pull request, or for reading CI results with no correction loop attached.

**Deployment Geography for Use:** Not applicable -- runs locally inside the installing developer's own repository and toolchain; CoDev does not host, deploy, or operate this skill as a service.

**Requirements / Dependencies:** The `pr-review` and `github-actions-ci-results` skills, whose fetch scripts and CI-inspection this skill reuses rather than reimplementing. An authenticated `gh` CLI, or `GITHUB_TOKEN`/`GH_TOKEN` directly.

**Known Risks and Mitigations:** Dispatching five specialist reviewers spends a real model call per specialist -- mitigated by an explicit, per-run selection question the developer answers before any dispatch, never a default of "all" and never inferred from the diff alone. Could be mistaken for something that can merge or approve on its own -- mitigated by ending at `codev git mark-ready`, which requests human review, and never calling merge, approve, or release authority itself (see `AGENTS.md`).

**References:** This skill's own `SKILL.md`; `AGENTS.md`'s Human-AI Development Policy; `docs/adr/0021-opencode-specialist-dispatch-permission-gate.md`; `docs/adr/0044-lead-is-not-an-agent.md`.

**Skill Output:** A pull request taken to `ok_machine_review_complete` or `ok_machine_review_complete_with_deferrals` and marked ready for human review, with a recorded specialist selection, merged findings, and a coverage manifest.

**Skill Version:** Versioned with the installed CoDev release (currently 0.6.0).

**Ethical Considerations:** Human retains authority for triage, waiver, acceptance, and merge (see `AGENTS.md`'s Human-AI Development Policy); this skill does not act autonomously beyond that boundary.
