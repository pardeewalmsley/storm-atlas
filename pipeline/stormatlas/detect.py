"""Detect closed pressure minima (cyclone centres) in one MSLP field."""
from __future__ import annotations
import numpy as np
from scipy import ndimage as ndi


def find_lows(lats, lons, msl, *, min_lat=25.0, max_p=1015.0, radius_deg=2.0, ring_deg=3.5,
              min_depth=2.0, smooth_cells=1.0):
    """Return list of dict(lat, lon, p, depth).

    A candidate is a local minimum of the lightly smoothed field within +-radius_deg that is
    below max_p, north of min_lat, and "closed": the mean MSLP on a ring ring_deg away must
    exceed the centre by min_depth hPa and every ring point must be higher than the centre.
    """
    dlat = float(lats[0] - lats[1])
    dlon = float(lons[1] - lons[0])
    sm = ndi.gaussian_filter(msl, smooth_cells, mode="nearest")
    rlat = max(1, int(round(radius_deg / dlat)))
    rlon = max(1, int(round(radius_deg * 1.5 / dlon)))
    mn = ndi.minimum_filter(sm, size=(2 * rlat + 1, 2 * rlon + 1), mode="nearest")
    cand = (sm <= mn) & (sm < max_p) & (lats[:, None] >= min_lat)
    lab, n = ndi.label(cand)
    out = []
    ny, nx = sm.shape
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        ys, xs = np.nonzero(lab[sl] == i)
        j = len(ys) // 2
        y, x = ys[j] + sl[0].start, xs[j] + sl[1].start
        if y < 1 or x < 1 or y > ny - 2 or x > nx - 2:
            continue
        oy = _parab(sm[y - 1, x], sm[y, x], sm[y + 1, x])
        ox = _parab(sm[y, x - 1], sm[y, x], sm[y, x + 1])
        lat = float(lats[0] - (y + oy) * dlat)
        lon = float(lons[0] + (x + ox) * dlon)
        ring = _ring(sm, lats, lons, lat, lon, ring_deg)
        if ring is None:
            continue
        centre = float(sm[y, x])
        if ring.min() - centre < 0.0 or ring.mean() - centre < min_depth:
            continue
        p = float(msl[max(y - 1, 0):y + 2, max(x - 1, 0):x + 2].min())
        out.append(dict(lat=lat, lon=lon, p=p, depth=float(ring.mean() - centre)))
    return out


def _parab(a, b, c):
    d = a - 2 * b + c
    if d <= 1e-9:
        return 0.0
    return float(np.clip(0.5 * (a - c) / d, -0.5, 0.5))


def _ring(sm, lats, lons, lat, lon, ring_deg):
    dlat = float(lats[0] - lats[1])
    dlon = float(lons[1] - lons[0])
    b = np.radians(np.arange(0, 360, 45))
    rl = lat + ring_deg * np.cos(b)
    ro = lon + ring_deg * np.sin(b) / max(np.cos(np.radians(lat)), 0.2)
    iy = (lats[0] - rl) / dlat
    ix = (ro - lons[0]) / dlon
    if iy.min() < 0 or ix.min() < 0 or iy.max() > sm.shape[0] - 1 or ix.max() > sm.shape[1] - 1:
        return None
    return ndi.map_coordinates(sm, [iy, ix], order=1)
