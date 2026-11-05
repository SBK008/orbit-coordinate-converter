"""The in-app updater, with GitHub replaced by a fake so no network is used."""

import base64
import hashlib
import io
import json
import os
from urllib.parse import urlparse

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import updater

OLD = b'__version__ = "1.2.0"\n'
NEW = b'__version__ = "1.3.0"\n'
TAG = "v1.3.0"
SUMS_URL = f"https://github.com/someone/converter/releases/download/{TAG}/SHA256SUMS"
SIG_URL = SUMS_URL + ".minisig"


class SigningKey:
    """A throwaway signing key that writes minisign-format keys and signatures."""

    def __init__(self, key_id=b"testkey1"):
        self.private = Ed25519PrivateKey.generate()
        self.key_id = key_id
        raw = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.public = base64.b64encode(b"Ed" + key_id + raw).decode()

    def sign(self, data, comment=f"orbit-converter {TAG}"):
        signature = self.private.sign(hashlib.blake2b(data, digest_size=64).digest())
        comment_signature = self.private.sign(signature + comment.encode())
        return (f"untrusted comment: test signature\n"
                f"{base64.b64encode(b'ED' + self.key_id + signature).decode()}\n"
                f"trusted comment: {comment}\n"
                f"{base64.b64encode(comment_signature).decode()}\n")


RELEASE_KEY = SigningKey()


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
        self.has_sig = True
        self.sig = None  # None: sign whatever self.sums is when it is fetched
        self.has_release = True
        self.fetched = []

    def release_json(self):
        assets = [{"name": "SHA256SUMS", "browser_download_url": SUMS_URL}] if self.has_sums else []
        if self.has_sig:
            assets.append({"name": "SHA256SUMS.minisig", "browser_download_url": SIG_URL})
        return json.dumps({"tag_name": self.tag, "assets": assets}).encode()

    def fetch(self, url, what, accept=None):
        self.fetched.append(url)
        if url == updater._api_latest_url():
            if not self.has_release:
                raise updater.UpdateError(f"{what} was not found on GitHub ({url}).")
            return self.release_json()
        if url == SUMS_URL:
            return self.sums
        if url == SIG_URL:
            return (self.sig or RELEASE_KEY.sign(self.sums)).encode()
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
    monkeypatch.setattr(updater, "TRUSTED_KEYS", [RELEASE_KEY.public])
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


