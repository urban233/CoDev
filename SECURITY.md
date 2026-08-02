# Security Policy

## Supported versions

Security fixes are provided for the latest minor release of the current major
version. Consumer repositories should pin an explicit CoDev version and
review update diffs before adoption.

## Reporting

Do not disclose a suspected vulnerability in a public issue. Use the GitHub
repository's private vulnerability reporting feature after the project is
published, or contact the repository owner through its documented private
channel.

Include the affected version, operating system, target layout, reproduction,
and potential impact. Never include production secrets or proprietary source.

## Trust model

CoDev writes instruction and configuration files into developer repositories.
Treat every bundle update like a source-code dependency update: pin versions,
verify release provenance, inspect the diff, run validation, and require human
review. CoDev does not execute target-project build or deployment commands.

