# Rubric

- **R1 — whitespace normalization:** `slugify` lowercases its input, removes
  leading and trailing whitespace, and replaces each internal run of whitespace
  with exactly one hyphen.
- **R2 — existing behavior:** existing hyphens are preserved and the change is
  limited to the requested helper without dependencies.
