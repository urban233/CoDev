# Google Python Style audit matrix

| Rule family | Owner | Severity | Exemptions and evidence |
| --- | --- | --- | --- |
| Syntax and unreadable source | supplemental checker | violation | None; standard library only. |
| One module/symbol per import; no wildcard imports | supplemental checker | violation | None. |
| PascalCase classes; snake_case functions/methods/parameters/bindings; no tmp_ | checker plus actor | violation | Dunder/private names, uppercase constants, and exact AST visitor overrides are documented exceptions. |
| Docstrings and summaries | supplemental checker plus actor | violation | Modules, classes, public/private functions and methods; summaries and logical section descriptions end with periods. |
| Args completeness | supplemental checker | violation | Positional-only, positional, keyword-only, *args, and **kwargs; self/cls excluded. |
| Returns/Yields completeness | supplemental checker | violation | Direct current scope plus non-None value annotations; nested scopes excluded. |
| Raises completeness and matching | supplemental checker | violation | Direct current scope only; named/qualified forms match symmetrically by leaf or qualified name. Dynamic raises require exactly `Exception:` with nonempty period-ended text. |
| Forbidden markup | supplemental checker | violation | Backticks and `:class:` are always checked, including headers. |
| Comment punctuation | supplemental checker | violation | Only conservative recognized leading license/header lines within lines 1–25, exact shebang/encoding directives, and exact fold/region/symmetric separator markers are exempt. |
| Existing supplemental review rules | supplemental checker | review/violation | Type comments, TODO format, Pylint suppressions, continuations, broad exceptions, assertions, lambdas, mutable state, legacy aliases, nested definitions, long lines/functions, and syntax/readability findings. |
| Exclusions | supplemental checker | policy | Case-insensitive `.agents`, caches, build output, generated, vendor, site-packages, and related excluded components. |
| Ruff lint and formatting | pymake/Ruff wrapper | report separately | Never run Pylint; report unavailable wrappers honestly. |
| Types and contextual design | actor judgment | review | Exceptions, state, resources, APIs, and behavior require context. |

Phase A is read-only and ends `APPROVAL REQUIRED`. Phase B is limited to the
human-approved exact plan. The actor must never inspect, invoke, copy, import, or
rely on evaluation-only verifier/oracle scripts. `check_audit.py` belongs only to
the Phase B harness.

## Independent coverage boundary

| Generic rule or evidence | Owner | Boundary |
| --- | --- | --- |
| Imports, naming, docstrings, comments, exclusions, and supplemental reviews | Skill checker/instructions | Independently represented here and in the skill-owned checker. |
| Approved scope and recheck evidence | Workflow | Use `git diff --name-only` and `git diff --check` in Phase B; do not reproduce fixture allowlists. |
| Fixture target pathname, Git status allowlist, exact success text | Evaluation harness only | Fixture mechanics; intentionally never inspected, copied, or used by the skill. |
| `tests/test_google_style_audit_rules.py` | Repository maintenance | Regression evidence only; not installed in target repositories. |
