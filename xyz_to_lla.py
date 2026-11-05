#!/usr/bin/env python3
"""
Convert ECEF X/Y/Z coordinates (meters) to WGS84 latitude/longitude/altitude
using pyproj. Vectorized and chunked, so it handles millions of points.

Also reads CCSDS OEM (Orbit Ephemeris Message) files in the text (KVN) format.
OEM positions are in km and may be in an Earth-fixed frame (ITRF*, EFG, ECEF)
or a space-fixed frame (EME2000/J2000, GCRF, ICRF, TEME). Space-fixed positions
are rotated to Earth-fixed (ITRS) at each line's epoch before conversion.

Install:
    pip install -r requirements.txt
    (astropy is only used for OEM files in a space-fixed frame)

    Or install the whole app with pip install orbit-converter, which adds
    the commands xyz-to-lla and coordinate-converter.

Desktop app:
    python converter_gui.py

Usage (CSV file):
    python xyz_to_lla.py input.csv output.csv
    python xyz_to_lla.py input.csv output.csv --x X --y Y --z Z --chunksize 1000000

Usage (OEM file):
    python xyz_to_lla.py orbit.oem output.csv
    python xyz_to_lla.py orbit.txt output.csv --format oem --chunksize 200000
    python xyz_to_lla.py orbit.oem output.csv --fast
    python xyz_to_lla.py orbit.oem output.csv --time-format mjd

    Files ending in .oem are read as OEM automatically. Use --format oem to force
    OEM for other extensions, or --format csv to force CSV. The --x/--y/--z options
    only apply to CSV input.

    OEM output columns:
        object, epoch, time_system, x_ecef_m, y_ecef_m, z_ecef_m, lat, lon, alt

    --time-format (OEM only) sets how the epoch column is written:
        original   epochs exactly as they appear in the file (default)
        gregorian  calendar date, e.g. 2026-292T12:00:00.000 becomes 2026-10-19T12:00:00.000
        mjd        Modified Julian Date, days since 1858-11-17T00:00, e.g. 61332.500000000000
                   (column is named epoch_mjd, 12 decimal places, about 0.1 microsecond)
    The time system is not changed. A TDB epoch stays TDB, and the time_system
    column still says which one it is.

    Supported OEM metadata:
        CENTER_NAME  EARTH only
        REF_FRAME    ITRF, ITRF2014, ITRF2020, any ITRF*, EFG, ECEF (used as is)
                     EME2000, J2000, GCRF, ICRF, TEME (rotated to ITRS with astropy)
        TIME_SYSTEM  UTC, TAI, TT, TDB, TCG, TCB, UT1, GPS
        Epochs       2026-10-19T12:00:00.000 or day-of-year 2026-292T12:00:00.000
    COVARIANCE_START/COVARIANCE_STOP blocks are skipped. XML OEM is not supported.

    --fast (space-fixed frames only): by default the full IAU 2006/2000A rotation
    is computed at every line, which takes about 75 s per 500,000 lines. With
    --fast, the slowly changing precession-nutation part is computed every 600 s
    and interpolated, while Earth rotation and polar motion are still computed at
    every line. This is about 8x faster overall and differs from the default by
    less than 0.05 mm even at geostationary distance. TEME is exact either way.

    Note: astropy uses IERS Earth orientation data for the rotation. It downloads
    current tables when it can; without internet access it falls back to the
    tables bundled with astropy and prints a warning.

Output options (CSV and OEM):
    --separator comma   comma-separated output (default)
    --separator space   space-separated output, e.g. for CCMC Runs-on-Request uploads
    --no-header         leave out the column-name line at the top
    --nairas            OEM only: write a NAIRAS trajectory input file for CCMC
                        Runs-on-Request, matching NASA's RaD-X sample files:
                        UTC year month day hour min sec, alt (km), lat, lon (0-360)
    --step SECONDS      with --nairas, keep one point per SECONDS (0 keeps all)
    --limit N           write only the first N points (0 keeps all)

    With --separator space, empty values are written as NaN so every row keeps
    the same number of columns, and any text value that contains a space (such
    as an object name) is wrapped in double quotes.

    The output is written to a temporary .part file next to the output and only
    renamed to the final name when the conversion finishes, so a failed or
    interrupted run never leaves a half-written file that looks complete.

Usage (in your own code):
    from xyz_to_lla import xyz_to_lla
    lat, lon, alt = xyz_to_lla(x_array, y_array, z_array)
"""

# Version of the whole app. Bump this when you push an update: pip and the
# GUI's "Check for updates" button both read it from here.
__version__ = "1.5.0"

import argparse
import contextlib
import math
import os
import sys
import tempfile
from types import SimpleNamespace

import numpy as np
import pandas as pd
from pyproj import Transformer

# EPSG:4978 = WGS84 geocentric (ECEF X, Y, Z in meters)
# EPSG:4979 = WGS84 geographic 3D (lon, lat, ellipsoidal height in meters)
# always_xy=True means output order is (lon, lat, alt)
_TRANSFORMER = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)

_WGS84_A = 6378137.0                      # equatorial radius (m)
_WGS84_F = 1 / 298.257223563              # flattening
_WGS84_E2 = _WGS84_F * (2 - _WGS84_F)     # first eccentricity squared


