# Skill Card: plan-wave

**Description:** Turns an accepted product or feature brief and any required design into a lightweight, team-profile-aware, rolling-wave delivery plan: waves, capability lanes, owners, independent reviewers, dependencies, and WIP limits. Details and readies only the current wave; later waves stay coarse until their own turn.

**Owner:** CoDev maintainers

**License / Terms of Use:** BSD-3-Clause (this repository's own `LICENSE`; matches this skill's `SKILL.md` frontmatter `license` field).

**Use Case:** Use when a team needs to coordinate multiple developers on related work, or a single developer needs to sequence a multi-wave feature without pre-detailing waves the evidence hasn't arrived for yet. Does not create a separate architecture or capacity bureaucracy -- that scope stays with `design-solution` and the plan itself stays lightweight.

**Deployment Geography for Use:** Not applicable -- runs locally inside the installing developer's own repository and toolchain; CoDev does not host, deploy, or operate this skill as a service.

**Requirements / Dependencies:** None beyond git and an authenticated OpenCode (or equivalent agent) invocation. Where the platform is Claude Code, `require_wave_shape.py` mechanically checks the rolling-wave discipline this skill's prose asks for; on other platforms the prose is the only enforcement.

**Known Risks and Mitigations:** Could produce process overhead disproportionate to the work -- mitigated by the explicit non-goal ("Do not create a separate architecture or capacity bureaucracy") and its focus on outcome-based waves over prediction. Could silently regress into pre-detailing every wave upfront under session pressure -- mitigated by the mechanical gate on Claude Code, and by the revisit checkpoint in step 1 requiring evidence from the previous wave before a new one is detailed.

**References:** This skill's own `SKILL.md`; `define-product`; `design-solution`; `build-change` (workflow-aware task slicing).

**Skill Output:** A wave plan: the current wave in detail, later waves as coarse outcomes, lanes or ready tasks, owners, reviewers, dependencies, and risks.

**Skill Version:** Versioned with the installed CoDev release (currently 0.3.0).

**Ethical Considerations:** Human retains authority for acceptance, merge, deployment, and publication (see `AGENTS.md`'s Human-AI Development Policy); this skill does not act autonomously beyond that boundary.
