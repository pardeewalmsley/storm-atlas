"""Link per-timestep lows into tracks and compute storm metrics."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from .scene import haversine_km


@dataclass
class Point:
    t: object
    lat: float
    lon: float
    p: float
    depth: float = 0.0
    wind: float | None = None   # m/s, max within radius
    swh: float | None = None    # m, max within radius
    deep24: float | None = None  # Bergeron-scaled hPa/24h (positive = deepening)


@dataclass
class Track:
    pts: list = field(default_factory=list)
    missed: int = 0


def link(frames, *, max_speed_kmh=100.0, floor_km=300.0, max_gap=1):
    """frames: list of (time, [low dicts]). Greedy nearest-neighbour linking with
    constant-velocity prediction. Returns list of list[Point]."""
    active: list[Track] = []
    done: list[Track] = []
    for t, lows in frames:
        pairs = []
        for ti, tr in enumerate(active):
            last = tr.pts[-1]
            dt = (t - last.t).total_seconds() / 3600.0
            gate = max(floor_km, max_speed_kmh * dt)
            plat, plon = last.lat, last.lon
            if len(tr.pts) >= 2:
                prev = tr.pts[-2]
                dtp = (last.t - prev.t).total_seconds() / 3600.0
                plat += (last.lat - prev.lat) / dtp * dt
                plon += (last.lon - prev.lon) / dtp * dt
            for ci, c in enumerate(lows):
                if haversine_km(last.lat, last.lon, c["lat"], c["lon"]) > gate:
                    continue
                cost = float(haversine_km(plat, plon, c["lat"], c["lon"]))
                if cost <= gate:
                    pairs.append((cost, ti, ci))
        pairs.sort()
        used_t, used_c = set(), set()
        for cost, ti, ci in pairs:
            if ti in used_t or ci in used_c:
                continue
            used_t.add(ti)
            used_c.add(ci)
            c = lows[ci]
            active[ti].pts.append(Point(t, c["lat"], c["lon"], c["p"], c["depth"]))
            active[ti].missed = 0
        still = []
        for ti, tr in enumerate(active):
            if ti not in used_t:
                tr.missed += 1
                if tr.missed > max_gap:
                    done.append(tr)
                    continue
            still.append(tr)
        active = still
        for ci, c in enumerate(lows):
            if ci not in used_c:
                active.append(Track([Point(t, c["lat"], c["lon"], c["p"], c["depth"])]))
    done.extend(active)
    return [tr.pts for tr in done]


def filter_tracks(tracks, *, min_points=4, min_duration_h=12.0, min_travel_km=400.0, max_min_p=1008.0):
    """Drop noise and semi-permanent features (e.g. the Icelandic Low)."""
    keep = []
    for pts in tracks:
        if len(pts) < min_points:
            continue
        dur = (pts[-1].t - pts[0].t).total_seconds() / 3600.0
        if dur < min_duration_h:
            continue
        if min(p.p for p in pts) > max_min_p:
            continue
        travel = float(haversine_km(pts[0].lat, pts[0].lon, pts[-1].lat, pts[-1].lon))
        if travel < min_travel_km:
            continue
        keep.append(pts)
    return keep


def compute_deepening(pts):
    """Sanders-Gyakum style: 24 h central-pressure fall scaled by sin(lat)/sin(60N).
    >= 1.0 Bergeron is the classic 'bomb' threshold. Stores Point.deep24."""
    th = np.array([(p.t - pts[0].t).total_seconds() / 3600.0 for p in pts])
    pp = np.array([p.p for p in pts])
    for i, p in enumerate(pts):
        if th[i] - 24.0 < th[0] - 1e-6:
            continue
        p0 = float(np.interp(th[i] - 24.0, th, pp))
        lat = 0.5 * (p.lat + float(np.interp(th[i] - 24.0, th, [q.lat for q in pts])))
        scale = np.sin(np.radians(60.0)) / np.sin(np.radians(max(lat, 20.0)))
        p.deep24 = float((p0 - p.p) * scale)  # hPa fallen in 24 h, Bergeron-scaled
    vals = [p.deep24 for p in pts if p.deep24 is not None]
    return max(vals) if vals else None


def local_max(field, lats, lons, lat0, lon0, radius_km=500.0):
    dlat = float(lats[0] - lats[1])
    dlon = float(lons[1] - lons[0])
    dy = int(radius_km / 111.0 / dlat) + 2
    dx = int(radius_km / (111.0 * max(np.cos(np.radians(lat0)), 0.2)) / dlon) + 2
    iy = int(round((lats[0] - lat0) / dlat))
    ix = int(round((lon0 - lons[0]) / dlon))
    y0, y1 = max(iy - dy, 0), min(iy + dy + 1, len(lats))
    x0, x1 = max(ix - dx, 0), min(ix + dx + 1, len(lons))
    if y0 >= y1 or x0 >= x1:
        return None
    LON, LAT = np.meshgrid(lons[x0:x1], lats[y0:y1])
    d = haversine_km(lat0, lon0, LAT, LON)
    sub = np.where(d <= radius_km, field[y0:y1, x0:x1], -np.inf)
    v = sub.max()
    return None if not np.isfinite(v) else float(v)
