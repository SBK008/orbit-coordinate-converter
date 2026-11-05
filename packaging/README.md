# Standalone apps

The standalone app has Python, the converter, and every library sealed
inside, so users download it, open it, and need nothing else installed.
It is built with [PyInstaller](https://pyinstaller.org).

## Status

| System | Status |
|---|---|
| macOS (Apple Silicon and Intel) | Built in CI, being tested |
| Windows | Planned |
| Linux | Planned |

## How the build works

`.github/workflows/build-apps.yml` runs on pull requests that change the code
or the packaging, and from the **Run workflow** button on the Actions tab.
For each Mac type it:

1. Installs the app and the tools in `packaging/requirements.txt`.
2. Builds `Coordinate Converter.app` from `coordinate_converter.spec`.
3. Gives it a free ad-hoc signature and checks the signature.
4. Puts it in a `.dmg` with a shortcut to Applications.
5. Opens the `.dmg` and runs the app's self-test from inside it.
6. Saves the `.dmg` on the run's **Summary** page under **Artifacts**
   (kept 14 days).

The self-test (`--self-test`) converts a CSV, an Earth-fixed OEM to NAIRAS,
and a space-fixed (EME2000) OEM, then opens and closes the window. If a
library or data file is missing from the app, this step fails.

## Testing a build on a Mac

1. Open the run on the **Actions** tab and download the `.dmg` for your Mac
   from **Artifacts** (`arm64` for M1 and newer, `x86_64` for Intel). It
   downloads as a `.zip`; double-click it to get the `.dmg`.
2. Double-click the `.dmg` and drag **Coordinate Converter** onto
   **Applications**.
3. Open it from Applications. macOS says it can't check the app for
   malicious software, because the app has no paid Apple signature.
   Click **Done**.
4. Open **System Settings > Privacy & Security**, scroll down, and click
   **Open Anyway** next to Coordinate Converter. Confirm with your password.
   This is only needed the first time.

## Building it yourself

On a Mac with Python 3.11 or newer from python.org:

```
python3 -m pip install . -r packaging/requirements.txt
pyinstaller --noconfirm packaging/coordinate_converter.spec
open "dist/Coordinate Converter.app"
```

## Updates

The standalone app can't replace its own files the way the zip install
does. When a new version is out, **Check for updates** offers to open the
download page instead.

## Known limits

- **Size:** about a 50 MB download (the `.dmg`) and 120 MB once installed, mostly astropy and pandas.
- **Space-fixed OEM frames** (EME2000, GCRF, ICRF) still download current
  Earth orientation data when online. Bundling it for offline use is
  [#14](https://github.com/SBK008/orbit-coordinate-converter/issues/14).
- **First-open warning on macOS**, since Apple's notarization needs a paid
  account. See [#15](https://github.com/SBK008/orbit-coordinate-converter/issues/15).
