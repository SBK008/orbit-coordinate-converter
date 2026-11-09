"""CCSDS OEM input: parsing, epochs, frames and errors."""

import numpy as np
import pandas as pd
import pytest

import xyz_to_lla as conv
from conftest import oem_text

QUIET = dict(progress=lambda m: None)


def convert(write, tmp_path, text, chunksize=1000, **opts):
    src = write("in.oem", text)
    out = str(tmp_path / "out.csv")
    conv.convert_oem(src, out, chunksize, **QUIET, **opts)
    return pd.read_csv(out, dtype={"epoch": str, "epoch_mjd": str})


def test_earth_fixed_segment(write, tmp_path):
    df = convert(write, tmp_path, oem_text([({}, [
        "2026-10-19T12:00:00.000 6778.137 0 0 0 7.6 0",
        "2026-292T12:01:00.000 0 6778.137 0",
    ])]))
    assert list(df.columns) == conv.OEM_COLUMNS
    assert df.x_ecef_m[0] == pytest.approx(6778137.0)          # km -> m
    assert df.alt[0] == pytest.approx(400_000.0, abs=1e-6)
    assert df.lon[1] == pytest.approx(90.0)
    assert df.epoch.tolist() == ["2026-10-19T12:00:00.000", "2026-292T12:01:00.000"]


def test_comments_covariance_and_two_segments(write, tmp_path):
    text = oem_text([
        ({"OBJECT_NAME": "ONE"}, ["COMMENT a comment", "2026-01-01T00:00:00 6778.137 0 0",
                                  "COVARIANCE_START", "EPOCH = 2026-01-01T00:00:00",
                                  "1 2 3", "COVARIANCE_STOP"]),
        ({"OBJECT_NAME": "TWO", "TIME_SYSTEM": "TAI"}, ["2026-01-01T00:01:00 6778.137 0 0"]),
    ])
    df = convert(write, tmp_path, text)
    assert df.object.tolist() == ["ONE", "TWO"]
    assert df.time_system.tolist() == ["UTC", "TAI"]


@pytest.mark.parametrize("epoch, gregorian, mjd", [
    ("2026-292T12:00:00.000", "2026-10-19T12:00:00.000", "61332.500000000000"),
    ("2024-366T00:00:00", "2024-12-31T00:00:00", "60675.000000000000"),     # leap year
    ("1858-11-17T00:00:00", "1858-11-17T00:00:00", "0.000000000000"),
    ("1858-11-16T12:00:00", "1858-11-16T12:00:00", "-0.500000000000"),
    ("2016-12-31T23:59:60.000", "2016-12-31T23:59:60.000", "57754.000000000000"),  # leap second
])
def test_epoch_formats(write, tmp_path, epoch, gregorian, mjd):
    text = oem_text([({}, [f"{epoch} 6778.137 0 0"])])
    assert convert(write, tmp_path, text, time_format="gregorian").epoch[0] == gregorian
    assert convert(write, tmp_path, text, time_format="mjd").epoch_mjd[0] == mjd


def test_space_separated_oem_output(write, tmp_path):
    src = write("in.oem", oem_text([({"OBJECT_NAME": "ISS (ZARYA)"},
                                     ["2026-01-01T00:00:00 6778.137 0 0"])]))
    out = str(tmp_path / "out.txt")
    conv.convert_oem(src, out, 1000, separator="space", header=False, **QUIET)
    line = open(out).read().splitlines()[0]
    assert line.startswith('"ISS (ZARYA)" 2026-01-01T00:00:00 UTC 6778137.000000000')


def test_chunk_boundaries_match_single_pass(write, tmp_path):
    lines = [f"2026-01-01T00:{i // 60:02d}:{i % 60:02d} {6778.137 * np.cos(i / 50):.6f} "
             f"{6778.137 * np.sin(i / 50):.6f} 10.0" for i in range(500)]
    text = oem_text([({}, lines[:250]), ({"OBJECT_NAME": "SAT2"}, lines[250:])])
    a = convert(write, tmp_path, text, chunksize=10_000)
    b = convert(write, tmp_path, text, chunksize=7)
    pd.testing.assert_frame_equal(a, b)


