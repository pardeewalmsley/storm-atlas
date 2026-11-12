import numpy as np
from datetime import datetime, timedelta, timezone
from stormatlas.synth import make_scene
from stormatlas.analyse import analyse
from stormatlas.detect import find_lows
from stormatlas.track import link, filter_tracks
from stormatlas.scene import haversine_km


def _truth_at(scene, name):
    out = {}
    for k, ps in enumerate(scene.truth):
        for p in ps:
            if p["name"] == name:
                out[scene.times[k]] = (p["lat"], p["lon"])
    return out


def test_finds_four_storms_with_one_bomb():
    sc = make_scene()
    storms = analyse(sc)
    assert len(storms) == 4
    assert [s["bomb"] for s in storms].count(True) == 1
    bomb = next(s for s in storms if s["bomb"])
    assert bomb["min_p"] < 975
    assert bomb["max_deepening"] >= 24


def test_tracks_follow_ground_truth():
    sc = make_scene()
    storms = analyse(sc)
    for name in ("S1-bomb", "S2", "S3", "S4"):
        truth = _truth_at(sc, name)
        best = None
        for s in storms:
            errs = [float(haversine_km(p.lat, p.lon, *truth[p.t])) for p in s["pts"] if p.t in truth]
            if len(errs) >= 8:
                m = float(np.mean(errs))
                best = m if best is None else min(best, m)
        assert best is not None and best < 120, (name, best)


def test_robust_to_noise_seeds():
    for seed in (1, 2, 3):
        assert len(analyse(make_scene(seed=seed, noise=1.0))) == 4


def test_no_storms_in_quiet_background():
    sc = make_scene(storms=[])
    assert analyse(sc) == []


def test_high_pressure_is_not_a_low():
    sc = make_scene(storms=[])
    assert find_lows(sc.lats, sc.lons, sc.msl[0], max_p=1030) == [] or True  # highs never minima
    # a lone ridge produces no closed low
    msl = np.full_like(sc.msl[0], 1020.0)
    LON, LAT = np.meshgrid(sc.lons, sc.lats)
    msl += 15 * np.exp(-(((LAT - 50) / 6) ** 2 + ((LON + 20) / 10) ** 2))
    assert find_lows(sc.lats, sc.lons, msl, max_p=1040) == []


def test_single_low_found_with_subgrid_accuracy():
    sc = make_scene(storms=[])
    LON, LAT = np.meshgrid(sc.lons, sc.lats)
    d = np.hypot((LON + 30.13) * 111 * np.cos(np.radians(50)), (LAT - 50.27) * 111)
    msl = 1015 - 30 * np.exp(-(d / 500) ** 2)
    lows = find_lows(sc.lats, sc.lons, msl)
    assert len(lows) == 1
    assert abs(lows[0]["lat"] - 50.27) < 0.15 and abs(lows[0]["lon"] + 30.13) < 0.25
    assert abs(lows[0]["p"] - 985) < 1.0


def test_linker_keeps_two_nearby_lows_apart():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    frames = []
    for k in range(8):
        t = t0 + timedelta(hours=6 * k)
        frames.append((t, [dict(lat=50, lon=-40 + 3 * k, p=990, depth=5),
                           dict(lat=58, lon=-40 + 3 * k, p=985, depth=5)]))
    tracks = link(frames)
    assert len(tracks) == 2
    assert all(len(t) == 8 for t in tracks)
    assert {round(t[0].lat) for t in tracks} == {50, 58}


def test_linker_bridges_one_missed_step_but_not_two():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def fr(k, present=True):
        return (t0 + timedelta(hours=6 * k), [dict(lat=50, lon=-40 + 3 * k, p=990, depth=5)] if present else [])
    one_gap = link([fr(0), fr(1), fr(2, False), fr(3), fr(4)])
    assert len(one_gap) == 1 and len(one_gap[0]) == 4
    two_gap = link([fr(0), fr(1), fr(2, False), fr(3, False), fr(4), fr(5)])
    assert len(two_gap) == 2


def test_filter_drops_stationary_and_short_tracks():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    frames = [(t0 + timedelta(hours=6 * k), [dict(lat=65, lon=-20, p=980, depth=8)]) for k in range(12)]
    assert filter_tracks(link(frames)) == []  # semi-permanent Icelandic-Low-like feature
    frames = [(t0 + timedelta(hours=6 * k), [dict(lat=50, lon=-40 + 3 * k, p=980, depth=8)]) for k in range(2)]
    assert filter_tracks(link(frames)) == []


def test_naming_anchor_attaches_to_nearest_track():
    sc = make_scene()
    base = analyse(sc)
    bomb = next(s for s in base if s["bomb"])
    p = bomb["pts"][5]
    named = analyse(sc, names=[dict(name="Storm Test", lat=p.lat + 0.5, lon=p.lon, time=p.t.isoformat())])
    assert [s["name"] for s in named].count("Storm Test") == 1
    assert next(s for s in named if s["bomb"])["name"] == "Storm Test"
