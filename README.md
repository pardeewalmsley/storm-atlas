# Storm Atlas: North Atlantic winter storm tracker

A zoom.earth-style map for **extratropical** North Atlantic storms, built on free
[ECMWF open data](https://www.ecmwf.int/en/forecasts/datasets/open-data) (IFS or AIFS, 0.25°, CC BY 4.0).

* **pipeline/** (Python): downloads the latest 00z/12z forecast, finds closed pressure minima at every step,
  links them into tracks, measures peak wind/waves and 24 h deepening (explosive "bomb" flag, ≥24 hPa/24 h scaled to 60°N),
  and writes `web/data/manifest.json` plus three small binary grids (MSLP, 10 m wind, wave height).
* **web/** (Leaflet, no build step): isobars with labels, wind or wave raster, L markers, forecast tracks, time slider
  (play, ←/→, space), storm panel with an **Episode data** block (name, dates, max wind, min pressure, ready for a title card),
  units switch, base maps (offline land / light / NASA GIBS satellite), URL-shareable state.

> **Important.** Tracks are *model-derived*: automatically detected pressure minima in forecast data. They are **not**
> official analyses. For published positions and pressures use NOAA OPC, Met Office or DWD charts.
> The bundled demo (`web/data`) is **synthetic** (invented storms) and shows a banner saying so.

## Quick start

```bash
pip install -e "pipeline[dev]"
cd pipeline
python -m stormatlas demo --out ../web/data          # synthetic data, works offline
# or real data:
python -m stormatlas fetch --stride 2 --out ../web/data      # --source aws|azure|google if ecmwf is busy
python -m stormatlas fetch --model aifs-single --out ../web/data   # AI model (no wave data)

cd ../web && python -m http.server 8000                # open http://localhost:8000
```
`--stride 2` thins the exported grid to 0.5° (about 2.6 MB per field for 49 steps); detection always runs at full resolution.

Local GRIB2 files: `python -m stormatlas process file1.grib2 file2.grib2 --out ../web/data`.

## Naming storms
The tracker numbers lows L01, L02… per run (numbers change between runs). To attach official names
(Met Office / DWD / KNMI names), copy `names.example.json` to `names.json` and list an anchor point per storm
(approximate position and time); it is attached to the nearest track within 500 km / 12 h. Pass `--names names.json`.
You can also type a name into the panel; it updates the episode block.

## Automatic updates and hosting (free)
`.github/workflows/update.yml` runs twice a day, tests, fetches the new forecast and publishes `web/` to GitHub Pages.
Enable *Settings → Pages → Source: GitHub Actions*.

## Tests
```bash
cd pipeline && pytest -q                 # tracker, GRIB reader, exporter (14 tests)
npm i playwright && node tests/e2e/smoke.js    # headless-browser smoke test of the UI
```

## How detection works
1. Smooth MSLP lightly; take local minima within ±2°; keep those < 1015 hPa and north of 25°N.
2. Require a *closed* low: all 8 points on a 3.5° ring higher than the centre, mean ≥ 2 hPa higher.
3. Sub-grid centre by parabolic fit; central pressure from the raw grid.
4. Link frame to frame (nearest to constant-velocity prediction, gate ≥ 300 km or 100 km/h, bridges one missed step).
5. Drop tracks shorter than 12 h / 4 points / 400 km travel or never below 1008 hPa. This removes semi-permanent features such as the Icelandic Low.

Limits: one forecast run = at most 6 days of track, no observed history (a later improvement is stitching successive analyses);
no fronts; highs are not marked; intensity of small, fast cyclones is smoothed at 0.25°; the tracker does not split/merge systems;
the first-time ECMWF download and wave-stream request could not be tested from the build sandbox (no network access),
so run `fetch` once and report any error (the GRIB reader itself is tested on generated GRIB2 files).

## Data credits
Contains ECMWF open data (CC BY 4.0). Optional satellite base map: NASA EOSDIS GIBS. Land outlines: Natural Earth via world-atlas.
Leaflet (BSD-2) and topojson-client (ISC) are vendored in `web/vendor`.
