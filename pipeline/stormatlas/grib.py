"""Read ECMWF open-data GRIB2 files (msl, 10u, 10v, swh) into a Scene, using eccodes."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np
from scipy.interpolate import RegularGridInterpolator

WANTED = {"msl", "10u", "10v", "swh"}


def _read_messages(path):
    from eccodes import (codes_grib_new_from_file, codes_get, codes_get_array,
                         codes_get_values, codes_release)
    with open(path, "rb") as f:
        while True:
            h = codes_grib_new_from_file(f)
            if h is None:
                break
            try:
                name = codes_get(h, "shortName")
                if name not in WANTED:
                    continue
                lats = np.asarray(codes_get_array(h, "distinctLatitudes"), float)
                lons = np.asarray(codes_get_array(h, "distinctLongitudes"), float)
                vals = np.asarray(codes_get_values(h), float).reshape(len(lats), len(lons))
                vd, vt = int(codes_get(h, "validityDate")), int(codes_get(h, "validityTime"))
                dd, dt = int(codes_get(h, "dataDate")), int(codes_get(h, "dataTime"))
                valid = datetime.strptime(f"{vd:08d}{vt:04d}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                run = datetime.strptime(f"{dd:08d}{dt:04d}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                yield name, valid, run, lats, lons, vals
            finally:
                codes_release(h)


def _crop(lats, lons, vals, bbox):
    lat_min, lat_max, lon_min, lon_max = bbox
    lons = np.where(lons > 180, lons - 360, lons)
    o = np.argsort(lons)
    lons, vals = lons[o], vals[:, o]
    if lats[0] < lats[-1]:  # make descending
        lats, vals = lats[::-1], vals[::-1]
    ym = (lats >= lat_min) & (lats <= lat_max)
    xm = (lons >= lon_min) & (lons <= lon_max)
    return lats[ym], lons[xm], vals[np.ix_(ym, xm)]


def read_scene(paths, bbox=(20, 75, -80, 40), model="ECMWF IFS 0.25°"):
    from .scene import Scene
    data = defaultdict(dict)
    runs, grid = [], None
    for path in paths:
        for name, valid, run, lats, lons, vals in _read_messages(path):
            la, lo, v = _crop(lats, lons, vals, bbox)
            if name == "msl":
                grid = grid or (la, lo)
            data[name][valid] = (la, lo, v)
            runs.append(run)
    if grid is None or not data["msl"]:
        raise ValueError("no msl messages found in the supplied GRIB files")
    lats, lons = grid
    times = sorted(data["msl"])

    def stack(name, fn=lambda x: x):
        if name not in data:
            return None
        out = np.full((len(times), len(lats), len(lons)), np.nan)
        for k, t in enumerate(times):
            if t not in data[name]:
                continue
            la, lo, v = data[name][t]
            v = fn(v)
            if la.shape != lats.shape or lo.shape != lons.shape or not (np.allclose(la, lats) and np.allclose(lo, lons)):
                f = RegularGridInterpolator((la[::-1], lo), v[::-1], bounds_error=False, fill_value=np.nan)
                LA, LO = np.meshgrid(lats, lons, indexing="ij")
                v = f(np.stack([LA.ravel(), LO.ravel()], -1)).reshape(LA.shape)
            out[k] = v
        return out

    msl = stack("msl", lambda v: v / 100.0)
    swh = stack("swh")
    u, vv = stack("10u"), stack("10v")
    wind = np.hypot(u, vv) if u is not None and vv is not None else None
    return Scene(lats, lons, times, msl, wind, swh, min(runs), model, False)
