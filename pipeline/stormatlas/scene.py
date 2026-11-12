from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np


@dataclass
class Scene:
    """Gridded forecast: lats descending, lons ascending, fields shaped (T, Y, X)."""
    lats: np.ndarray
    lons: np.ndarray
    times: list            # tz-aware UTC datetimes (valid times)
    msl: np.ndarray        # hPa
    wind: np.ndarray | None = None   # 10 m wind speed, m/s
    swh: np.ndarray | None = None    # significant wave height, m
    run: datetime | None = None
    model: str = "unknown"
    synthetic: bool = False
    truth: list = field(default_factory=list)  # synthetic ground truth (for tests)

    @property
    def dlat(self) -> float:
        return float(self.lats[0] - self.lats[1])

    @property
    def dlon(self) -> float:
        return float(self.lons[1] - self.lons[0])

    def hours(self) -> np.ndarray:
        t0 = self.times[0]
        return np.array([(t - t0).total_seconds() / 3600.0 for t in self.times])


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))
