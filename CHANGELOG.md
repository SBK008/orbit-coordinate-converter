# Changelog

What changed in each release, newest first. Release dates are on the
[releases page](https://github.com/SBK008/orbit-coordinate-converter/releases).
Versions follow [semantic versioning](https://semver.org).

## 1.5.0

### Added
- **Only the first N points:** a new box in the app's Output section, and
  `--limit N` on the command line, writes just the first N points and stops
  reading the rest of the file. Works for CSV, OEM, and NAIRAS output. With a
  NAIRAS time step, it counts the points that are kept. Blank or 0 keeps every
  point, as before.

## 1.4.1

### Fixed
- The desktop app could overwrite the input file when the output name differed
  from it only in letter case (like `Orbit.oem` and `orbit.oem`), which is the
  same file on Windows and macOS. The app now runs the same same-file check as
  the command line.
- Choosing a folder as the output now gives a clear message before converting,
  instead of a Python error after the whole file was read.
- OEM data lines with `nan`, `inf`, or out-of-range numbers are now refused
  with the line number, the same as CSV input. They used to be written out as
  empty latitude, longitude, and altitude.
- A NAIRAS time step of `nan` or `inf` no longer crashes, and a step under one
  millisecond is refused instead of quietly keeping every point.
- Output file permissions are worked out once at startup, so a conversion can
  no longer briefly change the process umask while the updater is writing
  files.

### Changed
- The README links the zip download to the latest release, not the newest
  code on `main`, and has a new pitch, badges, and sections on verifying and
  citing releases.
- Added `CITATION.cff`, so GitHub shows a "Cite this repository" button.
- Fixed the Dependabot config, which GitHub had rejected, so Python package
  updates are proposed again.

## 1.4.0: Supply chain and distribution

### Added
- **Install from PyPI:** `pip install orbit-converter`. The commands are still
  `coordinate-converter` (desktop app) and `xyz-to-lla` (command line).
- **Signed releases, two ways:**
  - The maintainer signs each release's `SHA256SUMS` with an offline
    [minisign](https://jedisct1.github.io/minisign/) key. The updater won't
    install a release without a valid signature that names its tag, so someone
    who takes over the GitHub account can't push an update to users.
  - The release workflow signs `SHA256SUMS` and the PyPI packages with
    Sigstore (GitHub artifact attestations). Check them with
    `gh attestation verify`. See [SECURITY.md](SECURITY.md).
- PyPI packages are published with trusted publishing, so there is no API
  token to steal, and PyPI shows where each file was built.
- Tests run against the oldest supported dependency versions, and every pull
  request builds and checks the PyPI packages.

### Changed
- Dependencies have tested version ranges (for example `numpy>=1.24,<3`), so a
  breaking upstream release can't reach users before it's tested.
- New dependency: `cryptography`, used to check release signatures. If you
  installed from a zip, run `pip install -r requirements.txt` once so updates
  keep working.
- GitHub Actions are pinned to commit SHAs, and Dependabot proposes updates.

### Upgrading a pip install from 1.3.0 or earlier
Older pip installs came from GitHub under the name `coordinate-converter`.
Switch to the PyPI name once:

```
pip uninstall coordinate-converter orbit-converter
pip install orbit-converter
```

## 1.3.0: Secure updates

### Changed
- The updater installs only the latest published release, never untagged code
  on `main`.
- Every downloaded file is checked against the release's `SHA256SUMS`.
- The release tag must be a version number, match `__version__`, and be on
  `main`.
- Downloads are HTTPS only, from GitHub's own hosts (redirects included), and
  capped at 5 MB.

### Fixed
- Converter temp files are created with `mkstemp`, so a planted symlink can't
  redirect output.

### Added
- A release workflow that checks the tag and attaches `SHA256SUMS`.

## 1.2.2

### Changed
- Requires Python 3.11 or newer.
- Tests run on Linux, macOS, and Windows with GitHub Actions.
- The workflow token is read-only.

## 1.2.1

### Added
- NAIRAS trajectory export for NASA's NAIRAS radiation model on CCMC
  Runs-on-Request.
- Automated tests.

### Fixed
- An accuracy fix in the conversion.

Versions before 1.2.1 were not published as releases.
