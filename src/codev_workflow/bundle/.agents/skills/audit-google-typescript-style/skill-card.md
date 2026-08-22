# Skill Card: audit-google-typescript-style

**Description:** Audits TypeScript and TSX code against the Google TypeScript Style Guide using GTS plus supplemental analysis, then proposes a grouped remediation plan for explicit human approval before modifying any approved source file.

**Owner:** CoDev maintainers

**License / Terms of Use:** BSD-3-Clause (this repository's own `LICENSE`; matches this skill's `SKILL.md` frontmatter `license` field).

**Use Case:** Invoke only when a developer explicitly requests this audit or invokes `$audit-google-typescript-style`. Not for ordinary code reviews, pull-request reviews, linting, or implementation tasks.

**Deployment Geography for Use:** Not applicable -- runs locally inside the installing developer's own repository and toolchain; CoDev does not host, deploy, or operate this skill as a service.

**Requirements / Dependencies:** GTS (Google TypeScript Style); git; an authenticated OpenCode (or equivalent agent) invocation.

**Known Risks and Mitigations:** Could be reached for as a general-purpose code reviewer, which it is not -- mitigated by the frontmatter's explicit scope exclusion and by requiring explicit invocation. Its planning phase is read-only by design until the human explicitly approves the proposed plan.

**References:** This skill's own `SKILL.md`.

**Skill Output:** A short, grouped remediation plan for human approval; once approved, edits to the specific approved source files.

**Skill Version:** Versioned with the installed CoDev release (currently 0.2.4).

**Ethical Considerations:** Human retains authority for acceptance, merge, deployment, and publication (see `AGENTS.md`'s Human-AI Development Policy); this skill does not act autonomously beyond that boundary.
