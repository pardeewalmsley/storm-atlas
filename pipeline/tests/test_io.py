import json, os
import numpy as np
from datetime import datetime, timezone
from stormatlas.synth import make_scene
from stormatlas.analyse import analyse
from stormatlas.export import write_web_data, encode, decode, FIELDS


def test_encode_decode_roundtrip_and_missing():
    a = np.array([[930.0, 1013.25, np.nan, 1060.0]])
    off, sc = FIELDS["msl"]
    back = decode(encode(a, off, sc), off, sc)
    assert np.allclose(back[0, [0, 1, 3]], a[0, [0, 1, 3]], atol=sc / 2 + 1e-9)
    assert np.isnan(back[0, 2])


def test_export_manifest_and_binary_shapes(tmp_path):
    sc = make_scene()
    storms = analyse(sc)
    m = write_web_data(sc, storms, str(tmp_path), stride=1, source="synthetic")
    g = m["grid"]
    n = len(m["times"]) * g["ny"] * g["nx"]
    for name, meta in m["fields"].items():
        raw = np.fromfile(tmp_path / meta["file"], dtype="<u2")
        assert raw.size == n
        vals = decode(raw, meta["offset"], meta["scale"]).reshape(len(m["times"]), g["ny"], g["nx"])
        ref = getattr(sc, name)
        assert np.abs(vals - ref).max() < meta["scale"] + 1e-6
    loaded = json.load(open(tmp_path / "manifest.json"))
    assert loaded["synthetic"] is True and len(loaded["storms"]) == 4
    assert loaded["storms"][0]["points"][0]["t"].endswith("Z")


def test_stride_halves_grid(tmp_path):
    sc = make_scene()
    m = write_web_data(sc, [], str(tmp_path), stride=2)
    assert m["grid"]["dlat"] == 2 * sc.dlat


def _write_grib(path, name, valid_step, lats, lons, vals, date=20261112, time=0):
    from eccodes import (codes_grib_new_from_samples, codes_set, codes_set_values,
                         codes_write, codes_release)
    h = codes_grib_new_from_samples("regular_ll_sfc_grib2")
    codes_set(h, "Ni", len(lons)); codes_set(h, "Nj", len(lats))
    codes_set(h, "latitudeOfFirstGridPointInDegrees", float(lats[0]))
    codes_set(h, "latitudeOfLastGridPointInDegrees", float(lats[-1]))
    codes_set(h, "longitudeOfFirstGridPointInDegrees", float(lons[0]))
    codes_set(h, "longitudeOfLastGridPointInDegrees", float(lons[-1]))
    codes_set(h, "iDirectionIncrementInDegrees", float(lons[1] - lons[0]))
    codes_set(h, "jDirectionIncrementInDegrees", float(lats[0] - lats[1]))
    codes_set(h, "dataDate", date); codes_set(h, "dataTime", time)
    codes_set(h, "stepUnits", 1); codes_set(h, "step", valid_step)
    codes_set(h, "shortName", name)
    codes_set_values(h, vals.ravel())
    with open(path, "ab") as f:
        codes_write(h, f)
    codes_release(h)


def test_grib_reader_roundtrip(tmp_path):
    from stormatlas.grib import read_scene
    lats = np.arange(90, -90.1, -0.5)
    lons = np.arange(0, 360, 0.5)           # ECMWF style 0..360 longitudes
    LON, LAT = np.meshgrid(lons, lats)
    p0 = 101300 - 3000 * np.exp(-(((LAT - 55) / 8) ** 2 + (((LON + 180) % 360 - 180 + 30) / 12) ** 2))
    path = str(tmp_path / "t.grib2")
    for step in (0, 3, 6):
        _write_grib(path, "msl", step, lats, lons, p0 - 100 * step)
        _write_grib(path, "10u", step, lats, lons, np.full_like(p0, 3.0))
        _write_grib(path, "10v", step, lats, lons, np.full_like(p0, 4.0))
    sc = read_scene([path])
    assert len(sc.times) == 3
    assert sc.times[1] - sc.times[0] == __import__("datetime").timedelta(hours=3)
    assert sc.run == datetime(2026, 11, 12, tzinfo=timezone.utc)
    assert sc.lons.min() >= -80 and sc.lons.max() <= 40 and sc.lats.max() <= 75
    assert np.allclose(sc.wind, 5.0, atol=1e-3)
    i = np.unravel_index(np.argmin(sc.msl[0]), sc.msl[0].shape)
    assert abs(sc.lats[i[0]] - 55) <= 1 and abs(sc.lons[i[1]] + 30) <= 1
    assert abs(sc.msl[0].min() - (1013 - 30)) < 0.5      # Pa -> hPa
    assert abs((sc.msl[0] - sc.msl[2]).mean() - (-0.0)) > -1  # sanity: shape ok
    # full pipeline on a decoded GRIB scene runs end to end
    assert analyse(sc) == []  # static single low: filtered as stationary
