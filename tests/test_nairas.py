"""NAIRAS trajectory output, checked against NASA's own RaD-X trajectory file."""

import os

import numpy as np
import pytest
from pyproj import Transformer

import xyz_to_lla as conv
from conftest import DATA, data_rows, oem_text

QUIET = dict(progress=lambda m: None)
NASA_FILE = os.path.join(DATA, "radx_balloon_excerpt.dat")


def nairas(write, tmp_path, text, chunksize=1000, **opts):
    src = write("in.oem", text)
    out = str(tmp_path / "trajectory_1.txt")
    conv.convert_oem_nairas(src, out, chunksize, **QUIET, **opts)
    return out


def nasa_as_oem():
    """Turn NASA's lat/lon/alt trajectory back into an Earth-fixed OEM file."""
    d = np.loadtxt(NASA_FILE, comments="#")
    year, month, day, hour, minute, sec, alt_km, lat, lon = d.T
    x, y, z = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True).transform(
        lon, lat, alt_km * 1000)
    lines = [f"{int(r[0]):04d}-{int(r[1]):02d}-{int(r[2]):02d}T{int(r[3]):02d}:{int(r[4]):02d}:"
             f"{r[5]:06.3f} {r[6] / 1000:.9f} {r[7] / 1000:.9f} {r[8] / 1000:.9f}"
             for r in zip(year, month, day, hour, minute, sec, x, y, z)]
    return oem_text([({"OBJECT_NAME": "RADX"}, lines)])


@pytest.mark.parametrize("chunksize", [1000, 3])
def test_matches_nasa_file_byte_for_byte(write, tmp_path, chunksize):
    out = nairas(write, tmp_path, nasa_as_oem(), chunksize=chunksize)
    assert data_rows(out) == data_rows(NASA_FILE)


def test_header_lines(write, tmp_path):
    out = nairas(write, tmp_path, nasa_as_oem())
    lines = open(out).read().splitlines()
    assert lines[2] == conv.NAIRAS_COLUMNS_LINE
    assert all(line.startswith("#") for line in lines[:3]) and not lines[3].startswith("#")
    out = nairas(write, tmp_path, nasa_as_oem(), header=False)
    assert not open(out).read().startswith("#")


def test_seconds_round_into_next_day_and_longitude_wraps(write, tmp_path):
    out = nairas(write, tmp_path, oem_text([({}, [
        "2026-12-31T23:59:59.9996 6378.137 -0.0000000001 0",
        "2027-001T00:00:30.000 6378.137 -100 0",
    ])]))
    rows = [r.split() for r in data_rows(out)]
    assert rows[0][:6] == ["2027", "1", "1", "0", "0", "0.000"]
    assert rows[0][8] == "0.000000"               # not 360.000000
    assert 359 < float(rows[1][8]) < 360          # west longitudes become 0-360


@pytest.mark.parametrize("time_system", ["UTC", "TAI", "GPS", "TT"])
def test_times_converted_to_utc(write, tmp_path, time_system):
    # 2026: TAI = UTC + 37 s, GPS = UTC + 18 s, TT = TAI + 32.184 s
    out = nairas(write, tmp_path, oem_text([({"TIME_SYSTEM": time_system},
                                             ["2026-06-01T00:00:37.000 6378.137 0 0"])]))
    y, mo, d, h, mi, s = data_rows(out)[0].split()[:6]
    expected = {"UTC": (1, 0, 0, 37.0), "TAI": (1, 0, 0, 0.0), "GPS": (1, 0, 0, 19.0),
                "TT": (31, 23, 59, 27.816)}[time_system]
    assert (int(d), int(h), int(mi), float(s)) == expected


def test_step_keeps_one_point_per_window_across_chunks(write, tmp_path):
    lines = [f"2026-01-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d} 6778.137 0 0"
             for i in range(0, 3600, 10)]                      # every 10 s for an hour
    text = oem_text([({}, lines)])
    for chunksize in (1000, 7):
        rows = data_rows(nairas(write, tmp_path, text, chunksize=chunksize, step_seconds=60))
        assert len(rows) == 60
        assert [r.split()[4] for r in rows[:3]] == ["0", "1", "2"]


def test_space_fixed_input(write, tmp_path):
    lines = [f"2026-03-01T00:{i:02d}:00 7000 0 0" for i in range(5)]
    out = nairas(write, tmp_path, oem_text([({"REF_FRAME": "EME2000"}, lines)]), fast=True)
    rows = np.loadtxt(out, comments="#")
    assert rows.shape == (5, 9)
    assert np.all((rows[:, 8] >= 0) & (rows[:, 8] < 360))


@pytest.mark.parametrize("segments, message", [
    ([({}, ["2026-01-01T00:01:00 6778 0 0", "2026-01-01T00:00:00 6778 0 0"])], "time order"),
    ([({}, ["2026-01-01T00:00:00 6778 0 0", "2026-01-01T00:00:00 6778 0 0"])], "time order"),
    ([({"OBJECT_NAME": "A"}, ["2026-01-01T00:00:00 6778 0 0"]),
      ({"OBJECT_NAME": "B"}, ["2026-01-01T00:01:00 6778 0 0"])], "more than one object"),
])
def test_bad_trajectories(write, tmp_path, segments, message):
    with pytest.raises(conv.OEMError, match=message):
        nairas(write, tmp_path, oem_text(segments))
    assert not os.path.exists(tmp_path / "trajectory_1.txt")


@pytest.mark.parametrize("step", [-1, float("nan"), float("inf"), 0.0004])
def test_bad_step(write, tmp_path, step):
    # nan and inf used to crash with a Python error, and a step under a
    # millisecond was silently treated as 0 (keep every point)
    with pytest.raises(conv.ConverterError, match="time step"):
        nairas(write, tmp_path, oem_text([({}, [])]), step_seconds=step)
