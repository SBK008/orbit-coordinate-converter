"""--limit / "Only the first N points": every output keeps just the first N points."""

import subprocess
import sys

import pandas as pd
import pytest

import xyz_to_lla as conv
from conftest import data_rows, oem_text

QUIET = dict(progress=lambda m: None)
LINES = [f"2026-01-01T00:{i // 60:02d}:{i % 60:02d} 6778.137 {i} 0" for i in range(25)]


@pytest.mark.parametrize("chunksize", [1000, 4])
def test_csv_limit(write, tmp_path, chunksize):
    src = write("in.csv", "x,y,z,name\n" + "".join(f"6378137,{i},0,p{i}\n" for i in range(25)))
    out = str(tmp_path / "out.csv")
    assert conv.convert_csv(src, out, "x", "y", "z", chunksize, limit=10, **QUIET) == 10
    df = pd.read_csv(out)
    assert list(df["name"]) == [f"p{i}" for i in range(10)]


@pytest.mark.parametrize("chunksize", [1000, 4])
def test_oem_limit(write, tmp_path, chunksize):
    src = write("in.oem", oem_text([({}, LINES)]))
    out = str(tmp_path / "out.csv")
    assert conv.convert_oem(src, out, chunksize, limit=7, **QUIET) == 7
    assert len(pd.read_csv(out)) == 7


@pytest.mark.parametrize("chunksize", [1000, 4])
def test_nairas_limit_matches_head_of_full_file(write, tmp_path, chunksize):
    src = write("in.oem", oem_text([({}, LINES)]))
    full, short = str(tmp_path / "full.txt"), str(tmp_path / "short.txt")
    conv.convert_oem_nairas(src, full, chunksize, **QUIET)
    assert conv.convert_oem_nairas(src, short, chunksize, limit=6, **QUIET) == 6
    assert data_rows(short) == data_rows(full)[:6]
    assert open(short).read().startswith("# NAIRAS")


def test_limit_counts_points_kept_by_step(write, tmp_path):
    src = write("in.oem", oem_text([({}, LINES)]))       # one point a second
    out = str(tmp_path / "t.txt")
    assert conv.convert_oem_nairas(src, out, 1000, step_seconds=5, limit=3, **QUIET) == 3
    secs = [float(r.split()[5]) for r in data_rows(out)]
    assert secs == [0.0, 5.0, 10.0]


def test_limit_larger_than_file_keeps_everything(write, tmp_path):
    src = write("in.oem", oem_text([({}, LINES)]))
    out = str(tmp_path / "out.csv")
    assert conv.convert_oem(src, out, 1000, limit=1000, **QUIET) == 25


def test_rows_after_the_limit_are_not_read(write, tmp_path):
    # A bad row past the limit doesn't matter, since it is never converted
    src = write("in.csv", "x,y,z\n6378137,0,0\n6378137,1,0\n1,abc,3\n")
    out = str(tmp_path / "out.csv")
    assert conv.convert_csv(src, out, "x", "y", "z", 1000, limit=2, **QUIET) == 2


@pytest.mark.parametrize("value, expected", [(None, 0), ("", 0), ("  ", 0), (0, 0),
                                             ("600", 600), (600, 600), ("600.0", 600)])
def test_check_limit_ok(value, expected):
    assert conv.check_limit(value) == expected


@pytest.mark.parametrize("value", ["-1", "2.5", "abc", "nan", "inf"])
def test_check_limit_refuses_bad_values(value):
    with pytest.raises(conv.ConverterError, match="whole number"):
        conv.check_limit(value)


def test_command_line_limit(write, tmp_path):
    src = write("in.oem", oem_text([({}, LINES)]))
    out = str(tmp_path / "t.txt")
    r = subprocess.run([sys.executable, conv.__file__, src, out, "--nairas", "--no-header",
                        "--limit", "4"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert len(open(out).read().splitlines()) == 4
    assert "stopped at the limit of 4" in r.stderr
