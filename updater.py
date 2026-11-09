"""
Update the app in place from its GitHub releases, without downloading the
whole zip again. Only the few .py files in UPDATE_FILES are fetched.

How it works:
    1. Ask GitHub for the latest published release and read its version from
       the release tag (for example v1.3.0). Drafts and pre-releases are ignored.
    2. If that release is newer than the version running now, download its
       SHA256SUMS file and its SHA256SUMS.minisig signature, and check the
       signature against TRUSTED_KEYS. The private key is kept offline.
    3. Download every file in UPDATE_FILES exactly as it was at that tag.
       Untagged work on the main branch is never installed.
    4. Check every file against SHA256SUMS, check that it is valid Python, and
       check that xyz_to_lla.py says the same version as the tag.
    5. Downloads are HTTPS only, to GitHub's own hosts (redirects included),
       and capped at MAX_DOWNLOAD_BYTES.
    6. Only then write them next to the running copy, keeping the old ones as
       .bak files, so a failed or tampered download never leaves a
       half-updated app. If writing fails partway, the old files are put back.

To publish an update: raise __version__ in xyz_to_lla.py, merge it into main,
and publish a GitHub release tagged with that version. The release workflow
(.github/workflows/release.yml) attaches SHA256SUMS automatically. Then sign
it offline with scripts/sign_release.sh and attach SHA256SUMS.minisig.

If the app was installed with pip, the files live in Python's own folder and
are not overwritten here. pip_upgrade_command() gives the command to run.
"""

import base64
import contextlib
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

# ---- Fill these in with your GitHub details ---------------------------------
GITHUB_OWNER = "SBK008"
GITHUB_REPO = "orbit-coordinate-converter"
# -----------------------------------------------------------------------------

# Files the updater replaces. The list in the NEW updater.py is used from the
# next update on, so a file you add later is picked up one update after that.
# The release workflow hashes this same list into SHA256SUMS.
UPDATE_FILES = ["xyz_to_lla.py", "converter_gui.py", "updater.py"]

# Name on PyPI (pip install orbit-converter), and the name used before 1.4.0
PYPI_NAME = "orbit-converter"
OLD_PIP_NAME = "coordinate-converter"

# Name of the checksum file attached to each release
CHECKSUM_ASSET = "SHA256SUMS"
# Signature of that file, made offline by the maintainer with minisign
SIGNATURE_ASSET = CHECKSUM_ASSET + ".minisig"

# Public keys allowed to sign releases: the second line of a minisign .pub
# file. The matching private key is kept offline, never on GitHub, so someone
# who takes over the GitHub account still can't publish a release this
# updater accepts.
TRUSTED_KEYS = [
    # Samuel Braman release key, ID 4DFE960FFF7DA07C (added in 1.4.0)
    "RWR8oH3/D5b+TQRtJdxqoLRA7kLjUq9mg5BQauO1XTaWfR/v3g3aF+At",
]

