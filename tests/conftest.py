"""Shared helpers for the tests."""

import os
import sys

import pytest

# Import the app from the repo folder, whether or not it is pip-installed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def oem_text(segments, version="2.0"):
    """
    Build a KVN OEM file. segments is a list of (meta_dict, data_lines), where
    data_lines are strings like "2026-10-19T12:00:00.000 6778.137 0 0".
    """
    out = [f"CCSDS_OEM_VERS = {version}", "CREATION_DATE = 2026-11-03T00:00:00",
           "ORIGINATOR = TEST"]
    for meta, lines in segments:
        out.append("META_START")
        m = {"OBJECT_NAME": "SAT", "CENTER_NAME": "EARTH", "REF_FRAME": "ITRF2020",
             "TIME_SYSTEM": "UTC", **meta}
        out += [f"{k} = {v}" for k, v in m.items() if v is not None]
        out.append("META_STOP")
        out += lines
    return "\n".join(out) + "\n"


@pytest.fixture
def write(tmp_path):
    """write("name.ext", text) -> path of a new file in a temporary folder."""
    def _write(name, text):
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        return str(p)
    return _write


def data_rows(path):
    """Lines of a text file, without # comment lines."""
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if not line.startswith("#")]