def test_space_fixed_frames_are_rotated(write, tmp_path):
    lines = [f"2026-03-01T00:{i:02d}:00 7000 0 0" for i in range(30)]
    exact = convert(write, tmp_path, oem_text([({"REF_FRAME": "EME2000"}, lines)]))
    fast = convert(write, tmp_path, oem_text([({"REF_FRAME": "EME2000"}, lines)]), fast=True)
    # The Earth turns under a fixed inertial point, so longitude must change
    assert abs(exact.lon[29] - exact.lon[0]) > 5
    r = np.hypot(np.hypot(exact.x_ecef_m, exact.y_ecef_m), exact.z_ecef_m)
    assert np.allclose(r, 7_000_000, atol=1e-6)                   # rotation keeps the length
    d = np.hypot(np.hypot(exact.x_ecef_m - fast.x_ecef_m, exact.y_ecef_m - fast.y_ecef_m),
                 exact.z_ecef_m - fast.z_ecef_m)
    assert d.max() < 1e-4                                           # fast mode within 0.1 mm


def test_teme_frame(write, tmp_path):
    df = convert(write, tmp_path, oem_text([({"REF_FRAME": "TEME"},
                                             ["2026-03-01T00:00:00 7000 0 0"])]))
    assert np.hypot(np.hypot(df.x_ecef_m[0], df.y_ecef_m[0]), df.z_ecef_m[0]) == \
        pytest.approx(7_000_000)


@pytest.mark.parametrize("text, message", [
    ("<?xml version='1.0'?>\n", "XML"),
    ("hello\n", "does not look like"),
    (oem_text([({"CENTER_NAME": "MARS"}, [])]), "Only EARTH"),
    (oem_text([({"REF_FRAME": "MOD"}, [])]), "not supported"),
    (oem_text([({"TIME_SYSTEM": "MET"}, [])]), "not supported"),
    (oem_text([({"REF_FRAME": None}, [])]), "missing REF_FRAME"),
    (oem_text([({}, ["2026-01-01T00:00:00 1 2"])]), "at least an epoch"),
    (oem_text([({}, ["2026-01-01T00:00:00 1 two 3"])]), "as numbers"),
    # These used to be accepted and written out as empty lat, lon, and alt
    (oem_text([({}, ["2026-01-01T00:00:00 nan 0 0"])]), "as numbers"),
    (oem_text([({}, ["2026-01-01T00:00:00 6778 inf 0"])]), "as numbers"),
    (oem_text([({}, ["2026-01-01T00:00:00 6778 0 1e999"])]), "as numbers"),
    (oem_text([({}, ["2026-02-30T00:00:00 6778 0 0"])]), "not a real date"),
    (oem_text([({}, ["2026-01-01T25:00:00 6778 0 0"])]), "not a real date"),
    (oem_text([({}, ["2026/01/01 6778 0 0"])]), "unrecognized|not in a supported"),
    # Second 60 only exists as a UTC leap second, at 23:59:60
    (oem_text([({}, ["2026-01-01T12:30:60.500 6778 0 0"])]), "not a real date"),
    (oem_text([({}, ["2016-12-31T23:59:61 6778 0 0"])]), "not a real date"),
    (oem_text([({"TIME_SYSTEM": "TAI"}, ["2016-12-31T23:59:60 6778 0 0"])]), "not a real date"),
    # float() reads "7_000" as 7000, but it is not a number in an OEM file
    (oem_text([({}, ["2026-01-01T00:00:00 6_778 0 0"])]), "as numbers"),
    ("CCSDS_OEM_VERS = 2.0\nMETA_START\nCENTER_NAME = EARTH\n", "no matching META_STOP"),
])
def test_bad_oem_files(write, tmp_path, text, message):
    with pytest.raises(conv.OEMError, match=message):
        convert(write, tmp_path, text)


def test_unknown_time_format(write, tmp_path):
    with pytest.raises(ValueError):
        convert(write, tmp_path, oem_text([({}, [])]), time_format="julian")


def test_utc_leap_second_is_accepted(write, tmp_path):
    df = convert(write, tmp_path, oem_text([({}, ["2016-12-31T23:59:60.500 6778.137 0 0"])]),
                 time_format="mjd")
    assert df["epoch_mjd"][0] == "57754.000005787037"