TIMEOUT_SECONDS = 15
# The three app files are well under 1 MB. Anything far bigger is refused.
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
# The only places the updater downloads from, including where GitHub redirects
# release downloads to. Everything must be HTTPS.
ALLOWED_HOSTS = {
    "api.github.com",
    "raw.githubusercontent.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
APP_DIR = os.path.dirname(os.path.abspath(__file__))

_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
# Release tags must look like v1.3.0. This also keeps anything odd in a tag
# name out of the download URLs.
_TAG_RE = re.compile(r"^v?(\d+(?:\.\d+){1,3})$")
_SUM_LINE_RE = re.compile(r"^([0-9a-fA-F]{64}) [ *]?(\S+)$")


class UpdateError(Exception):
    """A problem checking for or installing an update. The message is shown to the user."""


def is_configured():
    return "YOUR_" not in GITHUB_OWNER + GITHUB_REPO


def repo_url():
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"


def _pip_has(name):
    """True when pip has a package by this name installed."""
    try:
        importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def pip_upgrade_command(version=None):
    """The pip command to upgrade, pinned to a release when its version is known.

    Copies installed from GitHub before 1.4.0 are registered as
    "coordinate-converter", so the old name is removed first. Otherwise both
    names would claim the same files. Each command goes on its own line, which
    every terminal runs in order when pasted.
    """
    pin = f"=={version}" if version else ""
    command = f"pip install --upgrade {PYPI_NAME}{pin}"
    if _pip_has(OLD_PIP_NAME):
        command = f"pip uninstall -y {OLD_PIP_NAME}\n{command}"
    return command


def _api_latest_url():
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def _raw_url(tag, name):
    return f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{tag}/{name}"


def installed_with_pip():
    """True when these files live inside Python's packages folder (pip install)."""
    parts = APP_DIR.replace("\\", "/").split("/")
    return "site-packages" in parts or "dist-packages" in parts


def parse_version(text):
    """'1.10.2' -> (1, 10, 2). Anything after a number (like 'rc1') is ignored."""
    nums = []
    for piece in text.strip().split("."):
        m = re.match(r"\d+", piece)
        nums.append(int(m.group()) if m else 0)
    return tuple(nums)


def _version_in(source):
    m = _VERSION_RE.search(source)
    if not m:
        raise UpdateError("Could not find __version__ in the new xyz_to_lla.py.")
    return m.group(1)


def check_url(url):
    """Refuse anything that is not HTTPS to one of GitHub's own hosts."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise UpdateError(f"Refused to download from {url}: updates only come over HTTPS "
                          "from GitHub.")


class _HTTPSOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if its target passes check_url."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HTTPSOnlyRedirects)


def read_limited(response, what):
    """Read a response, refusing anything over MAX_DOWNLOAD_BYTES."""
    data = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise UpdateError(f"{what} on GitHub is much larger than expected, so it was not "
                          "downloaded.")
    return data


def _fetch(url, what, accept=None):
    """Download url and return its bytes. what names it in error messages."""
    check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "orbit-converter-updater"})
    if accept:
        req.add_header("Accept", accept)
    try:
        with _OPENER.open(req, timeout=TIMEOUT_SECONDS) as r:
            return read_limited(r, what)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError(f"{what} was not found on GitHub ({url}).")
        if e.code in (403, 429):
            raise UpdateError("GitHub is limiting how often this computer can check for "
                              "updates. Try again in an hour.")
        raise UpdateError(f"GitHub returned an error for {what}: HTTP {e.code}.")
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            raise UpdateError(
                "Could not verify GitHub's security certificate.\n"
                "On a Mac with Python from python.org, open Applications > Python 3.x and "
                "double-click 'Install Certificates.command', then try again.")
        raise UpdateError(f"Could not reach GitHub. Check your internet connection.\n({e.reason})")
    except (TimeoutError, OSError) as e:
        raise UpdateError(f"Could not reach GitHub: {e}")


def latest_release():
    """
    Return (version, tag, assets) for the latest published release, where
    assets maps each attached file name to its download URL.
    """
    if not is_configured():
        raise UpdateError("Updates are not set up yet: fill in GITHUB_OWNER and GITHUB_REPO "
                          "in updater.py.")
    try:
        raw = _fetch(_api_latest_url(), "The latest release",
                     accept="application/vnd.github+json")
    except UpdateError as e:
        if "was not found" in str(e):
            raise UpdateError("No releases have been published on GitHub yet.")
        raise
    try:
        data = json.loads(raw.decode("utf-8"))
        tag = data["tag_name"]
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    except (ValueError, KeyError, TypeError):
        raise UpdateError("GitHub sent release information this app could not read.")
    m = _TAG_RE.match(str(tag))
    if not m:
        raise UpdateError(f"The latest release tag ({tag!r}) is not a version number like "
                          "v1.3.0, so it was not installed.")
    return m.group(1), tag, assets


def parse_checksums(text):
    """Read a sha256sum-style file ('<hash>  <name>' per line) into {name: hash}."""
    sums = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _SUM_LINE_RE.match(line)
        if not m:
            raise UpdateError(f"{CHECKSUM_ASSET} on GitHub has a line this app could not read.")
        sums[m.group(2)] = m.group(1).lower()
    return sums


def _b64(text, size, what):
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except ValueError:
        raw = b""
    if len(raw) != size:
        raise UpdateError(f"{what} is not in the expected format, so nothing was changed.")
    return raw


def verify_signature(data, signature_text, tag, keys=None):
    """
    Raise UpdateError unless signature_text is a valid minisign signature of
    data, made by one of keys (TRUSTED_KEYS by default), whose trusted comment
    names this release tag.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        raise UpdateError("Checking the release signature needs the cryptography package. "
                          "Install it with:\npip install cryptography\nthen try again.")
    what = f"{SIGNATURE_ASSET} on GitHub"
    lines = [line.strip() for line in signature_text.strip().splitlines()]
    prefix = "trusted comment: "
    if len(lines) != 4 or not lines[0].startswith("untrusted comment:") \
            or not lines[2].startswith(prefix):
        raise UpdateError(f"{what} is not in the expected format, so nothing was changed.")
    blob = _b64(lines[1], 74, what)
    algorithm, key_id, signature = blob[:2], blob[2:10], blob[10:]
    comment = lines[2][len(prefix):]
    comment_signature = _b64(lines[3], 64, what)
    if algorithm not in (b"ED", b"Ed"):
        raise UpdateError(f"{what} uses a signature type this app does not accept.")

    public_key = None
    for key in TRUSTED_KEYS if keys is None else keys:
        raw = _b64(key, 42, "A trusted release key in updater.py")
        if raw[:2] == b"Ed" and raw[2:10] == key_id:
            public_key = Ed25519PublicKey.from_public_bytes(raw[10:])
    if public_key is None:
        raise UpdateError("This release was not signed by the app's release key, so nothing "
                          "was changed.")

    # minisign signs a BLAKE2b-512 hash of the file ("ED"), or the file itself
    # in its older format ("Ed"), then signs the signature plus the comment
    message = hashlib.blake2b(data, digest_size=64).digest() if algorithm == b"ED" else data
    try:
        public_key.verify(signature, message)
        public_key.verify(comment_signature, signature + comment.encode("utf-8"))
    except InvalidSignature:
        raise UpdateError("The release signature does not match, so nothing was changed. "
                          "The release may have been altered.")
    # Ties the signature to this release, so an old signature can't be reused
    if tag not in comment.split():
        raise UpdateError(f"The release signature is for a different release than {tag}, so "
                          "nothing was changed.")


def check(current_version):
    """
    Return the newest released version if it is newer than current_version,
    otherwise None.
    """
    latest, _, _ = latest_release()
    return latest if parse_version(latest) > parse_version(current_version) else None


def install(current_version):
    """
    Download and install the newest release. Returns the new version string.
    Nothing is written unless SHA256SUMS carries a valid signature from a
    trusted key, and every file downloads, matches SHA256SUMS, and is valid
    Python.
    """
    if installed_with_pip():
        raise UpdateError("This copy was installed with pip, so update it with:\n"
                          f"{pip_upgrade_command()}")
    latest, tag, assets = latest_release()
    if parse_version(latest) <= parse_version(current_version):
        raise UpdateError(f"You already have the newest version ({current_version}).")
    if CHECKSUM_ASSET not in assets:
        raise UpdateError(f"Version {latest} is still being prepared on GitHub (its "
                          f"{CHECKSUM_ASSET} file is not there yet), so nothing was changed. "
                          "Try again in a few minutes.")
    if SIGNATURE_ASSET not in assets:
        raise UpdateError(f"Version {latest} is still being prepared on GitHub (its "
                          f"{SIGNATURE_ASSET} signature is not there yet), so nothing was "
                          "changed. Try again later.")
    sums_data = _fetch(assets[CHECKSUM_ASSET], CHECKSUM_ASSET)
    try:
        signature_text = _fetch(assets[SIGNATURE_ASSET], SIGNATURE_ASSET).decode("utf-8")
    except UnicodeDecodeError:
        raise UpdateError(f"{SIGNATURE_ASSET} on GitHub is not a text file.")
    verify_signature(sums_data, signature_text, tag)
    try:
        sums = parse_checksums(sums_data.decode("utf-8"))
    except UnicodeDecodeError:
        raise UpdateError(f"{CHECKSUM_ASSET} on GitHub is not a text file.")

    files = {}
    for name in UPDATE_FILES:
        if name not in sums:
            raise UpdateError(f"{CHECKSUM_ASSET} for version {latest} has no entry for {name}, "
                              "so nothing was changed.")
        data = _fetch(_raw_url(tag, name), name)
        if hashlib.sha256(data).hexdigest() != sums[name]:
            raise UpdateError(f"The downloaded {name} does not match its checksum, so nothing "
                              "was changed. It may have been damaged or altered on the way. "
                              "Try again later.")
        try:
            source = data.decode("utf-8")
            compile(source, name, "exec")
        except UnicodeDecodeError:
            raise UpdateError(f"{name} on GitHub is not a text file.")
        except SyntaxError as e:
            raise UpdateError(f"The new {name} has an error (line {e.lineno}), so nothing "
                              "was changed.")
        except ValueError:  # Python 3.11 raises this for null bytes in source
            raise UpdateError(f"The new {name} is not valid Python, so nothing was changed.")
        files[name] = data

    file_version = _version_in(files["xyz_to_lla.py"].decode("utf-8"))
    if parse_version(file_version) != parse_version(latest):
        raise UpdateError(f"Release {tag} contains version {file_version} of the app, which "
                          "does not match its tag, so nothing was changed.")
    if not os.access(APP_DIR, os.W_OK):
        raise UpdateError(f"Cannot write to {APP_DIR}. Move the app to a folder you own "
                          "(such as Documents) and try again.")

    _swap_in(files)
    return latest


def _swap_in(files):
    """
    Install {name: bytes} into APP_DIR, keeping .bak copies of the old files.
    Every new file is written and every old one copied to .bak before any app
    file changes. Each file is then replaced in one step (os.replace), so it is
    never missing. If any step fails, the files already replaced are put back,
    so the app is never left half old and half new.
    """
    paths = {name: os.path.join(APP_DIR, name) for name in files}
    had_old = {name: os.path.exists(path) for name, path in paths.items()}
    replaced = []
    try:
        # Exact bytes, so they match the checksums
        for name, data in files.items():
            with open(paths[name] + ".new", "wb") as f:
                f.write(data)
        for name, path in paths.items():
            if had_old[name]:
                shutil.copy2(path, path + ".bak")
        for name, path in paths.items():
            os.replace(path + ".new", path)
            replaced.append(name)
    except OSError as e:
        rolled_back = True
        for name in replaced:
            path = paths[name]
            try:
                if had_old[name]:
                    shutil.copy2(path + ".bak", path)
                else:
                    os.remove(path)
            except OSError:
                rolled_back = False
        for path in paths.values():
            with contextlib.suppress(OSError):
                os.remove(path + ".new")
        kept = ("The previous version was kept." if rolled_back else
                f"Some files could not be put back. The old ones are the .bak files in {APP_DIR}.")
        raise UpdateError(f"Could not install the update: {e}\n{kept}")


def restart():
    """Start the app again with the new files."""
    if sys.platform.startswith("win"):
        import subprocess
        subprocess.Popen([sys.executable, *sys.argv])
        sys.exit(0)
    os.execv(sys.executable, [sys.executable, *sys.argv])
