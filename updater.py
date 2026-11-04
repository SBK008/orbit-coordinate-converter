"""
Update the app in place from its GitHub repository, without downloading the
whole zip again. Only the few .py files in UPDATE_FILES are fetched.

How it works:
    1. Read __version__ from xyz_to_lla.py on GitHub and compare it to the
       version running now.
    2. If GitHub has a newer one, download every file in UPDATE_FILES into
       memory and check that each one is valid Python.
    3. Only then write them next to the running copy, keeping the old ones as
       .bak files, so a failed download never leaves a half-updated app.

To publish an update: push your changed files to GitHub and raise __version__
in xyz_to_lla.py. Users who click "Check for updates" get the new files.

If the app was installed with pip, the files live in Python's own folder and
are not overwritten here. pip_upgrade_command() gives the command to run.
"""

import os
import re
import ssl
import sys
import urllib.error
import urllib.request

# ---- Fill these in with your GitHub details ---------------------------------
GITHUB_OWNER = "YOUR_GITHUB_USERNAME"
GITHUB_REPO = "YOUR_REPO_NAME"
GITHUB_BRANCH = "main"
# -----------------------------------------------------------------------------

# Files the updater replaces. The list in the NEW updater.py is used from the
# next update on, so a file you add later is picked up one update after that.
UPDATE_FILES = ["xyz_to_lla.py", "converter_gui.py", "updater.py"]

TIMEOUT_SECONDS = 15
APP_DIR = os.path.dirname(os.path.abspath(__file__))

_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


class UpdateError(Exception):
    """A problem checking for or installing an update. The message is shown to the user."""


def is_configured():
    return "YOUR_" not in GITHUB_OWNER + GITHUB_REPO


def repo_url():
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"


def pip_upgrade_command():
    return f"pip install --upgrade git+{repo_url()}.git"


def _raw_base():
    # The environment variable is only for testing against a local server
    return os.environ.get("COORD_CONVERTER_UPDATE_URL") or \
        f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"


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
        raise UpdateError("Could not find __version__ in xyz_to_lla.py on GitHub.")
    return m.group(1)


def _download(name):
    url = f"{_raw_base()}/{name}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError(f"{name} was not found on GitHub ({url}). Check GITHUB_OWNER, "
                              "GITHUB_REPO and GITHUB_BRANCH in updater.py, and that the repo "
                              "is public.")
        raise UpdateError(f"GitHub returned an error for {name}: HTTP {e.code}.")
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            raise UpdateError(
                "Could not verify GitHub's security certificate.\n"
                "On a Mac with Python from python.org, open Applications > Python 3.x and "
                "double-click 'Install Certificates.command', then try again.")
        raise UpdateError(f"Could not reach GitHub. Check your internet connection.\n({e.reason})")
    except (TimeoutError, OSError) as e:
        raise UpdateError(f"Could not reach GitHub: {e}")
    except UnicodeDecodeError:
        raise UpdateError(f"{name} on GitHub is not a text file.")


def check(current_version):
    """
    Return the newest version on GitHub if it is newer than current_version,
    otherwise None.
    """
    if not is_configured():
        raise UpdateError("Updates are not set up yet: fill in GITHUB_OWNER and GITHUB_REPO "
                          "in updater.py.")
    latest = _version_in(_download("xyz_to_lla.py"))
    return latest if parse_version(latest) > parse_version(current_version) else None


def install(current_version):
    """
    Download and install the newest version. Returns the new version string.
    Nothing is written unless every file downloads and is valid Python.
    """
    if installed_with_pip():
        raise UpdateError("This copy was installed with pip, so update it with:\n"
                          f"{pip_upgrade_command()}")
    files = {name: _download(name) for name in UPDATE_FILES}
    latest = _version_in(files["xyz_to_lla.py"])
    if parse_version(latest) <= parse_version(current_version):
        raise UpdateError(f"You already have the newest version ({current_version}).")
    for name, source in files.items():
        try:
            compile(source, name, "exec")
        except SyntaxError as e:
            raise UpdateError(f"The new {name} on GitHub has an error (line {e.lineno}), so "
                              "nothing was changed. Try again after the repo is fixed.")
    if not os.access(APP_DIR, os.W_OK):
        raise UpdateError(f"Cannot write to {APP_DIR}. Move the app to a folder you own "
                          "(such as Documents) and try again.")

    # Write every new file first, then swap them all in, keeping .bak copies
    for name, source in files.items():
        with open(os.path.join(APP_DIR, name + ".new"), "w", encoding="utf-8", newline="\n") as f:
            f.write(source)
    for name in files:
        path = os.path.join(APP_DIR, name)
        if os.path.exists(path):
            os.replace(path, path + ".bak")
        os.replace(path + ".new", path)
    return latest


def restart():
    """Start the app again with the new files."""
    if sys.platform.startswith("win"):
        import subprocess
        subprocess.Popen([sys.executable, *sys.argv])
        sys.exit(0)
    os.execv(sys.executable, [sys.executable, *sys.argv])
