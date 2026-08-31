---
title: Examples
description: Five worked scenarios, start to finish, from a cheminformatics codebase.
---

Five scenarios, start to finish. None of them are hypothetical shapes —
each is the kind of thing that actually happens in a cheminformatics
codebase. See the [Onboarding Guide](/CoDev/onboarding-guide/)
for the concepts these examples put to use.

## A bounded fix: the SMILES canonicalization gap

A pipeline's SMILES canonicalizer gets an uncommon tautomer/valence edge
case wrong — it's correct for the vast majority of structures and wrong for
one specific case a quick manual test never happens to hit. Two
chemically-identical compounds submitted by different vendors, differing
only in that one representation, canonicalize to different strings — and a
downstream dedup step silently treats them as two distinct compounds.

This never leaves **Build**. There's no shared contract to design and no
second developer to coordinate with — `build-change` frames the fix, grounds
it against the canonicalizer's existing tests, and adds one that pins the
edge case. A fast correctness check runs automatically once the diff
exists, confirming it matches the reported bug and nothing else moved. No
design document, no wave plan — for a change this size, that would be
ceremony the bug doesn't need.

## A feature that needs a decision first: reading InChI alongside SMILES

A collaborator's assay platform outputs InChI instead of SMILES — same
molecular information, different string representation, different library
support. The request sounds simple ("just read InChI too") but isn't: it
touches the pipeline's molecule-parsing abstraction, and getting that
abstraction wrong now means a third format later means another rewrite.

This starts in **Understand**: `define-product` frames the actual outcome
(read either format transparently, fail loudly on neither) and surfaces
that it's not size that makes this material — it's the shared interface.
That routes it into `design-solution`: what does a `read_molecule(input)`
call return regardless of input format, who owns validating a malformed
InChI string, and what happens to the two call sites that currently assume
SMILES. Only once that's settled does `build-change` implement it — informed
by a real contract instead of one parser's ad hoc assumptions.

## Splitting work across two developers: the compound-deduplication contract

A compound-intake pipeline needs two things built in parallel: canonicalizing
raw vendor SMILES into one agreed representation, and clustering
canonicalized compounds by fingerprint similarity to catch near-duplicates
across vendors. Different developers, real interdependency — the clustering
step needs to know exactly what shape a canonical compound record is before
either can write a line of code.

`plan-wave` exists for precisely this: it produces a wave plan
where the shared contract — the canonical SMILES, its source vendor, and the
fingerprint used for clustering, in one agreed representation — is decided
and fixture-tested *before* the two developers diverge, not discovered when
their branches collide. Each developer owns their component; the plan
records who reviews the other's work, since an owner never reviews their
own change. Skip this for the canonicalization-gap fix above; it would be
pure overhead for one person and one file.

## Catching a concurrency bug in review: the docking-score cache

A compound-screening pipeline scores each ligand against a target with a
docking tool, then caches the result by `(ligand_id, target_id)` so a
rerun doesn't redo expensive work. Under enough parallel docking workers,
two results for related ligands land close enough in time that a
non-atomic read-modify-write on the cache file corrupts an entry — flaky,
rare, and exactly the kind of thing a correctness-focused read misses.

This is what the outer loop's specialist review exists for. Once a pull
request is open, a dedicated concurrency reviewer examines the diff for
exactly this class of problem — shared state, non-atomic writes, ordering
assumptions — alongside, not instead of, the specialists checking
correctness, security, architecture, and rollout. The finding comes back
labeled `concurrency`, not buried in a general "looks fine" comment, and
you decide whether to fix it now or explicitly defer it with a reason.

## A style-catalog catch before the PR even opens: the swallowed parse error

A batch importer reads a large structure-data file of compounds and wraps
each record's parsing in a bare `except: continue`, so one malformed
molecule doesn't kill the whole import. It also means a *real* parsing
regression — a corrupted file, a library upgrade that changes error types —
silently skips records instead of failing loudly, and nobody notices until
the compound count looks wrong three pipelines downstream.

This is caught before a human ever sees the diff: an automatic style and
correctness-hazard gate runs immediately before every pull request opens,
and a bare `except` swallowing more than it should is exactly the kind of
finding it's built to catch. It reports back, the fix goes through one more
build round, and only a clean pass opens the PR — so the outer loop's
specialists spend their attention on judgment calls, not on a catalog-level
hazard a gate already caught.

## Deciding it's ready for real use: the toxicity-model rollout

A new machine-learned hepatotoxicity classifier is more accurate offline
than the rule-based filter it's meant to replace in a compound-screening
queue — but "more accurate offline" and "safe to trust on live batches" are
different claims. The team wants evidence, not hope, before the rule-based
filter goes away.

`launch-product` frames this as a staged rollout: the new model runs
alongside the existing filter on 10% of incoming batches first, both
verdicts are logged, and a defined disagreement rate is the threshold for
expanding to the next stage — not a calendar date. Rollback means routing
back to the rule-based filter alone, and that path is checked *before* the
rollout starts, not improvised if the numbers look wrong. Ship still stops
here for a human decision: CoDev assembles the readiness evidence, the
recommended stages, and the rollback plan — a person decides whether to
actually expand exposure.
