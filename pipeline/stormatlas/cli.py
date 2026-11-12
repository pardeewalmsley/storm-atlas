from __future__ import annotations
import argparse, json, os, sys
from .analyse import analyse
from .export import write_web_data


def _names(path):
    return json.load(open(path)) if path and os.path.exists(path) else None


def _finish(scene, args, source):
    storms = analyse(scene, names=_names(args.names))
    m = write_web_data(scene, storms, args.out, stride=args.stride, source=source)
    print(f"wrote {args.out}: {len(m['times'])} steps, {len(storms)} storms "
          f"({sum(s['bomb'] for s in storms)} bomb)")
    for s in storms:
        print(f"  {s['id']} {s['start']:%d %b %H}Z-{s['end']:%d %b %H}Z  min {s['min_p']:.0f} hPa  "
              f"wind {s['max_wind_kmh']} km/h  bomb={s['bomb']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stormatlas")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--out", default="../web/data")
        p.add_argument("--stride", type=int, default=1, help="decimate exported grids (2 turns 0.25 deg into 0.5)")
        p.add_argument("--names", default=None, help="optional names.json with naming anchors")

    d = sub.add_parser("demo", help="synthetic storms, no network needed")
    common(d)
    d.add_argument("--seed", type=int, default=7)
    f = sub.add_parser("fetch", help="download latest ECMWF open data and process it")
    common(f)
    f.add_argument("--model", default="ifs", choices=["ifs", "aifs-single"])
    f.add_argument("--source", default="ecmwf", choices=["ecmwf", "aws", "azure", "google"])
    f.add_argument("--max-hours", type=int, default=144)
    f.add_argument("--cache", default="../cache")
    p = sub.add_parser("process", help="process local GRIB2 files")
    common(p)
    p.add_argument("grib", nargs="+")
    a = ap.parse_args(argv)

    if a.cmd == "demo":
        from .synth import make_scene
        _finish(make_scene(seed=a.seed), a, "synthetic")
    elif a.cmd == "fetch":
        from .fetch import fetch
        from .grib import read_scene
        paths, run = fetch(a.cache, model=a.model, source=a.source, max_hours=a.max_hours)
        label = "ECMWF IFS 0.25°" if a.model == "ifs" else "ECMWF AIFS 0.25°"
        _finish(read_scene(paths, model=label), a, f"ECMWF open data ({a.source}), CC-BY-4.0")
    else:
        from .grib import read_scene
        _finish(read_scene(a.grib), a, "local GRIB")


if __name__ == "__main__":
    main()
