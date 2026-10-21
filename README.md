# orbit-coordinate-converter
# Orbit & Coordinate Converter

A Python command-line tool that converts Earth-centered X/Y/Z positions and CCSDS OEM satellite orbit files into WGS84 latitude, longitude, and altitude.

It handles space-fixed and Earth-fixed reference frames, eight time systems, and files with millions of points without running out of memory.

## Features

- **Two input types:** plain CSV files of ECEF X, Y, Z (meters), or CCSDS OEM orbit files in the text (KVN) format (km)
- **Reference frame rotation:** converts space-fixed frames (EME2000/J2000, GCRF, ICRF, TEME) to Earth-fixed ITRS at each timestamp using astropy and IERS Earth orientation data
- **Time systems:** UTC, TAI, TT, TDB, TCG, TCB, UT1, and GPS
- **Fast mode:** about 8x faster on space-fixed frames, with differences under 0.05 mm
- **Scales to large files:** vectorized and processed in chunks, so memory use stays flat
- **Strict input validation:** clear error messages with line numbers for malformed or unsupported files
- **Reusable:** import `xyz_to_lla()` into your own Python code

## Installation

Requires Python 3.

```
git clone https://github.com/SBK008/orbit-coordinate-converter.git
cd orbit-coordinate-converter
pip install -r requirements.txt
```

`astropy` is only needed for OEM files in a space-fixed frame. CSV files and Earth-fixed OEM files work with just `pyproj`, `numpy`, and `pandas`.

## Quick start

Try it on the included sample files:

```
python xyz_to_lla.py examples/points.csv points_lla.csv
python xyz_to_lla.py examples/sample_leo_eme2000.oem leo_lla.csv
```

Compare your results to `examples/expected_output/`. See [examples/README.md](examples/README.md) for what each sample shows.

## Usage

```
python xyz_to_lla.py INPUT OUTPUT [options]
```

### CSV input

The CSV needs X, Y, Z columns in meters. The output keeps every original column and adds `lat`, `lon`, `alt`.

```
python xyz_to_lla.py points.csv out.csv
python xyz_to_lla.py points.csv out.csv --x X_m --y Y_m --z Z_m
```

### OEM input

Files ending in `.oem` are detected automatically. Use `--format oem` for other extensions.

```
python xyz_to_lla.py orbit.oem out.csv
python xyz_to_lla.py orbit.txt out.csv --format oem --fast
```

Output columns: `object, epoch, time_system, x_ecef_m, y_ecef_m, z_ecef_m, lat, lon, alt`

### Options

| Option | Default | Description |
|---|---|---|
| `--format auto\|csv\|oem` | `auto` | `auto` reads `.oem` files as OEM and everything else as CSV |
| `--x`, `--y`, `--z` | `x`, `y`, `z` | Column names for CSV input |
| `--chunksize N` | 1,000,000 (CSV), 200,000 (OEM) | Rows processed per batch |
| `--fast` | off | Interpolate precession-nutation for space-fixed frames |

### In your own code

```python
from xyz_to_lla import xyz_to_lla

lat, lon, alt = xyz_to_lla(6378137.0, 0.0, 0.0)   # 0.0, 0.0, 0.0
lat, lon, alt = xyz_to_lla(x_array, y_array, z_array)
```

## Supported OEM metadata

| Field | Supported values |
|---|---|
| `CENTER_NAME` | `EARTH` |
| `REF_FRAME` (Earth-fixed) | `ITRF*` (any ITRF realization), `EFG`, `ECEF` |
| `REF_FRAME` (space-fixed) | `EME2000`, `J2000`, `GCRF`, `ICRF`, `TEME` |
| `TIME_SYSTEM` | `UTC`, `TAI`, `TT`, `TDB`, `TCG`, `TCB`, `UT1`, `GPS` |
| Epochs | `2026-10-19T12:00:00.000` or day-of-year `2026-292T12:00:00.000` |

`COMMENT` lines and covariance blocks are skipped. XML OEM is not supported.

## How it works

**ECEF to latitude, longitude, altitude.** `pyproj` transforms from WGS84 geocentric coordinates (EPSG:4978) to WGS84 geographic 3D (EPSG:4979). This gives geodetic latitude and height above the ellipsoid, not a simple spherical approximation.

**Space-fixed to Earth-fixed.** Satellite positions are often given in a frame whose axes point at distant stars. To find what point on Earth a satellite is over, the tool rotates each position into a frame that spins with the Earth, at that position's exact time. The rotation combines:

1. **Frame bias:** a tiny fixed offset between J2000 and GCRF
2. **Precession-nutation:** the slow wobble of Earth's axis (IAU 2006/2000A model)
3. **Earth rotation:** the daily spin, from UT1
4. **Polar motion:** small drift of the pole, from IERS data

**Fast mode.** Precession-nutation changes slowly, so `--fast` computes it every 600 seconds and interpolates in between. It interpolates the underlying angles rather than the matrix values, so every result is still a proper rotation matrix. Earth rotation and polar motion are still computed exactly at every point. On a full low Earth orbit sample, fast mode matched the full calculation to within a few micrometers.

## Validation

The sample files include built-in checks:

- Known locations (such as UAH in Huntsville, AL, and Mount Everest) convert back to their correct coordinates.
- A 51.6° inclination orbit reaches a maximum latitude of 51.6°, confirming the frame rotation is correct.
- A malformed file produces a clear error and exits with code 1.

## Documentation

See [Coordinate_Converter_Guide.pdf](Coordinate_Converter_Guide.pdf) for a full user guide with troubleshooting.

## Built with

Python, NumPy, pandas, [pyproj](https://pyproj4.github.io/pyproj/), [astropy](https://www.astropy.org/)

## License

MIT