def test_null_byte_in_file_changes_nothing(github):
    github.files["converter_gui.py"] = b"x = 1\x00\n"
    github.sums = sums_for(github.files)
    with pytest.raises(updater.UpdateError, match="nothing was changed"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


@pytest.mark.parametrize("url", [
    "https://api.github.com/repos/a/b/releases/latest",
    "https://raw.githubusercontent.com/a/b/v1.3.0/updater.py",
    "https://github.com/a/b/releases/download/v1.3.0/SHA256SUMS",
    "https://release-assets.githubusercontent.com/some/asset",
])
def test_github_https_urls_are_allowed(url):
    updater.check_url(url)


@pytest.mark.parametrize("url", [
    "http://raw.githubusercontent.com/a/b/v1.3.0/updater.py",   # not HTTPS
    "file:///etc/passwd",
    "ftp://github.com/x",
    "https://evil.example.com/SHA256SUMS",
    "https://github.com.evil.example.com/x",
    "https://raw.githubusercontent.com@evil.example.com/x",
])
def test_other_urls_are_refused(url):
    with pytest.raises(updater.UpdateError, match="Refused"):
        updater.check_url(url)


def test_real_fetch_checks_the_url_before_connecting():
    with pytest.raises(updater.UpdateError, match="Refused"):
        updater._fetch("file:///etc/passwd", "test")


def test_redirect_away_from_github_is_refused():
    handler = updater._HTTPSOnlyRedirects()
    req = updater.urllib.request.Request("https://github.com/a/b/releases/download/v1/SHA256SUMS")
    with pytest.raises(updater.UpdateError, match="Refused"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://evil.example.com/x")


def test_oversized_download_is_refused(monkeypatch):
    monkeypatch.setattr(updater, "MAX_DOWNLOAD_BYTES", 10)
    assert updater.read_limited(io.BytesIO(b"0123456789"), "f") == b"0123456789"
    with pytest.raises(updater.UpdateError, match="larger than expected"):
        updater.read_limited(io.BytesIO(b"0123456789!"), "f")


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


def test_pip_command_pins_the_release(monkeypatch):
    monkeypatch.setattr(updater, "_pip_has", lambda name: False)
    assert updater.pip_upgrade_command("1.4.0") == "pip install --upgrade orbit-converter==1.4.0"
    assert updater.pip_upgrade_command() == "pip install --upgrade orbit-converter"


def test_pip_command_removes_the_old_package_name_first(monkeypatch):
    monkeypatch.setattr(updater, "_pip_has", lambda name: name == "coordinate-converter")
    lines = updater.pip_upgrade_command("1.4.0").splitlines()
    assert lines == ["pip uninstall -y coordinate-converter",
                     "pip install --upgrade orbit-converter==1.4.0"]


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


# ---- Release signatures ------------------------------------------------------

def test_missing_signature_changes_nothing(github):
    github.has_sig = False
    with pytest.raises(updater.UpdateError, match="signature is not there yet"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_signature_from_another_key_changes_nothing(github):
    github.sig = SigningKey(b"otherkey").sign(github.sums)
    with pytest.raises(updater.UpdateError, match="not signed by the app's release key"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_forged_key_id_changes_nothing(github):
    # Right key ID, wrong private key: the signature itself must not verify
    github.sig = SigningKey(RELEASE_KEY.key_id).sign(github.sums)
    with pytest.raises(updater.UpdateError, match="signature does not match"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_checksums_changed_after_signing_changes_nothing(github):
    github.sig = RELEASE_KEY.sign(github.sums)
    github.files["converter_gui.py"] = b"# swapped\n"
    github.sums = sums_for(github.files)
    with pytest.raises(updater.UpdateError, match="signature does not match"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_edited_trusted_comment_changes_nothing(github):
    lines = RELEASE_KEY.sign(github.sums, "orbit-converter v1.2.0").splitlines()
    lines[2] = f"trusted comment: orbit-converter {TAG}"
    github.sig = "\n".join(lines)
    with pytest.raises(updater.UpdateError, match="signature does not match"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


def test_signature_for_another_release_changes_nothing(github):
    github.sig = RELEASE_KEY.sign(github.sums, "orbit-converter v1.2.9")
    with pytest.raises(updater.UpdateError, match="different release"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


@pytest.mark.parametrize("sig", ["", "not a signature", "a\nb\nc\nd",
                                 "untrusted comment: x\n!!!\ntrusted comment: y\n!!!"])
def test_malformed_signature_changes_nothing(github, sig):
    github.sig = sig or " "
    with pytest.raises(updater.UpdateError, match="expected format"):
        updater.install("1.2.0")
    assert_unchanged(github.app)


# Made with the real minisign 0.12 tool, so the format is checked against it
# rather than only against this test file's own signer.
MINISIGN_PUBLIC = "RWR0fCuGbKO/gmjwMOR49wKR9FMH92w4RbMSX2UtuUR8cgoQkWf4INmC"
MINISIGN_DATA = b"aaaa  xyz_to_lla.py\n"
MINISIGN_PREHASHED = """untrusted comment: signature from minisign secret key
RUR0fCuGbKO/gnzqS4cKasNxKl62lNNWKJbCHLudngTyNknVYlUBs1cs7N2EVWnoOeN/dlUKIH0+Ym3Hhg4zQYjFPoKKqq+C4QQ=
trusted comment: test release
sonU+pEgFKsxygqagf887GDiqizTyE42stM6OsjcYJc+ANPYbWh7kkcVFIUWb4z+iRV/ABrjXk2vIigW6AQdAQ==
"""
MINISIGN_LEGACY = """untrusted comment: signature from minisign secret key
RWR0fCuGbKO/gr8zp53Da9zp0VovLvTRzA7g8R1m9rZZ3dZSVt1HN0OdaRejHpHfv1zIJLkyXoB9PAG1TGhViXbC/o9fZ387wg4=
trusted comment: legacy
rGJfWFJA2nKEx3V7sW9KNXp9jn3hvKE5cx7tCbwrBUcEVvzOjdgzI09B79mw2dCTrhmhgd59KU0zuPrWkbOQCw==
"""


@pytest.mark.parametrize("sig, word", [(MINISIGN_PREHASHED, "release"),
                                       (MINISIGN_LEGACY, "legacy")])
def test_real_minisign_signatures_verify(sig, word):
    updater.verify_signature(MINISIGN_DATA, sig, word, keys=[MINISIGN_PUBLIC])
    with pytest.raises(updater.UpdateError, match="does not match"):
        updater.verify_signature(MINISIGN_DATA + b"x", sig, word, keys=[MINISIGN_PUBLIC])


def test_release_key_is_set():
    """The shipped updater must trust exactly the maintainer's real key."""
    assert updater.TRUSTED_KEYS, "Add the release public key to TRUSTED_KEYS in updater.py"
    for key in updater.TRUSTED_KEYS:
        raw = base64.b64decode(key, validate=True)
        assert len(raw) == 42 and raw[:2] == b"Ed", f"{key!r} is not a minisign public key"


def test_standalone_app_is_never_patched(github, monkeypatch):
    # In a packaged app the code is sealed inside the app (and covered by its
    # signature), so the updater must point to the download, not swap files
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    assert updater.is_packaged()
    with pytest.raises(updater.UpdateError, match="standalone app"):
        updater.install("1.2.0")
    assert_unchanged(github.app)
    assert updater.check("1.2.0") == "1.3.0"     # still tells the user a new version exists


def test_download_page_url(github):
    assert updater.download_page_url() == "https://github.com/someone/converter/releases/latest"
    assert updater.download_page_url("v1.3.0").endswith("/releases/tag/v1.3.0")
