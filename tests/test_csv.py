"""Core conversion math, CSV input, output options and safe writes."""

import os

import numpy as np
import pandas as pd
import pytest

import xyz_to_lla as conv

A = 6378137.0          # WGS84 equatorial radius (m)
B = 6356752.314245     # WGS84 polar radius (m)


# ----------------------------------------------------------------- core math

@pytest.mark.parametrize("xyz, lla", [
    ((A, 0, 0), (0, 0, 0)),
    ((0, A, 0), (0, 90, 0)),
    ((-A, 0, 0), (0, 180, 0)),
    ((0, 0, B), (90, 0, 0)),
    ((0, 0, -B), (-90, 0, 0)),
    ((A + 400_000, 0, 0), (0, 0, 400_000)),
])
def test_known_points(xyz, lla):
    lat, lon, alt = conv.xyz_to_lla(*xyz)
    assert lat == pytest.approx(lla[0], abs=1e-9)
    assert abs(lon) == pytest.approx(abs(lla[1]), abs=1e-9)   # 180 may come back as -180
    assert alt == pytest.approx(lla[2], abs=1e-6)


def test_round_trip_random_points():
    from pyproj import Transformer
    rng = np.random.default_rng(0)
    lat = rng.uniform(-89.9, 89.9, 10_000)
    lon = rng.uniform(-179.9, 179.9, 10_000)
    alt = rng.uniform(-100, 40_000_000, 10_000)
    x, y, z = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True).transform(lon, lat, alt)
    lat2, lon2, alt2 = conv.xyz_to_lla(x, y, z)
    assert np.abs(lat2 - lat).max() < 1e-9
    assert np.abs(lon2 - lon).max() < 1e-9
    assert np.abs(alt2 - alt).max() < 1e-5


# ----------------------------------------------------------------- CSV input

def test_csv_keeps_original_columns_exactly(write, tmp_path):
    src = write("in.csv", "id,x,y,z,note\n1,6378137,0,0,NA\n2,0,6378137,0,\n"
                          "3,1e-12,0,6356752.314245,hello world\n")
    out = str(tmp_path / "out.csv")
    assert conv.convert_csv(src, out, "x", "y", "z", 1000, progress=lambda m: None) == 3
    lines = open(out).read().splitlines()
    assert lines[0] == "id,x,y,z,note,lat,lon,alt"
    assert lines[1].startswith("1,6378137,0,0,NA,")       # "NA" text is not erased
    assert lines[2].startswith("2,0,6378137,0,,")          # empty stays empty
    assert lines[3].startswith("3,1e-12,0,")               # 1e-12 is not rounded to 0


def test_csv_space_separated(write, tmp_path):
    src = write("in.csv", "id,x,y,z,note\n1,6378137,0,0,\n2,0,6378137,0,two words\n")
    out = str(tmp_path / "out.txt")
    conv.convert_csv(src, out, "x", "y", "z", 1000, progress=lambda m: None, separator="space")
    lines = open(out).read().splitlines()
    assert lines[0] == "id x y z note lat lon alt"
    assert lines[1].split(" ")[4] == "NaN"                 # empty value keeps its column
    assert '"two words"' in lines[2]
    assert len(pd.read_csv(out, sep=" ").columns) == 8      # reads back cleanly


def test_csv_no_header(write, tmp_path):
    src = write("in.csv", "x,y,z\n6378137,0,0\n")
    out = str(tmp_path / "out.csv")
    conv.convert_csv(src, out, "x", "y", "z", 1000, progress=lambda m: None, header=False)
    assert open(out).read().splitlines() == ["6378137,0,0,0.000000000,0.000000000,0.000000000"]


def test_csv_chunks_match_single_pass(write, tmp_path):
    rng = np.random.default_rng(1)
    xyz = rng.uniform(-4e7, 4e7, (1000, 3))
    xyz[:, 0] += np.sign(xyz[:, 0]) * A
    src = write("in.csv", "x,y,z\n" + "\n".join(",".join(f"{v:.4f}" for v in r) for r in xyz) + "\n")
    one, many = str(tmp_path / "one.csv"), str(tmp_path / "many.csv")
    conv.convert_csv(src, one, "x", "y", "z", 10_000, progress=lambda m: None)
    conv.convert_csv(src, many, "x", "y", "z", 7, progress=lambda m: None)   # 143 chunks
    assert open(one).read() == open(many).read()


def test_csv_column_names_ignore_case_and_spaces(write, tmp_path):
    src = write("in.csv", "X , Y , Z\n6378137,0,0\n")
    out = str(tmp_path / "out.csv")
    assert conv.convert_csv(src, out, "x", "y", "z", 1000, progress=lambda m: None) == 1


def test_csv_with_excel_bom(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("x,y,z\n6378137,0,0\n", encoding="utf-8-sig")
    out = str(tmp_path / "out.csv")
    assert conv.convert_csv(str(src), out, "x", "y", "z", 1000, progress=lambda m: None) == 1


def test_csv_header_only(write, tmp_path):
    src = write("in.csv", "x,y,z\n")
    out = str(tmp_path / "out.csv")
    assert conv.convert_csv(src, out, "x", "y", "z", 1000, progress=lambda m: None) == 0
    assert open(out).read() == "x,y,z,lat,lon,alt\n"


@pytest.mark.parametrize("text, message", [
    ("x,y,z\n1,2,3\n4,abc,6\n", "Data row 2: column y"),
    ("x,y,z\n1,,3\n", "Data row 1: column y"),
    ("a,b\n1,2\n", "not found"),
    ("", "is empty"),
    ("x,y,z\n1,2,3\n4,5,6,7\n", "Could not read"),
])
def test_csv_bad_input(write, tmp_path, text, message):
    src = write("in.csv", text)
    out = str(tmp_path / "out.csv")
    with pytest.raises(conv.ConverterError, match=message):
        conv.convert_csv(src, out, "x", "y", "z", 1000, progress=lambda m: None)
    assert not os.path.exists(out)


# ----------------------------------------------------------------- safe writes

def test_failed_run_keeps_old_output_and_leaves_no_temp_file(write, tmp_path):
    out = tmp_path / "out.csv"
    out.write_text("previous result\n")
    src = write("in.csv", "x,y,z\n" + "6378137,0,0\n" * 50 + "1,bad,3\n")
    with pytest.raises(conv.ConverterError):
        conv.convert_csv(src, str(out), "x", "y", "z", 10, progress=lambda m: None)
    assert out.read_text() == "previous result\n"
    assert sorted(os.listdir(tmp_path)) == ["in.csv", "out.csv"]


def test_check_paths(write):
    src = write("in.csv", "x,y,z\n")
    with pytest.raises(conv.ConverterError, match="different"):
        conv.check_paths(src, src)
    with pytest.raises(conv.ConverterError, match="not found"):
        conv.check_paths(src + ".missing", "out.csv")


def test_unknown_separator(write, tmp_path):
    src = write("in.csv", "x,y,z\n6378137,0,0\n")
    with pytest.raises(ValueError):
        conv.convert_csv(src, str(tmp_path / "o.csv"), "x", "y", "z", 10, separator="tab")
