# PR review: GitHub CLI setup

The installed `pr-review` skill reviews an existing GitHub Pull Request and can prepare
validated inline comments for the exact PR head. It uses the GitHub CLI credential store
by default, so agents do not need to read or print a token.

## Install and authenticate GitHub CLI on Windows

Install the official package from PowerShell with WinGet:

```powershell
winget install --id GitHub.cli --source winget
```

Open a new Windows Terminal window after installation, then verify and sign in:

```powershell
gh --version
gh auth login --web
gh auth status --active
```

Choose `GitHub.com`, the HTTPS protocol, and the browser login flow. `gh` stores the
credential using the Windows credential store when available. See the
[official Windows installation guide](https://github.com/cli/cli/blob/trunk/docs/install_windows.md)
and [`gh auth login` documentation](https://cli.github.com/manual/gh_auth_login).

Run the PR publisher in dry-run mode first:

```powershell
python .agents\skills\pr-review\scripts\publish_review.py `
  --repo OWNER/REPO `
  --pr 123 `
  --review review.json
```

The publisher automatically uses authenticated `gh api` when no `GITHUB_TOKEN` or
`GH_TOKEN` is set. Use `--auth gh` to require that backend or `--auth token` for headless
environments that provide a token variable. Add `--publish` only after explicitly
authorizing a GitHub review, and use `--submit comment` only when it should be submitted
immediately.

If a desktop agent does not inherit the Windows machine PATH, the publisher also checks the
standard `C:\Program Files\GitHub CLI\gh.exe` location. For a custom installation, set
`CODEV_GH_PATH` to the full path of `gh.exe`.

## Using an already-authenticated `gh` credential from another CLI

To copy the already-authenticated `gh` credential into `GH_TOKEN` for the current
PowerShell process and the CLI started from it, dot-source the bundled helper:

```powershell
. .agents\skills\pr-review\scripts\set-github-token.ps1
```

The helper calls `gh auth token` without printing the result and does not persist it. The
`gh` credential must be valid in the same process context. This is useful for a CLI that
needs `GH_TOKEN`; launch that CLI from the shell where the helper has been dot-sourced. Do
not put the token in a repository file or command-line argument.

One-line equivalent:

```powershell
$g=Get-Command gh -ErrorAction SilentlyContinue;if($g){$p=$g.Source}else{$p='C:\Program Files\GitHub CLI\gh.exe'};$env:GH_TOKEN=(& $p auth token --hostname github.com 2>$null).Trim()
```

## Fetching a PR's full context

Fetch the complete GitHub PR context before asking an agent to review it:

```powershell
python .agents\skills\pr-review\scripts\publish_review.py `
  --repo OWNER/REPO `
  --pr 123 `
  --fetch `
  --output-dir .codev\pr-review\123
```

This writes PR metadata, the patch, changed files, commits, reviews, comments, and check
runs. Use repeated `--include metadata`, `--include diff`, or other parts to fetch a
smaller set.

## Running the review

Once fetched, the same command is available directly inside Claude Code:

```text
/pr-review repo=OWNER/REPO pr=123
```

Claude Code's project-specific commands live under `.claude/commands`, so this command is
versioned with the repository and appears in Claude Code's own `/` command list. Junie and
Antigravity don't get a `pr-review` command — see
[ADR-0031](adr/0031-drop-codex-narrow-junie-and-antigravity-to-an-edit-assistant.md) for
why. On any platform, describing the PR number and repository in plain language and asking
for the `pr-review` skill works the same way.
