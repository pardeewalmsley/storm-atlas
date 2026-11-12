"""Scene -> list of storm dicts (the JSON schema the web app consumes)."""
from __future__ import annotations
import json
import numpy as np
from .detect import find_lows
from .track import link, filter_tracks, compute_deepening, local_max
from .scene import Scene, haversine_km

BOMB_THRESHOLD = 24.0  # hPa fall in 24 h, scaled to 60N (1 Bergeron)


def analyse(scene: Scene, *, detect_kw=None, filter_kw=None, link_kw=None, names=None) -> list[dict]:
    frames = []
    for k, t in enumerate(scene.times):
        frames.append((t, find_lows(scene.lats, scene.lons, scene.msl[k], **(detect_kw or {}))))
    tracks = filter_tracks(link(frames, **(link_kw or {})), **(filter_kw or {}))
    tidx = {t: k for k, t in enumerate(scene.times)}
    storms = []
    for pts in tracks:
        for p in pts:
            k = tidx[p.t]
            if scene.wind is not None:
                p.wind = local_max(scene.wind[k], scene.lats, scene.lons, p.lat, p.lon)
            if scene.swh is not None:
                p.swh = local_max(scene.swh[k], scene.lats, scene.lons, p.lat, p.lon)
        best = compute_deepening(pts)
        winds = [p.wind for p in pts if p.wind is not None]
        waves = [p.swh for p in pts if p.swh is not None]
        low = min(pts, key=lambda q: q.p)
        storms.append(dict(
            start=pts[0].t, end=pts[-1].t, min_p=low.p, min_p_time=low.t,
            max_wind_ms=max(winds) if winds else None,
            max_wind_kmh=round(max(winds) * 3.6) if winds else None,
            max_swh=max(waves) if waves else None,
            max_deepening=best,
            bomb=bool(best is not None and best >= BOMB_THRESHOLD),
            pts=pts,
        ))
    storms.sort(key=lambda s: s["start"])
    for i, s in enumerate(storms):
        s["id"] = f"L{i + 1:02d}"
        s["name"] = None
    if names:
        apply_names(storms, names)
    return storms


def apply_names(storms, names, max_km=500.0, max_h=12.0):
    """names: [{name, lat, lon, time(ISO)}] anchors; attach to the nearest track point."""
    from datetime import datetime
    for n in names:
        t = datetime.fromisoformat(n["time"].replace("Z", "+00:00"))
        best, bd = None, None
        for s in storms:
            for p in s["pts"]:
                if abs((p.t - t).total_seconds()) / 3600.0 > max_h:
                    continue
                d = float(haversine_km(p.lat, p.lon, n["lat"], n["lon"]))
                if d <= max_km and (bd is None or d < bd):
                    best, bd = s, d
        if best is not None:
            best["name"] = n["name"]


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def storm_to_json(s: dict) -> dict:
    r = lambda v, n=1: None if v is None else round(float(v), n)
    return dict(
        id=s["id"], name=s["name"], start=iso(s["start"]), end=iso(s["end"]),
        min_p=r(s["min_p"]), min_p_time=iso(s["min_p_time"]),
        max_wind_kmh=s["max_wind_kmh"], max_swh=r(s["max_swh"]),
        max_deepening=r(s["max_deepening"], 2), bomb=s["bomb"],
        points=[dict(t=iso(p.t), lat=r(p.lat, 2), lon=r(p.lon, 2), p=r(p.p), wind=r(p.wind),
                     swh=r(p.swh), deep24=r(p.deep24, 2)) for p in s["pts"]],
    )
