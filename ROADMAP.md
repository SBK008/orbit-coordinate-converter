# Roadmap

Where the Coordinate Converter is headed. Plans can change, and versions follow
[semantic versioning](https://semver.org): **patch** (1.3.**1**) for bug fixes,
**minor** (1.**4**.0) for new features, **major** (**2**.0.0) for changes that
break existing use.

Each version below has a [milestone](https://github.com/SBK008/orbit-coordinate-converter/milestones) on GitHub with one issue per item,
so you can follow progress there. Have an idea or need? [Open an issue](https://github.com/SBK008/orbit-coordinate-converter/issues/new).

## Done

- **1.2.x:** pip install, in-app updates, NAIRAS trajectory export, tests on
  Linux, macOS, and Windows with GitHub Actions, read-only workflow token,
  branch protection on `main`

## 1.3.0: Secure updates (released)

- [x] Updater installs only published releases, never untagged code on `main`
- [x] Every downloaded file checked against the release's SHA-256 checksums
- [x] Release tag must match the app version, and must be on `main`
- [x] Downloads are HTTPS only from GitHub, and size-limited
- [x] Output temp files can't be redirected by a planted symlink

## 1.4.0: Supply chain and distribution (in review)

[Track progress](https://github.com/SBK008/orbit-coordinate-converter/milestone/1)

- [x] Publish to PyPI with trusted publishing, so install is `pip install orbit-converter`
- [x] Sign releases with an offline minisign key, checked by the updater, plus
      Sigstore attestations from the release workflow
- [x] Pin GitHub Actions to commit SHAs and turn on Dependabot
- [x] Set version bounds on dependencies
- [x] `CHANGELOG.md`

## 1.5.0: Standalone apps for Windows, macOS, and Linux

[Track progress](https://github.com/SBK008/orbit-coordinate-converter/milestone/2)

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
- [ ] Free code signing, so fewer systems warn users:
      - Windows: signed through the SignPath Foundation, which signs
        open-source projects for free
      - macOS: Apple's notarization requires a paid account, so the app is
        ad-hoc signed and ships with steps for opening it the first time
      - Linux: AppImages are covered by the release's Sigstore signatures
- [ ] Download page in the README with one button per system
- [ ] A modern look for the desktop app, with light and dark mode
- [ ] Full keyboard use and readable contrast, for accessibility
- [ ] A docs site on GitHub Pages with screenshots and how-to guides

## 1.6.0: Features

[Track progress](https://github.com/SBK008/orbit-coordinate-converter/milestone/3)

- [ ] More output formats, in the app and with a `--output-format` option:
      - **KML:** open a ground track or flight path as a 3D line in Google Earth
      - **GeoJSON:** for maps and GIS tools like QGIS
      - **Excel (.xlsx):** opens directly in Excel; Excel's 1,048,576-row limit
        means large files get split across sheets or a warning
      - **JSON:** for other programs and scripts
      - Written in chunks like today's output, so large files still use little memory
      - Excel support as an optional install (`pip install "orbit-converter[excel]"`)
        so the base app stays small
- [ ] XML OEM input (only text/KVN is supported today)
- [ ] Reverse conversion: latitude, longitude, altitude back to ECEF X/Y/Z
- [ ] More orbit inputs, such as TLEs, if users need them
- [ ] Fuzz testing for the OEM and CSV parsers
- [ ] Easier to use: drag and drop files, a preview of the first output rows,
      a map preview of the trajectory, and plain-language error messages that
      say how to fix the problem
- [ ] A new `orbit-convert` command with subcommands. `xyz-to-lla` keeps
      working but warns that it will be removed in 2.0

## 2.0.0: Redesign

[Track progress](https://github.com/SBK008/orbit-coordinate-converter/milestone/4)

Breaking changes are saved up for one release, so users only adjust once.
Each one gets a warning in a 1.x release first.

- [ ] One command, `orbit-convert`, replaces `xyz-to-lla`:
      ```
      orbit-convert to-lla input.oem output.csv --format kml
      orbit-convert to-ecef input.csv output.csv
      ```
- [ ] The code moves into an `orbit_converter` package with a clean import
      (`from orbit_converter import to_lla`)
- [ ] A redesigned app, either:
      - **Qt (PySide6):** a professional desktop app on every system, or
      - **Browser version:** nothing to install, and files never leave your
        computer
- [ ] An "Upgrading to 2.0" guide showing old usage next to new

## Ongoing

- Test coverage report and badge
- Linting (`ruff`) in CI
- Split `xyz_to_lla.py` into smaller modules, keeping
  `from xyz_to_lla import xyz_to_lla` working
