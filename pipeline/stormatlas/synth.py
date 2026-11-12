"""Synthetic North Atlantic scene with known storms, used for demo + tests.

The storms are invented. They exist so the tracker and the web app can be exercised
without network access. Never present this data as a real forecast.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import numpy as np
from scipy import ndimage as ndi
from .scene import Scene

# waypoints: (hour, lon, lat). depth in hPa (peak deficit), width_h = gaussian time width.
DEFAULT_STORMS = [
    # explosive deepener: ~30 hPa in 24 h around hour 48-72, rapid track toward Iceland
    dict(name="S1-bomb", waypoints=[(-6, -72, 36), (24, -52, 43), (48, -34, 52), (72, -18, 59), (110, 2, 65), (144, 14, 68)],
         depth=48, t_peak=60, width_h=24, radius_km=600),
    # ordinary storm on a mid-Atlantic track, starts later
    dict(name="S2", waypoints=[(30, -70, 42), (70, -45, 47), (110, -20, 53), (144, 0, 57)],
         depth=24, t_peak=90, width_h=50, radius_km=550),
    # southern, slow-deepening system crossing toward Iberia/France
    dict(name="S3", waypoints=[(0, -28, 38), (40, -12, 44), (80, 6, 50), (110, 20, 54)],
         depth=22, t_peak=50, width_h=45, radius_km=500),
    # northern low that ends up merging into the Icelandic low
    dict(name="S4", waypoints=[(20, -60, 56), (60, -45, 61), (100, -30, 66)],
         depth=20, t_peak=70, width_h=40, radius_km=500),
]


def _background(LAT, LON):
    azores = 8.0 * np.exp(-(((LAT - 33) / 10) ** 2 + ((LON + 30) / 25) ** 2))
    iceland = -12.0 * np.exp(-(((LAT - 66) / 9) ** 2 + ((LON + 20) / 30) ** 2))
    return 1018.0 + azores + iceland


def make_scene(seed: int = 7, run: datetime | None = None, nsteps: int = 49, step_h: int = 3,
               res: float = 0.5, bbox=(20, 75, -80, 40), storms=None, noise: float = 0.7) -> Scene:
    storms = DEFAULT_STORMS if storms is None else storms
    run = run or datetime(2026, 11, 12, 0, tzinfo=timezone.utc)
    lat_min, lat_max, lon_min, lon_max = bbox
    lats = np.arange(lat_max, lat_min - res / 2, -res)
    lons = np.arange(lon_min, lon_max + res / 2, res)
    LON, LAT = np.meshgrid(lons, lats)
    rng = np.random.default_rng(seed)
    nz = ndi.gaussian_filter(rng.standard_normal(LAT.shape), 6)
    nz = nz / nz.std() * noise
    base = _background(LAT, LON) + nz
    times, msl, truth = [], [], []
    for k in range(nsteps):
        h = k * step_h
        p = base.copy()
        pos = []
        for s in storms:
            wp = np.array(s["waypoints"], float)
            if h < wp[0, 0] or h > wp[-1, 0]:
                continue
            lon0 = np.interp(h, wp[:, 0], wp[:, 1])
            lat0 = np.interp(h, wp[:, 0], wp[:, 2])
            x = (h - s["t_peak"]) / s["width_h"]
            deficit = s["depth"] * np.exp(-x * x)
            dx = (LON - lon0) * 111.0 * np.cos(np.radians(LAT))
            dy = (LAT - lat0) * 111.0
            p -= deficit * np.exp(-(dx * dx + dy * dy) / s["radius_km"] ** 2)
            pos.append(dict(name=s["name"], lat=lat0, lon=lon0))
        times.append(run + timedelta(hours=h))
        msl.append(p)
        truth.append(pos)
    msl = np.array(msl)
    wind = np.array([_wind(p, lats, lons) for p in msl])
    swh = np.array([ndi.gaussian_filter(np.clip(0.02 * w ** 2, 0, 14), 3) for w in wind])
    return Scene(lats, lons, times, msl, wind, swh, run, "SYNTHETIC DEMO", True, truth)


def _wind(p_hpa, lats, lons):
    """Crude surface wind from the pressure gradient (geostrophic * 0.6)."""
    dlat = lats[0] - lats[1]
    dlon = lons[1] - lons[0]
    LAT = lats[:, None]
    dp_dy = np.gradient(p_hpa, -dlat, axis=0) / 111.0                       # hPa/km northward
    dp_dx = np.gradient(p_hpa, dlon, axis=1) / (111.0 * np.cos(np.radians(LAT)))
    grad = np.hypot(dp_dx, dp_dy) * 0.1                                     # Pa/m
    f = 1.4584e-4 * np.sin(np.radians(np.maximum(LAT, 25)))
    return np.clip(0.6 * grad / (1.25 * f), 0, 60)
