# Coordinate Converter

[![tests](https://github.com/YOUR_NAME/YOUR_REPO/actions/workflows/tests.yml/badge.svg)](https://github.com/YOUR_NAME/YOUR_REPO/actions/workflows/tests.yml)

Convert Earth-centered (ECEF) X/Y/Z coordinates and CCSDS OEM orbit files to WGS84 latitude, longitude, and altitude. Includes a desktop app and a command-line tool, and handles files with millions of points.

## Features

- **Accurate at any altitude:** within a micrometer from the surface out past GEO.
- **CSV input:** any CSV with X, Y, Z columns in meters. Your other columns are kept exactly as they were.
- **CCSDS OEM input:** text (KVN) orbit files in Earth-fixed or space-fixed frames. Space-fixed positions are rotated to Earth-fixed at each epoch.
- **Epoch output** as written in the file, as Gregorian calendar dates, or as Modified Julian Dates.
- **Comma or space separated output.**
- **NAIRAS trajectory export:** OEM files can be saved in the exact trajectory format used by NASA's NAIRAS radiation model on CCMC Runs-on-Request.
- **Large files:** processed in chunks, so memory stays flat. Tested on a 1 GB, 20 million row CSV.
- **Safe writes:** a failed or stopped run never leaves a half-written output file.
- **Built-in updates:** the app downloads only the changed files from GitHub.

## Install

**Option 1: pip (recommended)**

Requires Python 3.11 or newer.

```
pip install git+https://github.com/YOUR_NAME/YOUR_REPO.git
```

This installs the dependencies and two commands:

- `coordinate-converter` opens the desktop app
- `xyz-to-lla` runs the command-line tool

To update:

```
pip install --upgrade git+https://github.com/YOUR_NAME/YOUR_REPO.git
```

**Option 2: download the zip**

1. Click **Code > Download ZIP** and unzip it.
2. Install the dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Run the app:
   ```
   python converter_gui.py
   ```

To update, click **Check for updates** in the app. It downloads only the files that changed.

## Desktop app

1. Choose an input file (`.csv`, `.oem`, or `.txt`).
2. Pick the options:
   - **OEM files:** epoch format, and fast mode for space-fixed frames
   - **CSV files:** the names of your X, Y, and Z columns
   - **Output:** comma separated, space separated, or NAIRAS trajectory, and whether to include column names
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

- NASA's sample files use one point per minute. Long, high-rate OEM files can produce very large trajectories, so `--step 60` (or the "Keep one point every" box) is a good starting point.
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

## Publishing an update (maintainer notes)

1. Upload the changed files to the top level of this repo.
2. Raise `__version__` in `xyz_to_lla.py`, for example `1.1.0` to `1.1.1`.

The version number is how pip and the app's update button know there is something new. If it isn't raised, users won't be told about the update.
