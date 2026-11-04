# Security Policy

## Supported versions

Only the latest release gets security fixes. Use **Check for updates** in the app, or `pip install --upgrade`, to stay current.

## Reporting a vulnerability

Please report security problems privately, not in a public issue:

1. Go to the **Security** tab of this repository.
2. Click **Report a vulnerability**.

Include what you found, how to reproduce it, and what an attacker could do with it. You can expect a reply within a week. Once a fix is released, you will be credited in the release notes unless you prefer not to be.

## How the updater works

The in-app updater downloads new code, so here is exactly what it trusts and checks:

- **Releases only:** it asks GitHub for the latest published release. Drafts, pre-releases, and untagged changes on `main` are never installed.
- **Source:** files are downloaded only over HTTPS from `api.github.com`, `raw.githubusercontent.com`, and the release's own download link. Certificate verification is never turned off.
- **Fixed file list:** only the `.py` files named in `updater.py` are downloaded, exactly as they were at the release tag. Nothing else is fetched or run.
- **Checksums:** every file must match the SHA-256 hash in the release's `SHA256SUMS` file, which the release workflow generates from the tagged code.
- **Version check:** the release tag must look like a version number (`v1.3.0`) and must match `__version__` inside the downloaded code.
- **All or nothing:** every file must download, match its checksum, and be valid Python before any file is replaced. Old versions are kept as `.bak` files.
- **No downgrades:** an update is installed only if its version number is higher than the one running.
- **pip installs are left alone:** copies installed with pip are never overwritten. pip handles those updates.

**Limitation:** the checksums come from the same GitHub repository as the code. They catch damaged, partial, or swapped downloads and make sure you get exactly the files that were released, but they are not a signature. Someone who took over the maintainer's GitHub account could publish a malicious release with matching checksums. If you need stronger guarantees, install a specific release with pip and review changes before upgrading.

## Scope

This tool reads local CSV and OEM files and writes local output files. It does not open network ports, collect data, or send anything anywhere, except the update check, which only reads public files from GitHub.

Input files are parsed as data and never executed. Problems worth reporting include a crafted input file that causes code execution or writes outside the chosen output path, or any way to make the updater install code from somewhere other than this repository.
