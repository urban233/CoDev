# Short-Form Voice Reference

For the one-line and one-sentence text an agent writes from scratch into
a GitHub artifact: a pull request title, an issue's opening sentence, a
wave-plan outcome or task-row sentence. Not for the long-form documents
`writing-style.md` covers -- a specification, brief, design, or plan --
and not for code or commit messages. Read the section below for the text
you are about to write; the whole file is short enough to read once.

The reader is whoever scans a GitHub issue list, a pull request list, or
a wave-plan table looking for what changed -- often skimming many at
once, not reading closely. Plain, specific, human language wins there,
the same way a good commit subject line wins over a vague one.

## Pull request titles

State the change's user-visible effect in plain English, in the imperative
mood, the way you would describe it out loud to a teammate. Leave out
this repository's internal vocabulary -- `slice`, `round`, a task ID, a
wave row ID -- from the title itself; that traceability information
belongs in the pull request body's tracking line, which every CoDev pull
request already carries.

- Bad: `T-042: implement cache fix per plan`
- Good: `Fix stale cache invalidation on logout`
- Bad: `W-01: Slice 2 - wire up the reviewer dispatch`
- Good: `Dispatch specialist reviewers in parallel`
- Bad: `Round 3 fixes for outer loop review findings`
- Good: `Stop double-counting review-dimension coverage`

## Issue opening sentence

Before any structured field (`Design doc:`, `Containment:`, `Slices:`,
and so on), write one plain-English sentence describing what will exist
once this issue is done, in terms the reader already understands -- not
the internal name of the component you will touch. Most readers,
including a teammate returning to the project after a gap, will read this
sentence and skim past the rest.

- Bad: "Refactor the `_render_pr_template` helper."
- Good: "Pull requests will show one plain sentence explaining what
  changed, before the coverage checklist."
- Bad: "Add framing field to task template."
- Good: "A new issue will open with a plain-English summary a teammate
  can read without opening the linked design doc."

## Wave-plan prose

Name the actual user, action, and object for this feature -- never reuse
`plan-wave`'s own worked example ("internal user completes the primary
workflow") verbatim. That example illustrates the *shape* of a good
outcome statement; it is not itself a sentence to paste into a real plan.
If the real outcome sentence would read identically to that example with
only the feature name swapped in, it is too generic -- name the specific
action the specific user takes.

- Bad: "Outcome: internal user completes the primary workflow."
- Good: "Outcome: a developer opens a pull request and sees a plain-English
  summary instead of a coverage checklist."
- Bad: "Task: implement validation logic for the wave shape checker."
- Good: "Task: `codev wave check` rejects a plan that details a later
  wave before its current wave is accepted."

## Self-check before writing

- Would you say this sentence out loud to a teammate at standup? If it
  only reads naturally as a status-report fragment, rewrite it.
- Does removing every internal name (`slice`, `round`, a task or row ID)
  still leave a complete, meaningful sentence? If not, the sentence is
  describing CoDev's process, not the change itself.
- Could this exact sentence be pasted into an unrelated pull request,
  issue, or wave plan without anyone noticing? If yes, it is too generic
  to be the actual sentence -- name the specific thing that changed.
