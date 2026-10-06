"""Perfect lap: a quasi-steady-state (QSS) point-mass lap simulation calibrated on a session.

The simulated car may, at every point of the reference lap's grid, go as fast as the session's
fastest laps showed is possible there, and between those points it brakes as late and
accelerates as hard as the session's cars demonstrated:

- `vlim(s)`: point-wise maximum of the calibration laps' (smoothed) speed. This is the grip the
  cars demonstrably had at that point. Curvature from FastF1's ~4 Hz position data understates
  hairpins (by ~40 km/h in testing), so demonstrated speed is the better corner limit.
- `CarModel.accel(v) = min(cap, power / v - drag * v²)`: fitted to the 99th-percentile
  acceleration envelope of the calibration laps (traction-limited at low speed, power and drag
  limited at high speed).
- `CarModel.brake(v) = b0 + b2 * v²`: fitted to the 99th-percentile deceleration envelope
  (downforce adds braking grip with v²).

The speed profile is `min(forward pass, backward pass)`, iterated over two laps so a flying
lap closes on itself. The calibration set is the session's `CALIBRATION_LAPS` fastest valid
laps: a fixed count keeps qualifying (≈90 laps) and races (≈900) comparable — a point-wise
maximum over hundreds of laps would pick up a lucky tow somewhere. On 2024-25 sessions the sim
lap is 1-3 % faster than the session's fastest lap.

The result is an ordinary `ResampledLap` (driver "SIM") with throttle/brake channels derived
from which limit is active, so `delta.compare` and `phases.compare_corners` work against it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any, Final

import numpy as np
import numpy.typing as npt
from scipy.ndimage import gaussian_filter1d

from f1lap import schema
from f1lap.delta import align
from f1lap.resample import nominal_length
from f1lap.trace import LapMeta, ResampledLap

F64 = npt.NDArray[np.float64]

SPEED: Final = "speed"
MODEL_VERSION: Final = 2
CALIBRATION_LAPS: Final = 8
MIN_CALIBRATION_LAPS: Final = 3
#: Accepted sim lap time, as a fraction faster than the session's fastest lap. Outside it the
#: calibration is broken (bad telemetry, wet/red-flag session) and no sim is kept.
SANITY_GAIN: Final = (0.0, 0.08)  # 2024 qualifying: 1.1-3.7 %; cruised races (Monaco) ~6 %
G: Final = 9.81
SMOOTH_M: Final = 4.0  # speed smoothing (Gaussian sigma) before limits and derivatives
ENVELOPE_Q: Final = 0.99  # quantile of acceleration / deceleration per speed bin
BIN_MS: Final = 5.0  # speed bin width (m/s) for the envelopes
MIN_BIN_SAMPLES: Final = 300
SIM_DRIVER: Final = "SIM"
#: Throttle shown while the car slows at its grip limit without braking (a lift into a corner).
GRIP_THROTTLE: Final = 50.0


@dataclass(frozen=True, slots=True)
class CarModel:
    """Longitudinal limits of the simulated car (SI units: m/s, m/s²)."""

    accel_cap: float  # traction limit
    power: float  # P/m, m²/s³
    drag: float  # 1/m
    brake0: float  # mechanical braking grip
    brake2: float  # aero braking grip per v²
    vmax: float

    def accel(self, v: float) -> float:
        return max(0.0, min(self.accel_cap, self.power / max(v, 1.0) - self.drag * v * v))

    def brake(self, v: float) -> float:
        return self.brake0 + self.brake2 * v * v

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CarModel:
        return cls(**{k: float(d[k]) for k in cls.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class SimLap:
    lap: ResampledLap
    model: CarModel
    calibration: tuple[tuple[str, int | None, float | None], ...]  # (driver, lap, lap time)
    fastest_lap_s: float | None  # the session's fastest valid lap, for context
    version: int = MODEL_VERSION

    @property
    def lap_time_s(self) -> float:
        t = self.lap.meta.lap_time_s
        assert t is not None
        return t

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "lap_time_s": self.lap_time_s,
            "fastest_lap_s": self.fastest_lap_s,
            "model": self.model.to_dict(),
            "calibration": [
                {"driver": d, "lap_number": n, "lap_time_s": t} for d, n, t in self.calibration
            ],
        }


def _envelope(v: F64, a: F64, q: float) -> F64:
    """(bin centre, quantile of a) for every well-populated speed bin."""
    pts = []
    finite = np.isfinite(v) & np.isfinite(a)
    v, a = v[finite], a[finite]
    for lo in np.arange(np.floor(v.min() / BIN_MS) * BIN_MS, v.max(), BIN_MS):
        m = (v >= lo) & (v < lo + BIN_MS)
        if m.sum() >= MIN_BIN_SAMPLES:
            pts.append((lo + BIN_MS / 2, float(np.quantile(a[m], q))))
    return np.array(pts, dtype=np.float64).reshape(-1, 2)


def fit_car(speed: F64, time: F64, step_m: float) -> CarModel:
    """Fit `CarModel` to calibration laps given as `(laps, n)` arrays of speed (m/s) and time (s)
    on one distance grid."""
    vs = gaussian_filter1d(speed, SMOOTH_M / step_m, axis=1)
    dt = np.gradient(time, axis=1)
    dvdt = np.gradient(vs, axis=1) / np.where(dt > 1e-4, dt, np.nan)
    v, a = vs.ravel(), dvdt.ravel()
    vmax = float(np.nanmax(vs))

    acc = _envelope(v, a, ENVELOPE_Q)
    brk = _envelope(v, -a, ENVELOPE_Q)
    if len(acc) < 3 or len(brk) < 3:
        raise ValueError("not enough telemetry to fit the car's acceleration and braking")
    # accel = power / v - drag * v², above the traction-limited low-speed bins
    hi = acc[acc[:, 0] >= 35.0] if (acc[:, 0] >= 35.0).sum() >= 3 else acc
    (power, drag), *_ = np.linalg.lstsq(np.c_[1 / hi[:, 0], -hi[:, 0] ** 2], hi[:, 1], rcond=None)
    low = acc[acc[:, 0] < 40.0]
    cap = float(np.quantile(low[:, 1], 0.9)) if len(low) else float(acc[:, 1].max())
    (b0, b2), *_ = np.linalg.lstsq(np.c_[np.ones(len(brk)), brk[:, 0] ** 2], brk[:, 1],
                                   rcond=None)
    return CarModel(
        accel_cap=float(np.clip(cap, 0.5 * G, 2.5 * G)),
        power=float(max(power, 50.0)),
        drag=float(max(drag, 0.0)),
        brake0=float(max(b0, 1.0 * G)),
        brake2=float(max(b2, 0.0)),
        vmax=vmax,
    )


def solve(
    vlim: F64, model: CarModel, step_m: float, shown: F64 | None = None,
) -> tuple[F64, F64, F64]:
    """QSS speed profile under `vlim`: returns (speed, forward-limited, backward-limited).

    `shown` (laps x n, m/s) are the calibration laps' speeds. Besides the fitted model, the car
    may do what a lap demonstrated *from the same or a better state*: reach `shown[k, i]` when
    it arrives at `i - 1` at least as fast as lap k did, and enter `i` at `shown[k, i]` when it
    needs to leave at `i + 1` no slower than lap k left. So grip shown at low speed is never
    used at high speed, and by induction over the passes the profile is never slower than any
    calibration lap anywhere; the fitted model decides wherever no lap was at the limit."""
    n = vlim.size
    k = np.zeros((0, n)) if shown is None else shown
    vf = vlim.copy()
    for _ in range(2):  # second pass closes the lap: the start speed is the end speed
        for i in range(1, n):
            v = vf[i - 1]
            reach = np.sqrt(v * v + 2.0 * model.accel(v) * step_m)
            ok = k[:, i - 1] <= v + 1e-9
            if ok.any():
                reach = max(reach, float(k[ok, i].max()))
            vf[i] = min(vlim[i], reach)
        vf[0] = min(vf[0], vf[-1])
    vb = vf.copy()
    for _ in range(2):
        for i in range(n - 2, -1, -1):
            v = vb[i + 1]
            entry = np.sqrt(v * v + 2.0 * model.brake(v) * step_m)
            ok = k[:, i + 1] <= v + 1e-9
            if ok.any():
                entry = max(entry, float(k[ok, i].max()))
            vb[i] = min(vb[i], entry)
        vb[-1] = min(vb[-1], vb[0])
    return np.minimum(vf, vb), vf, vb


WARP_WINDOW_M: Final = 60.0  # search ± this far along the reference line when warping
WARP_SMOOTH_M: Final = 30.0


def warp_to_line(lap: ResampledLap, reference: ResampledLap) -> F64:
    """Speed of `lap` (already on `reference`'s grid) re-mapped by track *position*.

    FastF1 distance is integrated speed, so two laps on one grid can be 10-30 m apart locally;
    a point-wise maximum over misaligned laps would borrow speed from the neighbouring braking
    zone (5-6 % too fast at Monaco/Singapore). Each sample is projected onto the reference
    line (nearest X/Y point within ±`WARP_WINDOW_M`), the projected distances are smoothed and
    made monotonic, and the speed is re-sampled on the reference grid. Without X/Y the speed is
    returned unchanged."""
    v = lap[SPEED]
    if not all(c in ch.channels for c in ("x", "y") for ch in (lap, reference)):
        return v
    step = reference.step_m
    n = len(reference)
    w = max(1, round(WARP_WINDOW_M / step))
    xr, yr = reference["x"], reference["y"]
    xl, yl = lap["x"], lap["y"]
    offsets = np.arange(-w, w + 1)
    idx = np.clip(np.arange(n)[:, None] + offsets[None, :], 0, n - 1)  # (n, 2w+1)
    dist2 = (xr[idx] - xl[:, None]) ** 2 + (yr[idx] - yl[:, None]) ** 2
    proj = idx[np.arange(n), np.argmin(dist2, axis=1)].astype(np.float64) * step
    shift = gaussian_filter1d(proj - reference[schema.DISTANCE], WARP_SMOOTH_M / step,
                              mode="nearest")
    where = np.maximum.accumulate(reference[schema.DISTANCE] + shift)
    return np.interp(reference[schema.DISTANCE], where, v)


class SimError(ValueError):
    """The session cannot produce a trustworthy perfect lap.

    `permanent=False` when the cause may be transient (e.g. no laps loaded at all, which is
    what FastF1 leaves after a swallowed network error): such failures are never recorded."""

    def __init__(self, message: str, *, permanent: bool = True) -> None:
        super().__init__(message)
        self.permanent = permanent


def calibration_laps(laps: Sequence[ResampledLap], k: int = CALIBRATION_LAPS) -> list[ResampledLap]:
    timed = [lap for lap in laps if lap.meta.lap_time_s is not None]
    return sorted(timed, key=lambda lap: lap.meta.lap_time_s or np.inf)[:k]


def simulate(
    reference: ResampledLap, laps: Sequence[ResampledLap], k: int = CALIBRATION_LAPS
) -> SimLap:
    """Perfect lap on `reference`'s grid, calibrated on the `k` fastest of `laps`.

    Raises `SimError` with fewer than `MIN_CALIBRATION_LAPS` timed laps or when the result fails
    the `SANITY_GAIN` check against the fastest lap."""
    calib = calibration_laps(laps, k)
    if len(calib) < MIN_CALIBRATION_LAPS:
        raise SimError(f"only {len(calib)} timed laps; need {MIN_CALIBRATION_LAPS} to calibrate",
                       permanent=bool(calib))
    step = reference.step_m
    on_grid = [align(reference, lap) for lap in calib]
    speed = np.vstack([lap[SPEED] for lap in on_grid]) / 3.6
    time = np.vstack([lap[schema.TIME] for lap in on_grid])
    try:
        model = fit_car(speed, time, step)
    except ValueError as exc:
        raise SimError(str(exc)) from exc
    warped = np.vstack([warp_to_line(lap, reference) for lap in on_grid]) / 3.6
    smooth = gaussian_filter1d(warped, SMOOTH_M / step, axis=1)
    vlim = smooth.max(axis=0)
    v, vf, vb = solve(vlim, model, step, smooth)

    d = reference[schema.DISTANCE]
    dt = 2.0 * np.diff(d) / (v[1:] + v[:-1])
    t = np.concatenate(([0.0], np.cumsum(dt)))
    end_gap = nominal_length(reference) - float(d[-1])
    lap_time = float(t[-1] + max(end_gap, 0.0) / v[-1])

    # Brake where the braking limit binds; lift where the speed limit falls without braking;
    # otherwise full throttle (also while held at a corner's demonstrated speed: steady state).
    braking = vb < vf - 1e-6
    lifting = ~braking & (np.gradient(v) < -1e-4)
    channels: dict[str, F64] = {
        schema.DISTANCE: d,
        schema.TIME: t,
        SPEED: v * 3.6,
        "throttle": np.where(braking, 0.0, np.where(lifting, GRIP_THROTTLE, 100.0)),
        "brake": braking.astype(np.float64),
    }
    for c in ("x", "y"):
        if c in reference.channels:
            channels[c] = reference[c]
    m = reference.meta
    meta = replace(
        LapMeta(), driver=SIM_DRIVER, lap_number=None, lap_time_s=lap_time, source="sim",
        year=m.year, event=m.event, session=m.session, raw_length_m=nominal_length(reference),
    )
    fastest = min((lap.meta.lap_time_s for lap in calib if lap.meta.lap_time_s), default=None)
    if fastest is not None:
        gain = 1.0 - lap_time / fastest
        if not SANITY_GAIN[0] <= gain <= SANITY_GAIN[1]:
            raise SimError(
                f"implausible sim lap {lap_time:.3f} s vs fastest {fastest:.3f} s "
                f"({gain:+.1%} gain); telemetry or calibration is unreliable"
            )
    return SimLap(
        lap=ResampledLap(channels, step_m=step, meta=meta),
        model=model,
        calibration=tuple(
            (lap.meta.driver, lap.meta.lap_number, lap.meta.lap_time_s) for lap in calib
        ),
        fastest_lap_s=fastest,
    )
