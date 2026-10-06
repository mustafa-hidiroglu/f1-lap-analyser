from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import LAP_LENGTH_M, MakeLap

from f1lap.circuit import (
    Circuit,
    Corner,
    circuit_filename,
    corner_segments,
    detect_corners,
)
from f1lap.cli import main
from f1lap.delta import compare, corner_table
from f1lap.ingest.fastf1_source import circuit_from_frame
from f1lap.resample import resample_to_distance, rescale
from f1lap.store import write_lap

# conftest speed profile: 200 + 100*cos(2*pi*d/1250) -> minima at 625, 1875, 3125, 4375 m.
MINIMA_M = [625.0, 1875.0, 3125.0, 4375.0]


def _circuit(*dists: float, length: float = LAP_LENGTH_M, xy: bool = False) -> Circuit:
    def corner(n: int, d: float) -> Corner:
        if not xy:
            return Corner(n, d)
        a = 2 * np.pi * d / length  # conftest track: circle of radius 800
        return Corner(n, d, x=float(np.cos(a) * 800), y=float(np.sin(a) * 800))

    return Circuit("Test", length, tuple(corner(n, d) for n, d in enumerate(dists, 1)))


def test_detect_corners_finds_speed_minima(make_lap: MakeLap) -> None:
    circuit = detect_corners(resample_to_distance(make_lap(), 1.0))
    found = [c.distance_m for c in circuit.corners]
    np.testing.assert_allclose(found, MINIMA_M, atol=3.0)
    assert circuit.source == "detected" and [c.number for c in circuit.corners] == [1, 2, 3, 4]


def test_detect_ignores_small_dips(make_lap: MakeLap) -> None:
    lap = resample_to_distance(make_lap(), 1.0)
    with pytest.raises(ValueError, match="no corners"):
        detect_corners(lap, min_drop_kmh=500.0)


def test_positions_scale_with_lap_length(make_lap: MakeLap) -> None:
    lap = resample_to_distance(make_lap(length=5100.0), 1.0)
    pos = _circuit(1000.0, 2500.0).positions_on(lap)
    np.testing.assert_allclose(pos, [1020.0, 2550.0])


def test_positions_snap_to_lap_xy(make_lap: MakeLap) -> None:
    # Marker XY sits at 1000 m on the track; a lap normalised to a different length still
    # finds it at the right place on its own line (scaling alone would say 1020 m).
    lap = rescale(resample_to_distance(make_lap(), 1.0), 5100.0)
    pos = _circuit(1000.0, 2500.0, xy=True).positions_on(lap)
    np.testing.assert_allclose(pos, [1020.0, 2550.0], atol=1.5)
    raw = resample_to_distance(make_lap(), 1.0)
    np.testing.assert_allclose(_circuit(1000.0, 2500.0, xy=True).positions_on(raw),
                               [1000.0, 2500.0], atol=1.5)


def test_segments_merge_complexes_and_tile_lap(make_lap: MakeLap) -> None:
    lap = resample_to_distance(make_lap(), 1.0)
    segs = corner_segments(_circuit(600.0, 680.0, 2000.0, 3900.0, 4000.0, 4100.0), lap)
    assert [s.name for s in segs] == ["T1-2", "T3", "T4-6"]
    assert segs[0].start_m == 0.0 and segs[-1].end_m == lap.grid_end_m
    assert [s.end_m for s in segs[:-1]] == [s.start_m for s in segs[1:]]
    assert segs[0].end_m == pytest.approx((680.0 + 2000.0) / 2)


def test_corner_table_sums_to_final_delta(make_lap: MakeLap) -> None:
    ref = resample_to_distance(make_lap(seed=3), 1.0)
    t = make_lap(seed=3)
    slow = resample_to_distance(type(t)({**t.channels, "time": t["time"] * 1.02}, t.meta), 1.0)
    cmp = compare(ref, slow)
    table = corner_table(cmp, corner_segments(detect_corners(ref), ref))
    assert table.names == ("T1", "T2", "T3", "T4")
    assert table.delta_s.sum() == pytest.approx(cmp.final_delta_s, abs=1e-9)
    assert (table.delta_s > 0).all()


def test_circuit_json_roundtrip(tmp_path: Path) -> None:
    c = _circuit(100.0, 900.0, xy=True)
    assert Circuit.load(c.save(tmp_path / "c.json")) == c


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(version=99),
        lambda d: d["corners"][0].update(number="1"),
        lambda d: d["corners"][0].update(distance_m=True),
        lambda d: d.pop("length_m"),
        lambda d: d.update(meta=[]),
        lambda d: d["corners"].reverse(),
        lambda d: d.update(corners=[]),
    ],
)
def test_circuit_rejects_malformed_json(mutate: object) -> None:
    raw = _circuit(100.0, 900.0).to_dict()
    mutate(raw)  # type: ignore[operator]
    with pytest.raises(ValueError):
        Circuit.from_dict(json.loads(json.dumps(raw)))


def test_circuit_from_fastf1_frame() -> None:
    frame = pd.DataFrame(
        {
            "X": [10.0, 0.0, 5.0, 7.0],
            "Y": [0.0, 1.0, 2.0, 3.0],
            "Number": [3, 1, 2, 4],
            "Letter": ["", "", "a", ""],
            "Angle": [0.0] * 4,
            "Distance": [1500.0, 300.0, 900.0, np.nan],
        }
    )
    c = circuit_from_frame(frame, 5000.0, "Testring", {"year": 2024})
    assert [c.label for c in c.corners] == ["1", "2a", "3"]
    assert c.corners[0].x == 0.0 and c.source == "fastf1"


def test_circuit_filename() -> None:
    assert circuit_filename(2024, "Italian Grand Prix") == "2024_italian_grand_prix.json"
    assert circuit_filename(None, "../../etc") == "______etc.json"


def test_cli_corners_and_delta_by_corner(
    make_lap: MakeLap, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = write_lap(resample_to_distance(make_lap(seed=1), 1.0), tmp_path / "ref.parquet")
    oth = write_lap(resample_to_distance(make_lap(seed=2), 1.0), tmp_path / "oth.parquet")
    circuit_json = tmp_path / "circuit.json"

    assert main(["corners", str(ref), "--detect", "--json", str(circuit_json)]) == 0
    assert "4 corners (detected)" in capsys.readouterr().out

    assert main(["delta", str(ref), str(oth), "--circuit", str(circuit_json)]) == 0
    out = capsys.readouterr().out
    assert all(f"T{n} " in out for n in range(1, 5))
