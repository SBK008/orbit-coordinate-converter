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


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt",
                    reason="creating symlinks needs extra rights on Windows")
def test_temp_file_never_follows_a_planted_link(write, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me\n")
    out = tmp_path / "out.csv"
    os.symlink(victim, str(out) + ".part")
    src = write("in.csv", "x,y,z\n6378137,0,0\n")
    conv.convert_csv(src, str(out), "x", "y", "z", 10, progress=lambda m: None)
    assert victim.read_text() == "keep me\n"
    assert "lat" in out.read_text()


def test_check_paths(write):
    src = write("in.csv", "x,y,z\n")
    with pytest.raises(conv.ConverterError, match="different"):
        conv.check_paths(src, src)
    with pytest.raises(conv.ConverterError, match="not found"):
        conv.check_paths(src + ".missing", "out.csv")


def test_check_paths_refuses_a_folder_as_output(write, tmp_path):
    # This used to fail with a Python error after the whole file was converted
    src = write("in.csv", "x,y,z\n")
    folder = tmp_path / "results"
    folder.mkdir()
    with pytest.raises(conv.ConverterError, match="is a folder"):
        conv.check_paths(src, str(folder))


def test_check_paths_catches_another_name_for_the_input(write, tmp_path):
    # On Windows and macOS, "Orbit.oem" and "orbit.oem" are the same file. A hard
    # link is another name for the same file on every system.
    src = write("in.csv", "x,y,z\n")
    link = tmp_path / "other_name.csv"
    os.link(src, link)
    with pytest.raises(conv.ConverterError, match="different"):
        conv.check_paths(src, str(link))


def test_output_permissions_follow_the_umask_without_changing_it(write, tmp_path, monkeypatch):
    # The umask used to be read by briefly setting it to 0 for the whole
    # process, which made files other threads created in that moment
    # world-writable. The output now gets the umask from the system instead.
    if os.name != "posix":
        pytest.skip("Unix file permissions")
    src = write("in.csv", "x,y,z\n6378137,0,0\n")
    out = tmp_path / "o.csv"
    real_umask = os.umask
    old = real_umask(0o027)
    calls = []
    try:
        monkeypatch.setattr(os, "umask", lambda m: calls.append(m) or real_umask(m))
        conv.convert_csv(src, str(out), "x", "y", "z", 10, progress=lambda m: None)
    finally:
        real_umask(old)
    assert oct(out.stat().st_mode & 0o777) == oct(0o640)
    assert calls == []
    assert not hasattr(conv, "_UMASK")


def test_replaced_output_keeps_its_permissions(write, tmp_path):
    # A private output used to become readable by everyone when converted again
    if os.name != "posix":
        pytest.skip("Unix file permissions")
    src = write("in.csv", "x,y,z\n6378137,0,0\n")
    out = tmp_path / "o.csv"
    out.write_text("old")
    out.chmod(0o600)
    conv.convert_csv(src, str(out), "x", "y", "z", 10, progress=lambda m: None)
    assert oct(out.stat().st_mode & 0o777) == oct(0o600)
    assert "lat" in out.read_text()


def test_long_output_name(write, tmp_path):
    # A 254-character name is allowed, but the temporary ".<random>.part" name
    # next to it used to be too long, so the conversion failed
    src = write("in.csv", "x,y,z\n6378137,0,0\n")
    out = tmp_path / ("a" * 250 + ".csv")
    conv.convert_csv(src, str(out), "x", "y", "z", 10, progress=lambda m: None)
    assert out.read_text().startswith("x,y,z,lat,lon,alt")
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".part")]


@pytest.mark.parametrize("text", ["x,y,z,lat\n6378137,0,0,51.5\n", "x,y,z,alt\n"])
def test_input_columns_named_like_the_output_are_refused(write, tmp_path, text):
    # Their values used to be silently replaced by the converted ones
    src = write("in.csv", text)
    out = tmp_path / "o.csv"
    with pytest.raises(conv.ConverterError, match="already has a column named"):
        conv.convert_csv(src, str(out), "x", "y", "z", 10, progress=lambda m: None)
    assert not out.exists()


def test_columns_differing_only_in_case_are_kept(write, tmp_path):
    src = write("in.csv", "x,y,z,LAT\n6378137,0,0,51.5\n")
    out = tmp_path / "o.csv"
    conv.convert_csv(src, str(out), "x", "y", "z", 10, progress=lambda m: None)
    df = pd.read_csv(out)
    assert list(df.columns) == ["x", "y", "z", "LAT", "lat", "lon", "alt"]
    assert df["LAT"][0] == 51.5


def test_os_error_messages_name_the_right_file(tmp_path):
    src, out = str(tmp_path / "in.csv"), str(tmp_path / "out.csv")
    e = PermissionError(13, "Permission denied", src)
    assert conv.describe_os_error(e, src, out) == f"Could not read {src}: Permission denied."
    e = FileNotFoundError(2, "No such file or directory", src)
    assert "input file" in conv.describe_os_error(e, src, out)
    e = PermissionError(13, "Permission denied", out + ".1234.part", out)
    assert "close it and try again" in conv.describe_os_error(e, src, out)
    e = OSError(28, "No space left on device")
    assert conv.describe_os_error(e, src, out, name=os.path.basename) == \
        "Could not write out.csv: No space left on device."


def test_command_line_reports_os_errors_without_a_traceback(write, tmp_path):
    import errno
    import subprocess
    import sys
    # Fill the disk the moment the output is written
    code = ("import sys, errno, xyz_to_lla as c\n"
            "def full(*a, **k): raise OSError(errno.ENOSPC, 'No space left on device')\n"
            "c.convert_csv = full\n"
            "sys.argv = ['xyz_to_lla', sys.argv[1], sys.argv[2]]\n"
            "c.main()\n")
    src = write("in.csv", "x,y,z\n6378137,0,0\n")
    out = str(tmp_path / "o.csv")
    r = subprocess.run([sys.executable, "-c", code, src, out], capture_output=True, text=True,
                       cwd=os.path.dirname(conv.__file__))
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert f"Could not write {out}: No space left on device." in r.stderr
    assert errno.ENOSPC


def test_unknown_separator(write, tmp_path):
    src = write("in.csv", "x,y,z\n6378137,0,0\n")
    with pytest.raises(ValueError):
        conv.convert_csv(src, str(tmp_path / "o.csv"), "x", "y", "z", 10, separator="tab")
