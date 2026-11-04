# Roadmap

Where the Coordinate Converter is headed. Plans can change, and versions follow
[semantic versioning](https://semver.org): **patch** (1.3.**1**) for bug fixes,
**minor** (1.**4**.0) for new features, **major** (**2**.0.0) for changes that
break existing use.

Have an idea or need? Open an issue.

## Done

- **1.2.x:** pip install, in-app updates, NAIRAS trajectory export, tests on
  Linux, macOS, and Windows with GitHub Actions, read-only workflow token,
  branch protection on `main`

## 1.3.0: Secure updates (in review)

- [x] Updater installs only published releases, never untagged code on `main`
- [x] Every downloaded file checked against the release's SHA-256 checksums
- [x] Release tag must match the app version, and must be on `main`
- [x] Downloads are HTTPS only from GitHub, and size-limited
- [x] Output temp files can't be redirected by a planted symlink

## 1.4.0: Supply chain and distribution

- [ ] Publish to PyPI with trusted publishing, so install is `pip install coordinate-converter`
- [ ] Sign releases (for example with Sigstore) so the updater can verify who
      published them, not just that files arrived intact
- [ ] Pin GitHub Actions to commit SHAs and turn on Dependabot
- [ ] Set version bounds on dependencies
- [ ] `CHANGELOG.md`

## 1.5.0: Standalone apps for Windows, macOS, and Linux

Download, double-click, done. No Python needed.

- [ ] Build the desktop app for each system with PyInstaller (or Briefcase)
      - Windows: `.exe` installer
      - macOS: `.app` in a `.dmg`, for both Apple Silicon and Intel
      - Linux: AppImage
- [ ] Build all three in GitHub Actions whenever a release is published, and
      attach them to the release with their checksums
- [ ] Teach the updater to recognize a standalone app and offer the new
      installer, since it can't swap `.py` files inside a packaged app
- [ ] Bundle the PROJ and IERS data the converter needs, so the app works offline
- [ ] Code signing, so Windows SmartScreen and macOS Gatekeeper don't warn users:
      - macOS: Apple Developer ID and notarization (Apple Developer Program, $99/year)
      - Windows: a code signing certificate or Azure Trusted Signing
      - Until then, the apps ship unsigned, with instructions for opening them
- [ ] Download page in the README with one button per system

## 1.6.0: Features

- [ ] More output formats, in the app and with a `--output-format` option:
      - **KML:** open a ground track or flight path as a 3D line in Google Earth
      - **GeoJSON:** for maps and GIS tools like QGIS
      - **Excel (.xlsx):** opens directly in Excel; Excel's 1,048,576-row limit
        means large files get split across sheets or a warning
      - **JSON:** for other programs and scripts
      - Written in chunks like today's output, so large files still use little memory
      - Excel support as an optional install (`pip install "coordinate-converter[excel]"`)
        so the base app stays small
- [ ] XML OEM input (only text/KVN is supported today)
- [ ] Reverse conversion: latitude, longitude, altitude back to ECEF X/Y/Z
- [ ] More orbit inputs, such as TLEs, if users need them
- [ ] Fuzz testing for the OEM and CSV parsers

## Ongoing

- Test coverage report and badge
- Linting (`ruff`) in CI
- Split `xyz_to_lla.py` into smaller modules, keeping
  `from xyz_to_lla import xyz_to_lla` working
