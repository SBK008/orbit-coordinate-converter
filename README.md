# Orbit Coordinate Converter

[![tests](https://github.com/SBK008/orbit-coordinate-converter/actions/workflows/tests.yml/badge.svg)](https://github.com/SBK008/orbit-coordinate-converter/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/orbit-converter)](https://pypi.org/project/orbit-converter/)
[![Python](https://img.shields.io/pypi/pyversions/orbit-converter)](https://pypi.org/project/orbit-converter/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/SBK008/orbit-coordinate-converter/blob/main/LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23986346.svg)](https://doi.org/10.5281/zenodo.23986346)

Convert Earth-centered (ECEF) X/Y/Z coordinates and CCSDS OEM orbit files to WGS84 latitude, longitude, and altitude. Includes a desktop app and a command-line tool, and handles files with millions of points.

```
pip install orbit-converter
xyz-to-lla orbit.oem output.csv
```

## Why use this

- **No code needed.** Point it at a CSV or OEM file and get latitude, longitude, and altitude back. Libraries like pyproj and Astropy can do the math, but you'd still write the file reading, frame rotation, and chunking yourself.
- **Space-fixed frames handled.** EME2000, GCRF, ICRF, and TEME positions are rotated to Earth-fixed at each epoch before converting.
- **Ready for NAIRAS.** Exports the exact trajectory format NASA's NAIRAS radiation model expects on CCMC Runs-on-Request, checked byte for byte against a real NASA file.
- **Any file size.** Tested on 20 million rows (1 GB) with flat memory use.
- **Free and verifiable.** MIT licensed, and every release is signed. See [Verifying a release](#verifying-a-release).

## Features

- **Accurate at any altitude:** within a micrometer from the surface out past GEO.
- **CSV input:** any CSV with X, Y, Z columns in meters. Your other columns are kept exactly as they were.
- **CCSDS OEM input:** text (KVN) orbit files in Earth-fixed or space-fixed frames. Space-fixed positions are rotated to Earth-fixed at each epoch.
- **Epoch output** as written in the file, as Gregorian calendar dates, or as Modified Julian Dates.
- **Comma or space separated output.**
- **NAIRAS trajectory export:** OEM files can be saved in the exact trajectory format used by NASA's NAIRAS radiation model on CCMC Runs-on-Request.
- **Large files:** processed in chunks, so memory stays flat. Tested on a 1 GB, 20 million row CSV.
- **Safe writes:** a failed or stopped run never leaves a half-written output file.
- **Signed updates:** the app installs only published releases, and checks every file against SHA-256 checksums signed with the maintainer's offline key.

See the [roadmap](https://github.com/SBK008/orbit-coordinate-converter/blob/main/ROADMAP.md) for what's coming next.

## Install

**Option 1: pip (recommended)**

Requires Python 3.11 or newer.

```
pip install orbit-converter
```

This installs the dependencies and two commands:

- `coordinate-converter` opens the desktop app
- `xyz-to-lla` runs the command-line tool

To update:

```
pip install --upgrade orbit-converter
```

Installed with pip before version 1.4.0? That copy was registered under an older name, so switch over once:

```
pip uninstall coordinate-converter orbit-converter
pip install orbit-converter
```

**Option 2: download the zip**

1. Open the [latest release](https://github.com/SBK008/orbit-coordinate-converter/releases/latest), download **Source code (zip)** under **Assets**, and unzip it. (The green **Code > Download ZIP** button gives the newest code on `main`, which may not be released yet.)
2. Install the dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Run the app:
   ```
   python converter_gui.py
   ```

To update, click **Check for updates** in the app. It installs the latest release only after checking its signature and every file's checksum.

### Mac users

1. Install Python from [python.org](https://www.python.org/downloads/macos/) (3.11 or newer).
2. In **Applications > Python**, double-click **Install Certificates.command**.
3. Open **Terminal** (Cmd+Space, type "Terminal") and run:
   ```
   pip3 install orbit-converter
   ```
4. Start the app any time by typing this in Terminal:
   ```
   coordinate-converter
   ```

Keep Terminal open while the app is running.

**If something goes wrong:** close Terminal, open a new one, and try again. If it still doesn't work, make sure you installed Python from python.org (not Homebrew), then [open an issue](https://github.com/SBK008/orbit-coordinate-converter/issues).

## Desktop app

1. Choose an input file (`.csv`, `.oem`, or `.txt`).
2. Pick the options:
   - **OEM files:** epoch format, and fast mode for space-fixed frames
   - **CSV files:** the names of your X, Y, and Z columns
   - **Output:** comma separated, space separated, or NAIRAS trajectory, whether to include column names, and **Only the first ___ points** if you want just the start of the file
3. Choose where to save and click **Convert**.

## Command line

```
# CSV
xyz-to-lla input.csv output.csv
xyz-to-lla input.csv output.csv --x X --y Y --z Z

# OEM
xyz-to-lla orbit.oem output.csv
xyz-to-lla orbit.oem output.csv --time-format mjd
xyz-to-lla orbit.oem output.csv --fast
xyz-to-lla orbit.txt output.csv --format oem

# Space separated, no header line
xyz-to-lla orbit.oem output.txt --separator space --no-header

# NAIRAS trajectory, one point per minute
xyz-to-lla orbit.oem trajectory_1.txt --nairas --step 60

# Only the first 600 points
xyz-to-lla orbit.oem trajectory_1.txt --nairas --limit 600
```

If you downloaded the zip, use `python xyz_to_lla.py` in place of `xyz-to-lla`.

| Option | What it does |
|---|---|
| `--format auto\|csv\|oem` | Input type. `auto` treats `.oem` files as OEM and everything else as CSV. |
| `--x`, `--y`, `--z` | CSV column names (default `x`, `y`, `z`). |
| `--time-format original\|gregorian\|mjd` | How OEM epochs are written. |
| `--fast` | Faster rotation for space-fixed OEM frames, within 0.05 mm of exact. |
| `--separator comma\|space` | Output column separator. |
| `--no-header` | Leave out the column names line (or the `#` comment lines with `--nairas`). |
| `--nairas` | OEM only: write a NAIRAS trajectory file. |
| `--step SECONDS` | With `--nairas`: keep one point per this many seconds (default 0 keeps all). |
| `--limit N` | Write only the first N points (default 0 keeps all). |
| `--chunksize N` | Rows processed at a time. |
| `--version` | Show the version. |

## Output

**CSV input:** your original columns, plus `lat`, `lon`, `alt`.

**OEM input:** `object, epoch, time_system, x_ecef_m, y_ecef_m, z_ecef_m, lat, lon, alt`

Latitude and longitude are in degrees. Altitude is meters above the WGS84 ellipsoid. In space separated output, empty values are written as `NaN` and text containing spaces is put in quotes.

## Supported OEM files

| Field | Supported |
|---|---|
| Format | Text (KVN). XML is not supported. |
| `CENTER_NAME` | `EARTH` |
| `REF_FRAME` | Earth-fixed: `ITRF*`, `EFG`, `ECEF`. Space-fixed: `EME2000`/`J2000`, `GCRF`, `ICRF`, `TEME`. |
| `TIME_SYSTEM` | `UTC`, `TAI`, `TT`, `TDB`, `TCG`, `TCB`, `UT1`, `GPS` |
| Epochs | `2026-10-19T12:00:00.000` or day-of-year `2026-292T12:00:00.000` |

Covariance blocks are skipped. Space-fixed frames use astropy and IERS Earth orientation data, which it downloads when online.

## NAIRAS trajectories (CCMC Runs-on-Request)

Choose **NAIRAS trajectory** in the app, or use `--nairas`. The output matches the trajectory input files NASA published with the [RaD-X flight data](https://doi.org/10.5281/zenodo.14927669), checked byte for byte against their balloon flight file:

```
# year(yyyy),month(mm),day(dd),hour(hh),min(mm),sec(fractional second),alt(km),lat(deg),lon(deg)
 2015   9  25  17   6  6.000     1.394765    34.490002   255.783325
```

- Space separated, with `#` comment lines at the top
- Date and time in UTC (TAI, TT, GPS and other OEM time systems are converted)
- Altitude in km, **before** latitude
- Longitude from 0 to 360 degrees east
- One vehicle per file, with times in order

Notes:

- NASA's sample files use one point per minute. Long, high-rate OEM files can produce very large trajectories, so `--step 60` (or the "Keep one point every" box) is a good starting point. To keep just the start of a file, use **Only the first ___ points** in the app or `--limit 600`.
- Altitude is height above the WGS84 ellipsoid. NASA's aircraft and balloon files use barometric altitude, which can differ by tens of meters. For spacecraft this makes no practical difference.
- The CCMC uploader checks file names: use only letters, numbers, and underscores (like `trajectory_1.txt`) and keep the file in a folder with no spaces in its path. The app suggests a safe name for you.

## Use in your own code

```python
from xyz_to_lla import xyz_to_lla

lat, lon, alt = xyz_to_lla(x_array, y_array, z_array)
```

## Running the tests

```
pip install ".[test]"
pytest
```

The tests cover the conversion math, CSV and OEM input, every output option, the NAIRAS format (checked byte for byte against an excerpt of NASA's RaD-X trajectory file in `tests/data`), safe writes, and the updater. The desktop app tests need a screen, so they only run when `RUN_GUI_TESTS=1` is set.

GitHub Actions runs everything on Linux, macOS, and Windows on every push. The badge at the top shows the latest result.

## Verifying a release

Every release is signed with the maintainer's offline [minisign](https://jedisct1.github.io/minisign/) key and with Sigstore through GitHub's artifact attestations. PyPI packages are published with trusted publishing, so PyPI shows exactly which workflow built each file. The in-app updater checks the minisign signature before installing anything.

To check a release yourself, see [Verifying a release yourself](https://github.com/SBK008/orbit-coordinate-converter/blob/main/SECURITY.md#verifying-a-release-yourself) in SECURITY.md.

## Citing

If this tool helps your research, please cite it. Every release is archived on Zenodo, and [doi:10.5281/zenodo.23986346](https://doi.org/10.5281/zenodo.23986346) always points to the latest version. Zenodo also gives each release its own DOI if you need to cite an exact version.

GitHub's **Cite this repository** button (in the About section) gives APA and BibTeX from [`CITATION.cff`](https://github.com/SBK008/orbit-coordinate-converter/blob/main/CITATION.cff).

## Publishing an update (maintainer notes)

1. Create a branch for the change, for example `v1.4.0`.
2. Make the changes on that branch, raise `__version__` in `xyz_to_lla.py`, add a section to `CHANGELOG.md`, and update `version` and `date-released` in `CITATION.cff`.
3. Open a pull request into `main` and wait for the tests to pass.
4. Merge the pull request.
5. Go to **Releases > Draft a new release**, create a tag named after the version (like `v1.4.0`) on `main`, paste the changelog section, and publish.
6. The **release** workflow checks the tag, signs the files with Sigstore, attaches `SHA256SUMS` and the packages, and publishes to PyPI. Wait for a green check on the Actions tab.
7. On your own computer, sign the release with your offline key:
   ```
   scripts/sign_release.sh v1.4.0
   ```
   It checks that `SHA256SUMS` matches the files at the tag before signing. Attach the `SHA256SUMS.minisig` it makes to the release (**Edit release**, drag the file in, **Update release**).

The app's update button won't install a release until both `SHA256SUMS` and `SHA256SUMS.minisig` are attached. Code merged into `main` without a release is never sent to users.
