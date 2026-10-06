"""Circuit model: corners, their positions on a given lap, and corner-based segmentation.

Two sources:
- FastF1 circuit info (`ingest.fastf1_source.circuit_from_session`): hand-placed corner markers
  with track X/Y, snapped to the session's fastest lap.
- Telemetry detection (`detect_corners`): significant speed minima on a lap. Works for any data
  source, including exports with no circuit metadata.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.signal import find_peaks

from f1lap import schema
from f1lap.resample import nominal_length
from f1lap.trace import ResampledLap

F64 = npt.NDArray[np.float64]

# When snapping a corner marker to a lap's X/Y line, only search this far either side of the
# length-scaled estimate, so markers cannot snap onto a nearby, different part of the track.
SNAP_WINDOW_M = 300.0
_FORMAT_VERSION = 1


@dataclass(frozen=True, slots=True)
class Corner:
    number: int
    distance_m: float  # along the circuit's reference lap
    letter: str = ""
    x: float | None = None  # track coordinates of the marker, if known
    y: float | None = None

    @property
    def label(self) -> str:
        return f"{self.number}{self.letter}"


@dataclass(frozen=True, slots=True)
class Circuit:
    name: str
    length_m: float  # length of the reference lap the corner distances were measured on
    corners: tuple[Corner, ...]
    source: str = ""  # "fastf1" or "detected"
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (math.isfinite(self.length_m) and self.length_m > 0):
            raise ValueError(f"circuit length must be finite and > 0, got {self.length_m}")
        if not self.corners:
            raise ValueError("circuit has no corners")
        d = np.array([c.distance_m for c in self.corners])
        if not (np.all(np.isfinite(d)) and np.all(np.diff(d) > 0)):
            raise ValueError("corner distances must be finite and strictly increasing")
        if d[0] < 0 or d[-1] > self.length_m:
            raise ValueError("corner distances must lie within the lap")

    def positions_on(self, lap: ResampledLap) -> F64:
        """Corner distances on `lap`'s grid.

        Starts from the length-scaled distance, then (if both circuit and lap have X/Y) snaps each
        corner to the nearest point on the lap's own line within ±`SNAP_WINDOW_M`.
        """
        length = nominal_length(lap)
        est = np.array([c.distance_m for c in self.corners]) * (length / self.length_m)
        has_xy = all(c.x is not None and c.y is not None for c in self.corners)
        if not has_xy or "x" not in lap.channels or "y" not in lap.channels:
            return est
        d, x, y = lap[schema.DISTANCE], lap["x"], lap["y"]
        out = est.copy()
        for i, c in enumerate(self.corners):
            lo, hi = np.searchsorted(d, [est[i] - SNAP_WINDOW_M, est[i] + SNAP_WINDOW_M])
            if hi <= lo:
                continue
            err = (x[lo:hi] - c.x) ** 2 + (y[lo:hi] - c.y) ** 2
            if np.isfinite(err).any():
                out[i] = d[lo + int(np.nanargmin(err))]
        return np.maximum.accumulate(out)  # keep order if two markers snap to the same point

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": _FORMAT_VERSION,
            "name": self.name,
            "length_m": self.length_m,
            "source": self.source,
            "meta": self.meta,
            "corners": [
                {"number": c.number, "letter": c.letter, "distance_m": c.distance_m,
                 "x": c.x, "y": c.y}
                for c in self.corners
            ],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Circuit:
        """Parse untrusted JSON; raises ValueError on any malformed field."""
        try:
            if raw["version"] != _FORMAT_VERSION:
                raise ValueError(f"unsupported circuit format version {raw['version']!r}")
            corners = tuple(
                Corner(
                    number=_typed(c["number"], int),
                    distance_m=float(_typed(c["distance_m"], int, float)),
                    letter=_typed(c.get("letter", ""), str),
                    x=_opt_float(c.get("x")),
                    y=_opt_float(c.get("y")),
                )
                for c in raw["corners"]
            )
            meta = raw.get("meta", {})
            if not isinstance(meta, dict):
                raise ValueError("meta must be an object")
            return cls(
                name=_typed(raw["name"], str),
                length_m=float(_typed(raw["length_m"], int, float)),
                corners=corners,
                source=_typed(raw.get("source", ""), str),
                meta=meta,
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"malformed circuit data: {exc!r}") from exc

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    @classmethod
    def load(cls, path: Path) -> Circuit:
        return cls.from_dict(json.loads(path.read_text()))


def circuit_filename(year: int | None, event: str) -> str:
    """Filesystem-safe name for a saved circuit, e.g. `2024_italian_grand_prix.json`."""
    name = "_".join(p for p in (str(year or ""), event) if p).lower() or "circuit"
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name) + ".json"


def _typed(value: Any, *types: type) -> Any:
    if isinstance(value, bool) or not isinstance(value, types):
        raise ValueError(f"expected {'/'.join(t.__name__ for t in types)}, got {value!r}")
    return value


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(_typed(value, int, float))


def detect_corners(
    lap: ResampledLap, min_drop_kmh: float = 20.0, min_separation_m: float = 80.0
) -> Circuit:
    """Corners as speed minima at least `min_drop_kmh` below the surrounding speed.

    Flat-out kinks with no meaningful speed loss are deliberately not reported.
    """
    speed = lap["speed"]
    distance = max(1, round(min_separation_m / lap.step_m))
    idx, _ = find_peaks(-speed, prominence=min_drop_kmh, distance=distance)
    if idx.size == 0:
        raise ValueError(f"no corners found with ≥{min_drop_kmh} km/h speed drop")
    d, x, y = lap[schema.DISTANCE], lap.channels.get("x"), lap.channels.get("y")
    corners = tuple(
        Corner(
            number=n,
            distance_m=float(d[i]),
            x=None if x is None else float(x[i]),
            y=None if y is None else float(y[i]),
        )
        for n, i in enumerate(idx, 1)
    )
    return Circuit(
        name=lap.meta.event or lap.meta.source or "unknown",
        length_m=nominal_length(lap),
        corners=corners,
        source="detected",
        meta={"min_drop_kmh": min_drop_kmh, "min_separation_m": min_separation_m},
    )


@dataclass(frozen=True, slots=True)
class Segment:
    name: str  # e.g. "T1-2" for a complex, "T11" for a single corner
    start_m: float
    end_m: float
    apex_m: tuple[float, ...]  # corner positions inside this segment


def corner_segments(
    circuit: Circuit, lap: ResampledLap, merge_within_m: float = 150.0
) -> list[Segment]:
    """Split `lap` into one segment per corner complex.

    Corners closer than `merge_within_m` form a complex (chicanes, esses). Segment boundaries lie
    midway between neighbouring complexes; the first segment starts at 0 and the last ends at
    the lap's grid end, so segments tile the whole lap.
    """
    pos = circuit.positions_on(lap)
    groups: list[list[int]] = [[0]]
    for i in range(1, pos.size):
        if pos[i] - pos[i - 1] <= merge_within_m:
            groups[-1].append(i)
        else:
            groups.append([i])

    end = lap.grid_end_m
    bounds = [0.0]
    for prev, nxt in pairwise(groups):
        bounds.append(float((pos[prev[-1]] + pos[nxt[0]]) / 2))
    bounds.append(end)

    segments = []
    for g, (lo, hi) in zip(groups, pairwise(bounds), strict=True):
        first, last = circuit.corners[g[0]], circuit.corners[g[-1]]
        name = f"T{first.label}" if len(g) == 1 else f"T{first.label}-{last.label}"
        segments.append(Segment(name, lo, hi, tuple(float(pos[i]) for i in g)))
    return segments
