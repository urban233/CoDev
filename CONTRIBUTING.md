# Contributing

CoDev accepts focused changes with observable evidence.

1. Open an issue describing the user problem and expected behavior.
2. Keep installer behavior backwards compatible within a major version.
3. Add focused tests for important install, merge, drift, or migration behavior,
   favoring a few high-value integration tests over exhaustive unit coverage.
4. Run the commands in the README before requesting review.
5. Update the changelog when users or installed artifacts are affected.

Changes to bundled skills, agent policy, or workflow rules must also validate
the behavioral scenario catalog. The implementing AI cannot approve its own
change; use an independent human review and, for material behavior changes, a
fresh AI review as additional evidence.
