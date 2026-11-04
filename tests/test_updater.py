"""The in-app updater, with GitHub replaced by a fake so no network is used."""

import os

import pytest

import updater

OLD = '__version__ = "1.2.0"\n'
NEW = '__version__ = "1.3.0"\n'


@pytest.fixture
def fake_github(monkeypatch, tmp_path):
    """An app folder with version 1.2.0, and a fake GitHub serving version 1.3.0."""
    app = tmp_path / "app"
    app.mkdir()
    for name in updater.UPDATE_FILES:
        (app / name).write_text(OLD if name == "xyz_to_lla.py" else f"# old {name}\n")
    remote = {name: (NEW if name == "xyz_to_lla.py" else f"# new {name}\n")
              for name in updater.UPDATE_FILES}

    def download(name):
        if name not in remote:
            raise updater.UpdateError(f"{name} was not found on GitHub")
        return remote[name]

    monkeypatch.setattr(updater, "_download", download)
    monkeypatch.setattr(updater, "APP_DIR", str(app))
    monkeypatch.setattr(updater, "GITHUB_OWNER", "someone")
    monkeypatch.setattr(updater, "GITHUB_REPO", "converter")
    return app, remote


@pytest.mark.parametrize("a, b", [("1.10.0", "1.9.0"), ("2.0", "1.99.99"), ("1.2.1", "1.2"),
                                  ("1.3.0rc1", "1.2.9")])
def test_version_order(a, b):
    assert updater.parse_version(a) > updater.parse_version(b)


def test_check_reports_newer_version_only(fake_github):
    assert updater.check("1.2.0") == "1.3.0"
    assert updater.check("1.3.0") is None
    assert updater.check("1.4.0") is None


def test_install_replaces_files_and_keeps_backups(fake_github):
    app, _ = fake_github
    assert updater.install("1.2.0") == "1.3.0"
    assert (app / "xyz_to_lla.py").read_text() == NEW
    assert (app / "xyz_to_lla.py.bak").read_text() == OLD
    assert (app / "converter_gui.py").read_text() == "# new converter_gui.py\n"
    assert not [n for n in os.listdir(app) if n.endswith(".new")]


def test_broken_file_on_github_changes_nothing(fake_github):
    app, remote = fake_github
    remote["converter_gui.py"] = "def broken(:\n"
    with pytest.raises(updater.UpdateError, match="has an error"):
        updater.install("1.2.0")
    assert (app / "xyz_to_lla.py").read_text() == OLD
    assert sorted(os.listdir(app)) == sorted(updater.UPDATE_FILES)


def test_missing_file_on_github_changes_nothing(fake_github):
    app, remote = fake_github
    del remote["updater.py"]
    with pytest.raises(updater.UpdateError, match="not found"):
        updater.install("1.2.0")
    assert (app / "xyz_to_lla.py").read_text() == OLD


def test_no_update_when_already_newest(fake_github):
    with pytest.raises(updater.UpdateError, match="newest"):
        updater.install("1.3.0")


def test_refuses_to_overwrite_a_pip_install(fake_github, monkeypatch):
    monkeypatch.setattr(updater, "APP_DIR", "/usr/lib/python3/site-packages")
    with pytest.raises(updater.UpdateError, match="pip install --upgrade"):
        updater.install("1.2.0")


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
