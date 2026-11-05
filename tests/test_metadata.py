"""Project files that must agree with the app version."""

import os
import re

import xyz_to_lla

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_citation_version_matches_the_app():
    m = re.search(r"^version:\s*(\S+)", read("CITATION.cff"), re.MULTILINE)
    assert m, "CITATION.cff has no version line"
    assert m.group(1) == xyz_to_lla.__version__, (
        "Update version and date-released in CITATION.cff to match __version__")


def test_changelog_has_a_section_for_this_version():
    assert re.search(rf"^## {re.escape(xyz_to_lla.__version__)}\b", read("CHANGELOG.md"),
                     re.MULTILINE), "Add a CHANGELOG.md section for this version"