def xyz_to_lla(x, y, z):
    """Convert ECEF arrays to (lat, lon, alt). Accepts scalars, lists, or numpy arrays."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    lon, lat, _ = _TRANSFORMER.transform(x, y, z)
    # pyproj's inverse is a fast approximation that is exact near the surface but drifts
    # with altitude (about 0.3 m in altitude at GEO). Starting from its answer, two steps
    # of the standard fixed-point iteration bring every altitude to full double precision.
    p = np.hypot(x, y)
    phi = np.radians(lat)
    for _ in range(2):
        s = np.sin(phi)
        n = _WGS84_A / np.sqrt(1 - _WGS84_E2 * s * s)
        phi = np.arctan2(z + _WGS84_E2 * n * s, p)
    s, c = np.sin(phi), np.cos(phi)
    # This form of the height stays accurate at the poles, where p is near 0
    alt = p * c + z * s - _WGS84_A * np.sqrt(1 - _WGS84_E2 * s * s)
    return np.degrees(phi), lon, alt


class ConverterError(Exception):
    """A problem with the input. The message is shown to the user."""


def _report(progress, message):
    """Send a status message to the GUI callback, or to stderr for the command line."""
    if progress is not None:
        progress(message)
    else:
        print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

SEPARATORS = {"comma": ",", "space": " "}
FLOAT_FORMAT = "%.9f"


def _separator(name):
    if name not in SEPARATORS:
        raise ValueError(f"Unknown separator {name!r}. Use one of: {', '.join(SEPARATORS)}.")
    return SEPARATORS[name]


def check_limit(limit):
    """Return the most points to write (0 means all), or raise ConverterError."""
    if limit is None or (isinstance(limit, str) and not limit.strip()):
        return 0
    try:
        n = float(limit)
    except (TypeError, ValueError):
        n = math.nan
    if not math.isfinite(n) or n < 0 or n != int(n):
        raise ConverterError("The number of points must be a whole number, 0 or more "
                             "(0 or blank keeps every point).")
    return int(n)


def _done_message(total, limit, out_path, extra=""):
    stopped = f", stopped at the limit of {limit:,}" if limit and total >= limit else ""
    return f"Done. Wrote {total:,} points{extra}{stopped} to {out_path}"


def _read_umask():
    # os.umask can only be read by setting it, which changes it for the whole
    # process. Do that once here, at import, before the app starts any threads.
    mask = os.umask(0)
    os.umask(mask)
    return mask


_UMASK = _read_umask()


@contextlib.contextmanager
def _output_file(out_path):
    """
    Open a temporary file next to out_path for writing. On success it replaces
    out_path; on any error (or Ctrl+C) it is deleted and out_path is left alone.
    """
    # mkstemp makes a new file with a random name and never follows an existing
    # file or link, so nothing outside out_path can be overwritten
    folder, name = os.path.split(os.path.abspath(out_path))
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=name + ".", suffix=".part")
    f = os.fdopen(fd, "w", newline="", encoding="utf-8")
    try:
        with f:
            yield f
        # mkstemp files are private (0600); give the output normal permissions
        os.chmod(tmp, 0o666 & ~_UMASK)
        os.replace(tmp, out_path)
    except BaseException:
        f.close()
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def _write_chunk(df, f, sep, header):
    # Empty fields would shift columns in a space-separated file, so write NaN there
    df.to_csv(f, sep=sep, header=header, index=False, float_format=FLOAT_FORMAT,
              na_rep="" if sep == "," else "NaN", lineterminator="\n")


# ---------------------------------------------------------------------------
# CSV input
# ---------------------------------------------------------------------------

def _resolve_column(name, columns):
    """Find a column by exact name, then ignoring spaces around it and letter case."""
    if name in columns:
        return name
    matches = [c for c in columns if str(c).strip().lower() == name.strip().lower()]
    return matches[0] if len(matches) == 1 else None


def convert_csv(in_path, out_path, xcol, ycol, zcol, chunksize, progress=None,
                separator="comma", header=True, limit=0):
    sep = _separator(separator)
    limit = check_limit(limit)
    total = 0
    cols = None
    # Every column is read as text so the original columns are written back exactly
    # as they were. Only X, Y and Z are turned into numbers.
    read_opts = dict(dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig")
    try:
        with _output_file(out_path) as f, \
                pd.read_csv(in_path, chunksize=chunksize, **read_opts) as reader:
            for chunk in reader:
                if cols is None:
                    cols = _find_xyz(chunk.columns, (xcol, ycol, zcol), in_path)
                if limit:
                    chunk = chunk.iloc[:limit - total].copy()
                nums = []
                for c in cols:
                    v = pd.to_numeric(chunk[c], errors="coerce").to_numpy(dtype=np.float64)
                    bad = ~np.isfinite(v)
                    if bad.any():
                        i = int(np.argmax(bad))
                        raise ConverterError(
                            f"Data row {total + i + 1:,}: column {c} has {chunk[c].iloc[i]!r}, "
                            "which is not a number. Every row needs numeric X, Y and Z values.")
                    nums.append(v)
                lat, lon, alt = xyz_to_lla(*nums)
                chunk["lat"] = lat
                chunk["lon"] = lon
                chunk["alt"] = alt
                _write_chunk(chunk, f, sep, header and total == 0)
                total += len(chunk)
                _report(progress, f"Converted {total:,} points")
                if limit and total >= limit:
                    break
            if cols is None:
                # Header only, no data rows: still write the header
                columns = pd.read_csv(in_path, nrows=0, **read_opts).columns
                _find_xyz(columns, (xcol, ycol, zcol), in_path)
                empty = pd.DataFrame(columns=[*columns, "lat", "lon", "alt"])
                _write_chunk(empty, f, sep, header)
    except pd.errors.EmptyDataError:
        raise ConverterError(f"{in_path} is empty.")
    except pd.errors.ParserError as e:
        raise ConverterError(f"Could not read {in_path} as a CSV file: {e}")
    except UnicodeDecodeError:
        raise ConverterError(f"{in_path} is not a text CSV file (it may be an Excel .xlsx "
                             "file; save it as CSV first).")
    _report(progress, _done_message(total, limit, out_path))
    return total


def _find_xyz(columns, names, in_path):
    found = [_resolve_column(n, columns) for n in names]
    missing = [n for n, c in zip(names, found) if c is None]
    if missing:
        raise ConverterError(f"Column(s) {', '.join(missing)} not found in {in_path}. "
                             f"Columns in the file: {', '.join(map(str, columns))}")
    if len(set(found)) < 3:
        raise ConverterError("X, Y and Z must be three different columns.")
    return found


# ---------------------------------------------------------------------------
# CCSDS OEM (KVN text format)
# ---------------------------------------------------------------------------

CSV_CHUNKSIZE = 1_000_000
OEM_CHUNKSIZE = 200_000

INERTIAL_FRAMES = ("EME2000", "J2000", "GCRF", "ICRF", "TEME")
TIME_SYSTEMS = ("UTC", "TAI", "TT", "TDB", "TCG", "TCB", "UT1", "GPS")
GPS_TO_TAI_SECONDS = 19.0  # TAI = GPS + 19 s
FAST_GRID_SECONDS = 600.0  # --fast: precession-nutation grid spacing

SUPPORTED_FRAMES_TEXT = (
    "Earth-fixed: ITRF, ITRF2014, ITRF2020 (any ITRF*), EFG, ECEF. "
    "Space-fixed: EME2000 (J2000), GCRF, ICRF, TEME."
)

OEM_COLUMNS = ["object", "epoch", "time_system",
               "x_ecef_m", "y_ecef_m", "z_ecef_m", "lat", "lon", "alt"]

TIME_FORMATS = ("original", "gregorian", "mjd")
MJD_ZERO = np.datetime64("1858-11-17", "D")  # MJD 0 = 1858-11-17T00:00
MJD_DECIMALS = 12                             # 1e-12 day is about 0.09 microseconds

# Calendar (YYYY-MM-DDThh:mm:ss.sss) or day-of-year (YYYY-DDDThh:mm:ss.sss)
_EPOCH_RE = r"\d{4}-(?:\d{2}-\d{2}|\d{3})T\d{2}:\d{2}:\d{2}(?:\.\d*)?Z?"


class OEMError(ConverterError):
    """A problem with the OEM file. The message is shown to the user."""


def _is_earth_fixed(frame):
    return frame.startswith("ITRF") or frame in ("EFG", "ECEF")


_ASTROPY = None


def _load_astropy():
    """Import astropy only when a space-fixed frame needs it."""
    global _ASTROPY
    if _ASTROPY is None:
        try:
            import astropy.units as u
            import erfa
            from astropy.coordinates import GCRS, ITRS, TEME, CartesianRepresentation
            # Same polar motion lookup (IERS tables) that astropy's own ITRS transforms use
            from astropy.coordinates.builtin_frames.utils import get_polar_motion
            from astropy.time import Time, TimeDelta
        except ImportError:
            raise OEMError("This OEM file uses a space-fixed reference frame, which needs astropy.\n"
                           "Install it with: pip install astropy")
        _ASTROPY = SimpleNamespace(u=u, erfa=erfa, GCRS=GCRS, ITRS=ITRS, TEME=TEME,
                                   CartesianRepresentation=CartesianRepresentation,
                                   get_polar_motion=get_polar_motion,
                                   Time=Time, TimeDelta=TimeDelta)
    return _ASTROPY


def _check_meta(m, line_no):
    """Validate one META block and return the parts we use."""
    for key in ("CENTER_NAME", "REF_FRAME", "TIME_SYSTEM"):
        if key not in m:
            raise OEMError(f"META block starting on line {line_no} is missing {key}.")
    if m["CENTER_NAME"].upper() != "EARTH":
        raise OEMError(f"META block starting on line {line_no} has CENTER_NAME = {m['CENTER_NAME']}. "
                       "Only EARTH is supported.")
    frame = m["REF_FRAME"].upper()
    if not (_is_earth_fixed(frame) or frame in INERTIAL_FRAMES):
        raise OEMError(f"META block starting on line {line_no} has REF_FRAME = {m['REF_FRAME']}, "
                       f"which is not supported. Supported frames: {SUPPORTED_FRAMES_TEXT}")
    time_system = m["TIME_SYSTEM"].upper()
    if time_system not in TIME_SYSTEMS:
        raise OEMError(f"META block starting on line {line_no} has TIME_SYSTEM = {m['TIME_SYSTEM']}, "
                       f"which is not supported. Supported time systems: {', '.join(TIME_SYSTEMS)}.")
    return {"object": m.get("OBJECT_NAME", m.get("OBJECT_ID", "")),
            "frame": frame, "time_system": time_system}


def _iter_oem_batches(path, chunksize):
    """
    Read an OEM file line by line and yield batches of data lines as
    (meta, line_numbers, epochs, x_km, y_km, z_km). A batch ends when it
    reaches chunksize lines, when a new segment starts, or at end of file.
    """
    meta = None       # metadata for the data lines being read
    pending = None    # metadata being collected between META_START and META_STOP
    meta_line = 0
    in_cov = False
    seen_content = False
    seen_meta = False
    lines, epochs, xs, ys, zs = [], [], [], [], []

    def take():
        nonlocal lines, epochs, xs, ys, zs
        batch = (meta, lines, epochs, np.array(xs), np.array(ys), np.array(zs))
        lines, epochs, xs, ys, zs = [], [], [], [], []
        return batch

    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for n, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue

            if not seen_content:
                seen_content = True
                if line.startswith("<"):
                    raise OEMError("This looks like an XML OEM file. Only the text (KVN) OEM format "
                                   "is supported.")
                if not line.startswith("CCSDS_OEM_VERS") and not line.startswith("COMMENT"):
                    raise OEMError(f"Line {n} should be CCSDS_OEM_VERS = ... but is: {line}\n"
                                   "This does not look like a text (KVN) OEM file.")

            if line.startswith("COMMENT"):
                continue

            if in_cov:
                if line == "COVARIANCE_STOP":
                    in_cov = False
                continue

            if pending is not None:
                if line == "META_STOP":
                    meta = _check_meta(pending, meta_line)
                    pending = None
                    continue
                key, sep, value = line.partition("=")
                if not sep:
                    raise OEMError(f"Line {n}: expected KEY = value inside the META block, got: {line}")
                pending[key.strip().upper()] = value.strip()
                continue

            if line == "META_START":
                if epochs:
                    yield take()
                pending = {}
                meta_line = n
                seen_meta = True
                continue

            if line == "COVARIANCE_START":
                in_cov = True
                continue

            if line in ("META_STOP", "COVARIANCE_STOP"):
                raise OEMError(f"Line {n}: {line} without a matching start line.")

            if line[0].isdigit():
                if meta is None:
                    raise OEMError(f"Line {n}: data line found before any META_START/META_STOP block.")
                parts = line.split()
                if len(parts) < 4:
                    raise OEMError(f"Line {n}: data line needs at least an epoch and X Y Z, got: {line}")
                try:
                    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                        raise ValueError
                except ValueError:
                    raise OEMError(f"Line {n}: could not read X Y Z as numbers: {line}")
                lines.append(n)
                epochs.append(parts[0])
                xs.append(x)
                ys.append(y)
                zs.append(z)
                if len(epochs) >= chunksize:
                    yield take()
                continue

            if not seen_meta and "=" in line:
                continue  # header keys such as CCSDS_OEM_VERS, CREATION_DATE, ORIGINATOR

            raise OEMError(f"Line {n}: unrecognized line: {line}")

    if pending is not None:
        raise OEMError(f"META_START on line {meta_line} has no matching META_STOP.")
    if in_cov:
        raise OEMError("COVARIANCE_START has no matching COVARIANCE_STOP.")
    if epochs:
        yield take()


def _check_epochs(epochs, line_numbers):
    ok = pd.Series(epochs).str.fullmatch(_EPOCH_RE).to_numpy()
    if not ok.all():
        i = int(np.argmin(ok))
        raise OEMError(f"Line {line_numbers[i]}: epoch {epochs[i]} is not in a supported format. "
                       "Use YYYY-MM-DDThh:mm:ss.sss or YYYY-DDDThh:mm:ss.sss.")
    # Also refuse impossible dates and times (2026-02-30, 25:00), whatever the output format
    _split_epochs(epochs, line_numbers)


def _split_epochs(epochs, line_numbers):
    """
    Split checked OEM epoch strings into calendar days (datetime64[D]), the
    time-of-day text, and seconds of day. Pure calendar arithmetic in the file's
    own time system, so no astropy and no change of time scale.
    """
    s = pd.Series(epochs, dtype=str).str.rstrip("Z")
    parts = s.str.split("T", n=1)
    date_text = parts.str[0]
    time_text = parts.str[1]
    is_doy = (date_text.str.len() == 8).to_numpy()   # YYYY-DDD vs YYYY-MM-DD

    days = np.empty(len(s), dtype="datetime64[D]")
    bad = np.zeros(len(s), dtype=bool)
    if (~is_doy).any():
        cal = date_text[~is_doy].to_numpy()
        try:
            days[~is_doy] = cal.astype("datetime64[D]")
        except ValueError:
            # Find the first impossible date (such as 2026-02-30) to report it
            for j, d in zip(np.flatnonzero(~is_doy), cal):
                try:
                    np.datetime64(d, "D")
                except ValueError:
                    bad[j] = True
                    break
    if is_doy.any():
        d = date_text[is_doy]
        year = d.str[:4].astype(int).to_numpy()
        doy = d.str[5:8].astype(int).to_numpy()
        jan1 = (d.str[:4] + "-01-01").to_numpy().astype("datetime64[D]")
        day = jan1 + (doy - 1).astype("timedelta64[D]")
        bad[is_doy] = (doy < 1) | (day.astype("datetime64[Y]").astype(int) + 1970 != year)
        days[is_doy] = day

    hh = time_text.str[0:2].astype(int).to_numpy()
    mm = time_text.str[3:5].astype(int).to_numpy()
    ss = time_text.str[6:].astype(float).to_numpy()
    bad |= (hh > 23) | (mm > 59) | (ss >= 61)   # 61 allows a UTC leap second (23:59:60)

    if bad.any():
        i = int(np.argmax(bad))
        raise OEMError(f"Line {line_numbers[i]}: epoch {epochs[i]} is not a real date or time.")
    return days, time_text, hh * 3600.0 + mm * 60.0 + ss


def format_epochs(epochs, line_numbers, time_format):
    """
    Return (column_name, values) for the epoch column in the chosen time format.
    original:  the epoch text as written in the file
    gregorian: YYYY-MM-DDThh:mm:ss.sss (day-of-year dates become calendar dates)
    mjd:       Modified Julian Date as text, built from whole days plus a rounded
               fraction so no precision is lost to floating point
    """
    if time_format == "original":
        return "epoch", list(epochs)
    days, time_text, seconds = _split_epochs(epochs, line_numbers)
    if time_format == "gregorian":
        return "epoch", (pd.Series(days.astype(str)) + "T" + time_text.to_numpy()).to_numpy()
    if time_format == "mjd":
        whole = (days - MJD_ZERO).astype(np.int64)
        scale = 10 ** MJD_DECIMALS
        frac = np.rint(seconds / 86400.0 * scale).astype(np.int64)
        # A leap second (23:59:60) or rounding at 23:59:59.99999... rolls into the next day
        carry = frac >= scale
        whole = whole + carry
        frac = frac - carry * scale
        # Dates before 1858-11-17 have negative MJD. MJD -1 plus half a day is -0.5,
        # which is written as "-0." + (1 - 0.5), so shift whole and frac for those.
        neg = (whole < 0) & (frac > 0)
        sign = np.where(whole < 0, "-", "")
        mag = np.where(neg, -(whole + 1), np.abs(whole))
        frac = np.where(neg, scale - frac, frac)
        text = (pd.Series(sign) + pd.Series(mag).astype(str) + "."
                + pd.Series(frac).astype(str).str.zfill(MJD_DECIMALS))
        return "epoch_mjd", text.to_numpy()
    raise ValueError(f"Unknown time format {time_format!r}. Use one of: {', '.join(TIME_FORMATS)}.")


def _parse_epochs(epochs, time_system):
    """Turn OEM epoch strings into an astropy Time array."""
    ap = _load_astropy()
    scale = "tai" if time_system == "GPS" else time_system.lower()
    s = pd.Series(epochs).str.rstrip("Z")
    # Calendar dates have "-" at index 7 (YYYY-MM-), day-of-year dates do not (YYYY-DDDT)
    is_doy = (s.str[7] != "-").to_numpy()
    jd1 = np.empty(len(s))
    jd2 = np.empty(len(s))
    try:
        if is_doy.any():
            d = s[is_doy]
            d = d.str[:4] + ":" + d.str[5:8] + ":" + d.str[9:]  # astropy "yday" is YYYY:DDD:hh:mm:ss
            t = ap.Time(d.to_numpy(dtype=str), format="yday", scale=scale)
            jd1[is_doy], jd2[is_doy] = t.jd1, t.jd2
        if not is_doy.all():
            t = ap.Time(s[~is_doy].to_numpy(dtype=str), format="isot", scale=scale)
            jd1[~is_doy], jd2[~is_doy] = t.jd1, t.jd2
    except ValueError as e:
        raise OEMError(f"Could not read an epoch in this chunk: {e}")
    times = ap.Time(jd1, jd2, format="jd", scale=scale)
    if time_system == "GPS":
        times = times + ap.TimeDelta(GPS_TO_TAI_SECONDS, format="sec")
    return times


def _interpolated_c2i(tt1, tt2):
    """
    GCRS to CIRS (precession-nutation) matrices, as erfa.c2i06a gives, but computed
    on a grid every FAST_GRID_SECONDS and linearly interpolated to each time.
    The CIP coordinates X, Y and the CIO locator s are interpolated (not the matrix
    elements), so every result is still an exact rotation matrix.
    """
    erfa = _load_astropy().erfa
    day0 = float(np.floor(tt1.min()))
    t = (tt1 - day0) + tt2                     # days since day0
    step = FAST_GRID_SECONDS / 86400.0
    k = np.floor(t / step)
    nodes = np.union1d(k, k + 1)
    if len(nodes) >= len(t):
        return erfa.c2i06a(tt1, tt2)           # sparse data: the grid would not save time
    gx, gy, gs = erfa.xys06a(np.full(len(nodes), day0), nodes * step)
    i0 = np.searchsorted(nodes, k)
    i1 = np.searchsorted(nodes, k + 1)
    f = t / step - k
    x = gx[i0] + f * (gx[i1] - gx[i0])
    y = gy[i0] + f * (gy[i1] - gy[i0])
    s = gs[i0] + f * (gs[i1] - gs[i0])
    return erfa.c2ixys(x, y, s)


def _fast_inertial_to_itrs(frame, v, times):
    """
    Same rotation as astropy's GCRS->ITRS and TEME->ITRS transforms, built directly
    from the same erfa calls. Earth rotation and polar motion are computed exactly
    at every time. For GCRS, the slowly changing precession-nutation part is
    interpolated (see _interpolated_c2i). TEME has no such part, so it is exact.
    """
    ap = _load_astropy()
    erfa = ap.erfa
    tt, ut1 = times.tt, times.ut1
    xp, yp = ap.get_polar_motion(times)
    if frame == "TEME":
        # As astropy's teme_to_itrs_mat: GMST 1982 and polar motion without s'
        m = erfa.c2tcio(np.eye(3), erfa.gmst82(ut1.jd1, ut1.jd2), erfa.pom00(xp, yp, 0))
    else:
        # As astropy's gcrs_to_cirs_mat followed by cirs_to_itrs_mat
        pom = erfa.pom00(xp, yp, erfa.sp00(tt.jd1, tt.jd2))
        m = erfa.c2tcio(_interpolated_c2i(tt.jd1, tt.jd2), erfa.era00(ut1.jd1, ut1.jd2), pom)
    out = np.einsum("nij,jn->in", m, v)
    return out[0], out[1], out[2]


def _inertial_to_itrs(frame, x, y, z, times, fast=False):
    """Rotate space-fixed positions (meters) to Earth-fixed ITRS (meters) at each time."""
    ap = _load_astropy()
    if frame in ("EME2000", "J2000"):
        # Frame bias: J2000 = rb @ GCRS, so GCRS = rb.T @ J2000
        rb, _, _ = ap.erfa.bp00(2451545.0, 0.0)
        x, y, z = rb.T @ np.vstack([x, y, z])
        frame = "GCRF"
    if fast:
        return _fast_inertial_to_itrs(frame, np.vstack([x, y, z]), times)
    rep = ap.CartesianRepresentation(x, y, z, unit=ap.u.m)
    if frame == "TEME":
        src = ap.TEME(rep, obstime=times)
    else:
        # GCRF and ICRF: Earth-centered with ICRS-aligned axes, which is GCRS
        src = ap.GCRS(rep, obstime=times)
    itrs = src.transform_to(ap.ITRS(obstime=times)).cartesian
    return itrs.x.to_value(ap.u.m), itrs.y.to_value(ap.u.m), itrs.z.to_value(ap.u.m)


def _rotate_to_earth_fixed(meta, epochs, line_numbers, x, y, z, fast):
    """Rotate a space-fixed batch to ITRS, turning astropy failures into readable errors."""
    try:
        times = _parse_epochs(epochs, meta["time_system"])
        return _inertial_to_itrs(meta["frame"], x, y, z, times, fast)
    except OEMError:
        raise
    except Exception as e:
        # Usually IERS Earth orientation data that does not cover these dates
        raise OEMError(f"Could not rotate {meta['frame']} positions to Earth-fixed for the "
                       f"lines starting at line {line_numbers[0]} (epoch {epochs[0]}).\n"
                       f"{type(e).__name__}: {e}\n"
                       "If this mentions IERS, connect to the internet so astropy can download "
                       "current Earth orientation tables, then try again.")


def _oem_points(in_path, chunksize, fast):
    """
    Read an OEM file in batches and yield
    (meta, segment_number, line_numbers, epochs, x, y, z, lat, lon, alt)
    with Earth-fixed X, Y, Z in meters.
    """
    segments = 0
    last_meta = None
    for meta, line_numbers, epochs, x_km, y_km, z_km in _iter_oem_batches(in_path, chunksize):
        if meta is not last_meta:
            segments += 1
            last_meta = meta
        _check_epochs(epochs, line_numbers)
        x, y, z = x_km * 1000.0, y_km * 1000.0, z_km * 1000.0
        if meta["frame"] in INERTIAL_FRAMES:
            x, y, z = _rotate_to_earth_fixed(meta, epochs, line_numbers, x, y, z, fast)
        lat, lon, alt = xyz_to_lla(x, y, z)
        yield meta, segments, line_numbers, epochs, x, y, z, lat, lon, alt


def convert_oem(in_path, out_path, chunksize, fast=False, time_format="original", progress=None,
                separator="comma", header=True, limit=0):
    if time_format not in TIME_FORMATS:
        raise ValueError(f"Unknown time format {time_format!r}. Use one of: {', '.join(TIME_FORMATS)}.")
    sep = _separator(separator)
    limit = check_limit(limit)
    columns = [("epoch_mjd" if c == "epoch" and time_format == "mjd" else c) for c in OEM_COLUMNS]
    total = 0
    segments = 0
    with _output_file(out_path) as f:
        for meta, segments, line_numbers, epochs, x, y, z, lat, lon, alt in \
                _oem_points(in_path, chunksize, fast):
            epoch_col, epoch_values = format_epochs(epochs, line_numbers, time_format)
            df = pd.DataFrame({"object": meta["object"] or np.nan, epoch_col: epoch_values,
                               "time_system": meta["time_system"],
                               "x_ecef_m": x, "y_ecef_m": y, "z_ecef_m": z,
                               "lat": lat, "lon": lon, "alt": alt}, columns=columns)
            if limit:
                df = df.iloc[:limit - total]
            _write_chunk(df, f, sep, header and total == 0)
            total += len(df)
            _report(progress, f"Converted {total:,} points (segment {segments}, {meta['frame']})")
            if limit and total >= limit:
                break
        if total == 0:
            _write_chunk(pd.DataFrame(columns=columns), f, sep, header)
    _report(progress, _done_message(total, limit, out_path, f" from {segments} segment(s)"))
    return total


# ---------------------------------------------------------------------------
# NAIRAS trajectory output (CCMC Runs-on-Request)
# ---------------------------------------------------------------------------
# Matches the trajectory input files NASA published with the RaD-X data
# (doi.org/10.5281/zenodo.14927669), for example:
#   # year(yyyy),month(mm),day(dd),hour(hh),min(mm),sec(fractional second),alt(km),lat(deg),lon(deg)
#    2015   9  25  17   6  6.000     1.394765    34.490002   255.783325
# Space separated, UTC, altitude in km BEFORE latitude, longitude 0 to 360 east.

NAIRAS_COLUMNS_LINE = ("# year(yyyy),month(mm),day(dd),hour(hh),min(mm),"
                       "sec(fractional second),alt(km),lat(deg),lon(deg)")
NAIRAS_ROW_FORMAT = " %4d %3d %3d %3d %3d %6.3f %12.6f %12.6f %12.6f"


def _utc_times_ms(meta, epochs, line_numbers):
    """OEM epochs as UTC datetime64[ms], converting from other time systems if needed."""
    if meta["time_system"] == "UTC":
        days, _, seconds = _split_epochs(epochs, line_numbers)
        ms = np.rint(seconds * 1000.0).astype(np.int64)
        return days.astype("datetime64[ms]") + ms.astype("timedelta64[ms]")
    try:
        ns = _parse_epochs(epochs, meta["time_system"]).utc.datetime64.astype("datetime64[ns]")
    except OEMError:
        raise
    except Exception as e:
        raise OEMError(f"Could not convert {meta['time_system']} epochs to UTC for the lines "
                       f"starting at line {line_numbers[0]} (epoch {epochs[0]}).\n"
                       f"{type(e).__name__}: {e}")
    n = ns.astype(np.int64)
    return ((n + 500_000) // 1_000_000).astype("datetime64[ms]")   # round to the millisecond


def _nairas_rows(t_ms, lat, lon, alt_m):
    """Columns in NAIRAS order: year month day hour min sec alt_km lat lon360."""
    d = t_ms.astype("datetime64[D]")
    month_start = d.astype("datetime64[M]")
    year_start = d.astype("datetime64[Y]")
    ms_of_day = (t_ms - d).astype(np.int64)
    lon360 = np.round(np.mod(lon, 360.0), 6)
    lon360[lon360 >= 360.0] = 0.0          # -0.0000001 rounds to 360.000000, which is 0
    return np.column_stack([
        year_start.astype(np.int64) + 1970,
        (month_start - year_start).astype(np.int64) + 1,
        (d - month_start).astype(np.int64) + 1,
        ms_of_day // 3_600_000,
        ms_of_day // 60_000 % 60,
        ms_of_day % 60_000 / 1000.0,
        alt_m / 1000.0,
        lat,
        lon360,
    ])


def check_step(step_seconds):
    """Return the NAIRAS time step in whole milliseconds, or raise ConverterError."""
    try:
        step = float(step_seconds)
    except (TypeError, ValueError):
        step = math.nan
    if not math.isfinite(step) or step < 0:
        raise ConverterError("The time step must be a number of seconds, 0 or more.")
    step_ms = int(round(step * 1000))
    if step > 0 and step_ms == 0:
        raise ConverterError("The time step must be 0 (keep every point) or at least "
                             "0.001 seconds.")
    return step_ms


def convert_oem_nairas(in_path, out_path, chunksize, fast=False, step_seconds=0, header=True,
                       progress=None, limit=0):
    """
    Write an OEM file as a NAIRAS trajectory input file. step_seconds > 0 keeps
    only the first point in each step_seconds window (RaD-X files use 60 s).
    limit > 0 stops after that many points are written.
    """
    step_ms = check_step(step_seconds)
    limit = check_limit(limit)
    total = 0
    read = 0
    segments = 0
    objects = []
    t0 = None
    last_bucket = None
    last_time = None
    with _output_file(out_path) as f:
        for meta, segments, line_numbers, epochs, x, y, z, lat, lon, alt in \
                _oem_points(in_path, chunksize, fast):
            name = meta["object"]
            if name not in objects:
                objects.append(name)
                if len(objects) > 1:
                    raise OEMError("A NAIRAS trajectory is one vehicle, but this OEM file has more "
                                   f"than one object ({', '.join(o or '(no name)' for o in objects)}). "
                                   "Split it into one file per object first.")
            t = _utc_times_ms(meta, epochs, line_numbers)
            ti = t.astype(np.int64)
            prev = np.concatenate(([last_time if last_time is not None else ti[0] - 1], ti[:-1]))
            backwards = ti <= prev
            if backwards.any():
                i = int(np.argmax(backwards))
                raise OEMError(f"Line {line_numbers[i]}: epoch {epochs[i]} is not later than the "
                               "one before it. NAIRAS needs the points in time order with no "
                               "repeats.")
            last_time = int(ti[-1])
            keep = slice(None)
            if step_ms > 0:
                if t0 is None:
                    t0 = int(ti[0])
                bucket = (ti - t0) // step_ms
                prev_b = np.concatenate(([last_bucket if last_bucket is not None else -1],
                                         bucket[:-1]))
                keep = bucket != prev_b
                last_bucket = int(bucket[-1])
            rows = _nairas_rows(t[keep], lat[keep], lon[keep], alt[keep])
            if limit:
                rows = rows[:limit - total]
            if header and total == 0 and read == 0:
                f.write("# NAIRAS trajectory input file\n")
                f.write(f"# From {os.path.basename(in_path)}"
                        f"{' (object ' + name + ')' if name else ''}, times in UTC, "
                        f"made by xyz_to_lla {__version__}\n")
                f.write(NAIRAS_COLUMNS_LINE + "\n")
            if len(rows):
                np.savetxt(f, rows, fmt=NAIRAS_ROW_FORMAT)
            read += len(t)
            total += len(rows)
            _report(progress, f"Read {read:,} points, wrote {total:,} (segment {segments})")
            if limit and total >= limit:
                break
        if read == 0 and header:
            f.write(NAIRAS_COLUMNS_LINE + "\n")
    _report(progress, _done_message(total, limit, out_path, f" of {read:,} read"))
    return total


def check_paths(in_path, out_path):
    """Refuse a missing input, and an output that would overwrite the input."""
    if not os.path.isfile(in_path):
        raise ConverterError(f"Input file not found: {in_path}")
    if os.path.isdir(out_path):
        raise ConverterError(f"{out_path} is a folder. Choose a file name to save to.")
    # samefile, not comparing the text, catches another name for the same file,
    # such as Orbit.oem and orbit.oem on Windows and macOS
    if os.path.exists(out_path) and os.path.samefile(in_path, out_path):
        raise ConverterError("The output file must be different from the input file.")


def main():
    p = argparse.ArgumentParser(description="ECEF XYZ or CCSDS OEM to WGS84 lat/lon/alt (pyproj)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("input", help="input CSV with X, Y, Z columns in meters, or a CCSDS OEM text file")
    p.add_argument("output", help="output CSV (CSV input: original columns + lat, lon, alt; "
                                  "OEM input: object, epoch, time_system, ECEF meters, lat, lon, alt)")
    p.add_argument("--format", choices=["auto", "csv", "oem"], default="auto",
                   help="input format (default: auto, which treats .oem files as OEM and "
                        "everything else as CSV)")
    p.add_argument("--x", default="x", help="X column name (default: x)")
    p.add_argument("--y", default="y", help="Y column name (default: y)")
    p.add_argument("--z", default="z", help="Z column name (default: z)")
    p.add_argument("--chunksize", type=_positive_int, default=None,
                   help="rows per chunk (default: 1,000,000 for CSV, 200,000 for OEM)")
    p.add_argument("--separator", choices=list(SEPARATORS), default="comma",
                   help="column separator in the output: comma (default) or space")
    p.add_argument("--no-header", action="store_true",
                   help="do not write the column-name line at the top of the output")
    p.add_argument("--fast", action="store_true",
                   help="OEM in a space-fixed frame only: interpolate precession-nutation on a "
                        f"{FAST_GRID_SECONDS:g} s grid instead of computing it at every line. "
                        "Much faster, with sub-millimeter differences")
    p.add_argument("--time-format", choices=TIME_FORMATS, default="original",
                   help="OEM only: write epochs as they appear in the file (original), as "
                        "calendar dates (gregorian), or as Modified Julian Dates (mjd). "
                        "Default: original")
    p.add_argument("--nairas", action="store_true",
                   help="OEM only: write a NAIRAS trajectory input file (UTC date and time, "
                        "alt km, lat, lon 0-360) for CCMC Runs-on-Request. --separator and "
                        "--time-format do not apply")
    p.add_argument("--step", type=float, default=0, metavar="SECONDS",
                   help="with --nairas: keep one point per this many seconds (default 0, "
                        "keep every point; NASA's RaD-X files use 60)")
    p.add_argument("--limit", type=_non_negative_int, default=0, metavar="N",
                   help="write only the first N points (default 0, keep every point). "
                        "With --step, counts the points that are kept")
    a = p.parse_args()

    fmt = a.format
    if fmt == "auto":
        fmt = "oem" if a.input.lower().endswith(".oem") else "csv"

    out_opts = dict(separator=a.separator, header=not a.no_header, limit=a.limit)
    try:
        check_paths(a.input, a.output)
        if a.nairas:
            if fmt == "csv":
                raise ConverterError("--nairas needs an OEM file, which has the times NAIRAS "
                                     "needs. Use --format oem if the file has another extension.")
            convert_oem_nairas(a.input, a.output, a.chunksize or OEM_CHUNKSIZE, a.fast, a.step,
                               header=not a.no_header, limit=a.limit)
        elif fmt == "csv":
            convert_csv(a.input, a.output, a.x, a.y, a.z, a.chunksize or CSV_CHUNKSIZE, **out_opts)
        else:
            convert_oem(a.input, a.output, a.chunksize or OEM_CHUNKSIZE, a.fast, a.time_format,
                        **out_opts)
    except ConverterError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"Error: could not write {a.output}. If it is open in Excel or another "
              "program, close it and try again.", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: the folder for {a.output} does not exist.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Stopped. No output file was written.", file=sys.stderr)
        sys.exit(130)


def _positive_int(text):
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number")
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def _non_negative_int(text):
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number")
    if n < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return n


if __name__ == "__main__":
    main()
