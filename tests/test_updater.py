"""The in-app updater, with GitHub replaced by a fake so no network is used."""

import hashlib
import json
import os
from urllib.parse import urlparse

import pytest

import updater

OLD = b'__version__ = "1.2.0"\n'
NEW = b'__version__ = "1.3.0"\n'
TAG = "v1.3.0"
SUMS_URL = f"https://github.com/someone/converter/releases/download/{TAG}/SHA256SUMS"


def sums_for(files):
    return "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                   for name, data in files.items()).encode()


class FakeGitHub:
    """Serves a latest release, its SHA256SUMS asset, and the files at its tag."""

    def __init__(self):
        self.tag = TAG
        self.files = {name: (NEW if name == "xyz_to_lla.py" else f"# new {name}\n".encode())
                      for name in updater.UPDATE_FILES}
        self.sums = sums_for(self.files)
        self.has_sums = True
        self.has_release = True
        self.fetched = []

    def release_json(self):
        assets = [{"name": "SHA256SUMS", "browser_download_url": SUMS_URL}] if self.has_sums else []
        return json.dumps({"tag_name": self.tag, "assets": assets}).encode()

    def fetch(self, url, what, accept=None):
        self.fetched.append(url)
        if url == updater._api_latest_url():
            if not self.has_release:
                raise updater.UpdateError(f"{what} was not found on GitHub ({url}).")
            return self.release_json()
        if url == SUMS_URL:
            return self.sums
        for name, data in self.files.items():
            if url == updater._raw_url(self.tag, name):
                return data
        raise updater.UpdateError(f"{what} was not found on GitHub ({url}).")


@pytest.fixture
def github(monkeypatch, tmp_path):
    """An app folder with version 1.2.0, and a fake GitHub whose latest release is 1.3.0."""
    app = tmp_path / "app"
    app.mkdir()
    for name in updater.UPDATE_FILES:
        (app / name).write_bytes(OLD if name == "xyz_to_lla.py" else f"# old {name}\n".encode())
    fake = FakeGitHub()
    monkeypatch.setattr(updater, "_fetch", fake.fetch)
    monkeypatch.setattr(updater, "APP_DIR", str(app))
    monkeypatch.setattr(updater, "GITHUB_OWNER", "someone")
    monkeypatch.setattr(updater, "GITHUB_REPO", "converter")
    fake.app = app
    return fake


def assert_unchanged(app):
    assert (app / "xyz_to_lla.py").read_bytes() == OLD
    assert sorted(os.listdir(app)) == sorted(updater.UPDATE_FILES)


@pytest.mark.parametrize("a, b", [("1.10.0", "1.9.0"), ("2.0", "1.99.99"), ("1.2.1", "1.2"),
                                  ("1.3.0rc1", "1.2.9")])
def test_version_order(a, b):
    assert updater.parse_version(a) > updater.parse_version(b)


def test_check_reports_newer_release_only(github):
    assert updater.check("1.2.0") == "1.3.0"
    assert updater.check("1.3.0") is None
    assert updater.check("1.4.0") is None


def test_check_uses_only_the_release_api(github):
    updater.check("1.2.0")
    assert github.fetched == [updater._api_latest_url()]


def test_install_replaces_files_and_keeps_backups(github):
    app = github.app
    assert updater.install("1.2.0") == "1.3.0"
    assert (app / "xyz_to_lla.py").read_bytes() == NEW
    assert (app / "xyz_to_lla.py.bak").read_bytes() == OLD
    assert (app / "converter_gui.py").read_bytes() == b"# new converter_gui.py\n"
    assert not [n for n in os.listdir(app) if n.endswith(".new")]


def test_files_come_from_the_release_tag_not_main(github):
    updater.install("1.2.0")
    raw = [urlparse(u) for u in github.fetched
           if urlparse(u).hostname == "raw.githubusercontent.com"]
    assert raw and all(u.path.split("/")[3] == TAG for u in raw)
    assert not any("/main/" in urlparse(u).path for u in github.fetched)


def test_windows_line_endings_are_kept_byte_for_byte(github):
    github.files["converter_gui.py"] = b"# new\r\nx = 1\r\n"
    github.sums = sums_for(github.files)
    updater.install("1.2.0")
    assert (github.app / "converter_gui.py").read_bytes() == b"# new\r\nx = 1\r\n"


def test_tampered_file_changes_nothing(github):
    github.files["converter_gui.py"] = b"import os  # something sneaky\n"
    with pytest.raises(updater.UpdateError, match="does not match its checksum"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_missing_checksum_file_changes_nothing(github):
    github.has_sums = False
    with pytest.raises(updater.UpdateError, match="still being prepared"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_checksum_file_missing_an_entry_changes_nothing(github):
    del github.files["updater.py"]
    github.sums = sums_for(github.files)
    with pytest.raises(updater.UpdateError, match="no entry for updater.py"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_unreadable_checksum_file_changes_nothing(github):
    github.sums = b"this is not a checksum file\n"
    with pytest.raises(updater.UpdateError, match="could not read"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_broken_file_in_release_changes_nothing(github):
    github.files["converter_gui.py"] = b"def broken(:\n"
    github.sums = sums_for(github.files)
    with pytest.raises(updater.UpdateError, match="has an error"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_missing_file_in_release_changes_nothing(github):
    sums = github.sums
    del github.files["updater.py"]
    github.sums = sums  # checksum lists it, but the file is gone
    with pytest.raises(updater.UpdateError, match="not found"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_tag_must_match_version_in_code(github):
    github.files["xyz_to_lla.py"] = b'__version__ = "1.2.5"\n'
    github.sums = sums_for(github.files)
    with pytest.raises(updater.UpdateError, match="does not match its tag"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


@pytest.mark.parametrize("tag", ["main", "v1.3.0/../../evil", "latest", "v1"])
def test_odd_tag_names_are_refused(github, tag):
    github.tag = tag
    with pytest.raises(updater.UpdateError, match="not a version number"):
        updater.check("1.2.0")


def test_no_releases_yet(github):
    github.has_release = False
    with pytest.raises(updater.UpdateError, match="No releases"):
        updater.check("1.2.0")


def test_no_update_when_already_newest(github):
    with pytest.raises(updater.UpdateError, match="newest"):
        updater.install("1.3.0")


def test_refuses_to_overwrite_a_pip_install(github, monkeypatch):
    monkeypatch.setattr(updater, "APP_DIR", "/usr/lib/python3/site-packages")
    with pytest.raises(updater.UpdateError, match="pip install --upgrade"):
        updater.install("1.2.0")


def test_pip_command_pins_the_release():
    assert updater.pip_upgrade_command("1.3.0").endswith(".git@v1.3.0")
    assert updater.pip_upgrade_command().endswith(".git")


def test_parse_checksums_accepts_sha256sum_output():
    h = "a" * 64
    assert updater.parse_checksums(f"{h}  one.py\n{h} *two.py\n\n") == {"one.py": h, "two.py": h}


def test_not_configured(monkeypatch):
    monkeypatch.setattr(updater, "GITHUB_OWNER", "YOUR_GITHUB_USERNAME")
    assert not updater.is_configured()
    with pytest.raises(updater.UpdateError, match="not set up"):
        updater.check("1.0.0")


def test_real_repo_version_matches_this_code():
    """The version updater reads from xyz_to_lla.py is the one the app reports."""
    import xyz_to_lla
    here = os.path.dirname(os.path.abspath(updater.__file__))
    with open(os.path.join(here, "xyz_to_lla.py"), encoding="utf-8") as f:
        assert updater._version_in(f.read()) == xyz_to_lla.__version__
