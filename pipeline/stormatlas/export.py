"""Write manifest.json + binary grids for the web app."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
import numpy as np
from .scene import Scene
from .analyse import storm_to_json, iso

FIELDS = {  # name: (offset, scale)  value = offset + raw*scale ; 65535 = missing
    "msl": (850.0, 0.05),
    "wind": (0.0, 0.01),
    "swh": (0.0, 0.005),
}
MISSING = 65535


def encode(a: np.ndarray, offset: float, scale: float) -> np.ndarray:
    raw = np.round((a - offset) / scale)
    raw = np.where(np.isfinite(a), np.clip(raw, 0, MISSING - 1), MISSING)
    return raw.astype("<u2")


def decode(raw: np.ndarray, offset: float, scale: float) -> np.ndarray:
    v = offset + raw.astype(np.float64) * scale
    return np.where(raw == MISSING, np.nan, v)


def write_web_data(scene: Scene, storms: list[dict], out_dir: str, stride: int = 1, source: str = ""):
    os.makedirs(out_dir, exist_ok=True)
    lats, lons = scene.lats[::stride], scene.lons[::stride]
    files = {}
    for name in FIELDS:
        arr = getattr(scene, name if name != "msl" else "msl")
        if arr is None:
            continue
        off, sc = FIELDS[name]
        raw = encode(arr[:, ::stride, ::stride], off, sc)
        fn = f"{name}.bin"
        raw.tofile(os.path.join(out_dir, fn))
        files[name] = dict(file=fn, offset=off, scale=sc, missing=MISSING)
    manifest = dict(
        schema=1,
        model=scene.model,
        synthetic=scene.synthetic,
        source=source,
        run=iso(scene.run) if scene.run else None,
        generated=iso(datetime.now(timezone.utc)),
        grid=dict(lat0=float(lats[0]), lon0=float(lons[0]), dlat=float(lats[0] - lats[1]),
                  dlon=float(lons[1] - lons[0]), ny=len(lats), nx=len(lons)),
        times=[iso(t) for t in scene.times],
        fields=files,
        storms=[storm_to_json(s) for s in storms],
    )
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, separators=(",", ":"))
    return manifest
