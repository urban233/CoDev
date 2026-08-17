# Phase A planning rubric

The actor must produce a grouped read-only Google Python Style remediation plan
for exactly `src/pyssa/controllers/delete_project_controller.py`. It must cover
multi-item imports, wildcard imports, tmp_ bindings, PascalCase/snake_case
naming, backticks and Sphinx class markup, summary/Args/Raises/Returns/Yields
punctuation, code-comment punctuation, and complete public/private docstrings.
It must distinguish checker-owned deterministic rules from actor judgment and
Ruff/pymake validation, preserve behavior and APIs, state exclusions, and end
exactly with `APPROVAL REQUIRED`. The fixture repository diff must be empty.
