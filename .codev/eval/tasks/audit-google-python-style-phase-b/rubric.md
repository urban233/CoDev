# Phase B remediation rubric

The actor must change only `src/pyssa/controllers/delete_project_controller.py`
and only the approved import, wildcard, naming, markup, documentation, comment
punctuation, and formatting categories. Seeded naming changes `helper_panel` to
`HelperPanel` and `FormatData` to `format_data` are approved style remediation.
Public/API preservation is satisfied when compatibility aliases or equivalent
forwarding compatibility preserve existing external names and behavior; the
judge must not reject a rename merely because the original spelling disappears
from the diff. Generated `__pycache__`, `.pyc`, and standard build/cache output
are ignored for target-only scope, matching the aligned verifier and skill
exclusions; unrelated source, configuration, test, or verifier changes remain
disallowed. The target must be clean under the skill's supplemental checker.
All other approved categories remain required, including complete applicable Args,
Returns/Yields, and Raises sections; qualified and leaf exception names are
equivalent, while dynamic raises require exactly one non-empty, period-ended
`Exception:` entry. The actor must provide judgeable evidence from the output,
diff, and verifier of the target-only scope, checker-clean target, preserved
behavior/API, `git diff --check`, and completion.
