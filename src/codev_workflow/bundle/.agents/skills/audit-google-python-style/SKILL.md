---
name: audit-google-python-style
description: Audit Python code against the Google Python Style Guide, produce a grouped read-only plan, and apply only an explicitly approved exact plan. Invoke only for an explicit Google Python Style audit request.
---

# Google Python Style audit

This skill is an explicit two-phase workflow. It never inspects, invokes, copies,
imports, or relies on an evaluation-only verifier or oracle script.

```mermaid
flowchart LR
 A[Phase A: audit] --> P[Grouped exact plan]
 P --> R[APPROVAL REQUIRED]
 R --> B[Phase B: bounded remediation]
 B --> C[Revalidate and report COMPLETED]
```

## Invocation boundary

Use only when the human explicitly requests this audit or invokes
`$audit-google-python-style`. Do not use it for ordinary reviews, linting, or
implementation tasks. Invocation is not permission to edit.

## Phase A: read-only audit and plan

Read repository instructions, configuration, generated-code policy, exceptions,
and working-tree state. Define the approved Python scope, including tests unless
explicitly excluded. Exclude dependencies, caches, build output, vendored or
generated code only with repository evidence. Run repository checks and then the
skill-owned supplemental checker:

```text
.agents/skills/audit-google-python-style/scripts/check_google_rules.py --root <approved-scope-root>
```

Use `pymake` wrappers when the repository provides them: `pymake lint`,
`pymake format dry_run=true`, and `pymake check_types`. If unavailable, report
that fact and use the repository's documented Ruff commands; never install
dependencies or claim an unavailable check passed.

The checker owns deterministic syntax, import, naming, markup, punctuation, and
documentation findings. The actor owns contextual judgment for exceptions,
resources, state, annotations, design, and consistency. Review these rule
families independently:

* Imports: one module or symbol per import statement; no wildcard imports.
* Naming: PascalCase classes; snake_case functions, methods, parameters, and
  variables; no `tmp_` bindings; preserve precise dunder/private names,
  uppercase constants, and exact AST visitor dispatch overrides.
* Documentation and comments: no backticks or `:class:` markup; period-ending
  summaries and descriptions; every public and private module, class, function,
  and method has a descriptive docstring; complete applicable `Args:` entries
  for every parameter form, direct-scope `Returns:`/`Yields:`, and direct-scope
  `Raises:` descriptions. Value returns inferred from non-None annotations
  require `Returns:` too. Named or qualified exception names match by either
  equivalent leaf or qualified form. Dynamic/factory raises require exactly a
  non-empty, period-ended `Exception:` entry; unrelated named entries fail.
* Comment punctuation is exempt only for exact shebang/encoding directives,
  conservative recognized leading license/header lines within lines 1–25, and
  exact fold, region, or symmetric separator markers. Markup is always checked;
  uncertain early comments are checked normally.

Produce a short grouped plan naming exact files, rule families, exact edits,
Ruff-assisted versus manual ownership, exclusions, behavior/API safeguards, and
post-approval validation. Do not edit, format-write, or apply fixes. End the
report exactly with `APPROVAL REQUIRED`.

## Phase B: approved remediation

Enter only after explicit human approval of the exact plan. Recheck the tree and
re-audit the approved scope; stop for changed inputs or a new decision. Apply
only approved style edits, preserving executable behavior, tests, public APIs,
dependencies, configuration, generated sources, and unrelated user changes.
Use Ruff's formatter or safe fixes only through the repository wrapper and only
when its complete target is approved; otherwise make targeted edits. Re-run the
repository checks and supplemental checker, run affected tests, inspect the
complete diff, and report exact commands, residual findings, changed files, and
the verdict `COMPLETED`, `PARTIALLY COMPLETED`, or `CLARIFICATION REQUIRED`.
Include approved-scope evidence from `git diff --name-only` and
`git diff --check`; the workflow owns scope and diff evidence, while the
checker owns only general Python style findings.

Never inspect, invoke, copy, import, or rely on evaluation-only verifier/oracle
scripts such as `check_audit.py`. The checker implementation must remain an
independent standard-library audit, not oracle-derived logic.

## Independent coverage boundary

Generalizable import, naming, documentation, comment, exclusion, and
supplemental review rules are independently owned by this skill's instructions,
matrix, and standard-library checker. The repository regression module
`tests/test_google_style_audit_rules.py` is maintenance evidence and is not
installed into target repositories. Fixture-only target path allowlists, Git
status enforcement, and exact harness success text belong only to the
evaluation harness and are intentionally never replicated by this skill.
