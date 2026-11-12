"""Download the latest ECMWF open-data forecast (CC-BY-4.0) with the ecmwf-opendata client."""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone


def latest_cycle(now=None, lag_h=8):
    now = now or datetime.now(timezone.utc)
    t = now - timedelta(hours=lag_h)
    return t.replace(hour=12 if t.hour >= 12 else 0, minute=0, second=0, microsecond=0)


def steps_for(max_hours):
    s = list(range(0, min(max_hours, 144) + 1, 3))
    s += list(range(150, max_hours + 1, 6))
    return s


def fetch(dest_dir, *, model="ifs", source="ecmwf", max_hours=144, waves=True, cycle=None):
    """Returns (list_of_grib_paths, run_datetime). Tries the latest 00/12z cycle, then the previous."""
    from ecmwf.opendata import Client  # package "ecmwf-opendata" installs as ecmwf.opendata
    os.makedirs(dest_dir, exist_ok=True)
    cycle = cycle or latest_cycle()
    last_err = None
    for attempt in range(2):
        run = cycle - timedelta(hours=12 * attempt)
        client = Client(source=source, model=model, resol="0p25")
        common = dict(date=run.strftime("%Y%m%d"), time=run.hour, step=steps_for(max_hours), type="fc")
        atm = os.path.join(dest_dir, f"atm_{run:%Y%m%d%H}.grib2")
        try:
            client.retrieve(param=["msl", "10u", "10v"], target=atm, **common)
        except Exception as e:  # cycle not published yet -> try the previous one
            last_err = e
            continue
        paths = [atm]
        if waves and model == "ifs":
            wav = os.path.join(dest_dir, f"wave_{run:%Y%m%d%H}.grib2")
            try:
                client.retrieve(stream="wave", param=["swh"], target=wav, **common)
                paths.append(wav)
            except Exception as e:
                print(f"warning: wave data unavailable ({e}); continuing without waves")
        return paths, run
    raise RuntimeError(f"could not download an ECMWF cycle: {last_err}")
