#!/usr/bin/env python3
"""
Convert ECEF X/Y/Z coordinates (meters) to WGS84 latitude/longitude/altitude
using pyproj. Vectorized and chunked, so it handles millions of points.

Also reads CCSDS OEM (Orbit Ephemeris Message) files in the text (KVN) format.
OEM positions are in km and may be in an Earth-fixed frame (ITRF*, EFG, ECEF)
or a space-fixed frame (EME2000/J2000, GCRF, ICRF, TEME). Space-fixed positions
are rotated to Earth-fixed (ITRS) at each line's epoch before conversion.

Install:
    pip install pyproj numpy pandas
    pip install astropy      (only needed for OEM files in a space-fixed frame)

Usage (CSV file):
    python "Coordinate Converter.py" input.csv output.csv
    python "Coordinate Converter.py" input.csv output.csv --x X --y Y --z Z --chunksize 1000000

Usage (OEM file):
    python "Coordinate Converter.py" orbit.oem output.csv
    python "Coordinate Converter.py" orbit.txt output.csv --format oem --chunksize 200000
    python "Coordinate Converter.py" orbit.oem output.csv --fast

    Files ending in .oem are read as OEM automatically. Use --format oem to force
    OEM for other extensions, or --format csv to force CSV. The --x/--y/--z options
    only apply to CSV input.

    OEM output columns:
        object, epoch, time_system, x_ecef_m, y_ecef_m, z_ecef_m, lat, lon, alt

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

Usage (in your own code, after renaming this file to xyz_to_lla.py):
    from xyz_to_lla import xyz_to_lla
    lat, lon, alt = xyz_to_lla(x_array, y_array, z_array)
"""

import argparse
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
from pyproj import Transformer

# EPSG:4978 = WGS84 geocentric (ECEF X, Y, Z in meters)
# EPSG:4979 = WGS84 geographic 3D (lon, lat, ellipsoidal height in meters)
# always_xy=True means output order is (lon, lat, alt)
_TRANSFORMER = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)


def xyz_to_lla(x, y, z):
    """Convert ECEF arrays to (lat, lon, alt). Accepts scalars, lists, or numpy arrays."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    lon, lat, alt = _TRANSFORMER.transform(x, y, z)
    return lat, lon, alt


def convert_csv(in_path, out_path, xcol, ycol, zcol, chunksize):
    total = 0
    first = True
    for chunk in pd.read_csv(in_path, chunksize=chunksize):
        lat, lon, alt = xyz_to_lla(chunk[xcol].values, chunk[ycol].values, chunk[zcol].values)
        chunk["lat"] = lat
        chunk["lon"] = lon
        chunk["alt"] = alt
        chunk.to_csv(out_path, mode="w" if first else "a", header=first, index=False,
                     float_format="%.9f")
        first = False
        total += len(chunk)
        print(f"Converted {total:,} points", file=sys.stderr)
    print(f"Done. Wrote {total:,} points to {out_path}", file=sys.stderr)


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

# Calendar (YYYY-MM-DDThh:mm:ss.sss) or day-of-year (YYYY-DDDThh:mm:ss.sss)
_EPOCH_RE = r"\d{4}-(?:\d{2}-\d{2}|\d{3})T\d{2}:\d{2}:\d{2}(?:\.\d*)?Z?"


class OEMError(Exception):
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


def convert_oem(in_path, out_path, chunksize, fast=False):
    total = 0
    segments = 0
    first = True
    last_meta = None
    for meta, line_numbers, epochs, x_km, y_km, z_km in _iter_oem_batches(in_path, chunksize):
        if meta is not last_meta:
            segments += 1
            last_meta = meta
        _check_epochs(epochs, line_numbers)
        x, y, z = x_km * 1000.0, y_km * 1000.0, z_km * 1000.0
        if meta["frame"] in INERTIAL_FRAMES:
            times = _parse_epochs(epochs, meta["time_system"])
            x, y, z = _inertial_to_itrs(meta["frame"], x, y, z, times, fast)
        lat, lon, alt = xyz_to_lla(x, y, z)
        df = pd.DataFrame({"object": meta["object"], "epoch": epochs,
                           "time_system": meta["time_system"],
                           "x_ecef_m": x, "y_ecef_m": y, "z_ecef_m": z,
                           "lat": lat, "lon": lon, "alt": alt}, columns=OEM_COLUMNS)
        df.to_csv(out_path, mode="w" if first else "a", header=first, index=False,
                  float_format="%.9f")
        first = False
        total += len(df)
        print(f"Converted {total:,} points (segment {segments}, {meta['frame']})", file=sys.stderr)
    if first:
        pd.DataFrame(columns=OEM_COLUMNS).to_csv(out_path, index=False)
    print(f"Done. Wrote {total:,} points from {segments} segment(s) to {out_path}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description="ECEF XYZ or CCSDS OEM to WGS84 lat/lon/alt (pyproj)")
    p.add_argument("input", help="input CSV with X, Y, Z columns in meters, or a CCSDS OEM text file")
    p.add_argument("output", help="output CSV (CSV input: original columns + lat, lon, alt; "
                                  "OEM input: object, epoch, time_system, ECEF meters, lat, lon, alt)")
    p.add_argument("--format", choices=["auto", "csv", "oem"], default="auto",
                   help="input format (default: auto, which treats .oem files as OEM and "
                        "everything else as CSV)")
    p.add_argument("--x", default="x", help="X column name (default: x)")
    p.add_argument("--y", default="y", help="Y column name (default: y)")
    p.add_argument("--z", default="z", help="Z column name (default: z)")
    p.add_argument("--chunksize", type=int, default=None,
                   help="rows per chunk (default: 1,000,000 for CSV, 200,000 for OEM)")
    p.add_argument("--fast", action="store_true",
                   help="OEM in a space-fixed frame only: interpolate precession-nutation on a "
                        f"{FAST_GRID_SECONDS:g} s grid instead of computing it at every line. "
                        "Much faster, with sub-millimeter differences")
    a = p.parse_args()

    fmt = a.format
    if fmt == "auto":
        fmt = "oem" if a.input.lower().endswith(".oem") else "csv"

    if fmt == "csv":
        convert_csv(a.input, a.output, a.x, a.y, a.z, a.chunksize or CSV_CHUNKSIZE)
    else:
        try:
            convert_oem(a.input, a.output, a.chunksize or OEM_CHUNKSIZE, a.fast)
        except OEMError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
