# Example inputs

Small files you can run right away to see the converter work. Run these from the repo's main folder.

| File | What it shows |
|---|---|
| `points.csv` | Plain CSV of ECEF X, Y, Z in meters for 6 known places (equator, North Pole, UAH, Everest, Sydney, a point at ISS altitude). |
| `sample_leo_eme2000.oem` | One full orbit (94 points, every 60 s) of a synthetic ISS-like satellite: 420 km, 51.6 degree inclination, space-fixed EME2000 frame. |
| `sample_multi_segment.oem` | Two segments in one file: ITRF2020 with UTC, then GCRF with GPS time. Also includes a covariance block that gets skipped. |
| `bad_example.oem` | Broken on purpose (unsupported frame) to show the error message. |

All orbit data is synthetic, not a real satellite.

## Try it

```
pip install -r requirements.txt

python xyz_to_lla.py examples/points.csv points_lla.csv
python xyz_to_lla.py examples/sample_leo_eme2000.oem leo_lla.csv
python xyz_to_lla.py examples/sample_leo_eme2000.oem leo_lla.csv --fast
python xyz_to_lla.py examples/sample_multi_segment.oem multi_lla.csv
python xyz_to_lla.py examples/bad_example.oem bad.csv
```

Compare your results to the files in `expected_output/`.

## What to check

- **points.csv:** each place comes back at the latitude, longitude, and altitude you'd expect. UAH comes out at 34.7254, -86.6406, 200 m.
- **sample_leo_eme2000.oem:** latitude swings between about -51.6 and +51.6 degrees. That matches the orbit's 51.6 degree inclination, which is a quick sanity check that the frame rotation is right.
- **--fast:** results differ from the normal run by a few micrometers.
- **bad_example.oem:** prints `REF_FRAME = MOON_ME, which is not supported` and exits with code 1.
