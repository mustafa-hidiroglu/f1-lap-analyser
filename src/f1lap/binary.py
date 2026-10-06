"""Structure-of-Arrays binary files for handing traces to the macOS app without JSON.

Each column is one contiguous little-endian array at an 8-byte-aligned offset; the layout (name,
dtype, offset, count) travels in the JSON-RPC response, so the app can memory-map the file and view
each column in place (`Data(contentsOf:options:.alwaysMapped)` + `withUnsafeBytes`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt

_DTYPES: Final = {np.dtype("<f8"): "f64", np.dtype("<i2"): "i16"}
_ALIGN: Final = 8


def write_soa(path: Path, columns: Mapping[str, npt.NDArray[Any]]) -> list[dict[str, Any]]:
    """Write `columns` atomically; returns the layout. Float columns are stored as f64, integer
    columns as i16 (the schema's discrete dtype)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    layout: list[dict[str, Any]] = []
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        offset = 0
        for name, values in columns.items():
            arr = np.asarray(values)
            dtype = np.dtype("<i2") if arr.dtype.kind in "iub" else np.dtype("<f8")
            arr = np.ascontiguousarray(arr, dtype=dtype)
            if arr.ndim != 1:
                raise ValueError(f"column {name!r} must be 1-D")
            pad = -offset % _ALIGN
            fh.write(b"\0" * pad)
            offset += pad
            fh.write(arr.tobytes())
            layout.append(
                {"name": name, "dtype": _DTYPES[dtype], "offset": offset, "count": arr.size}
            )
            offset += arr.nbytes
    os.replace(tmp, path)
    return layout


def read_soa(path: Path, layout: list[dict[str, Any]]) -> dict[str, npt.NDArray[Any]]:
    """Memory-mapped read-back (used by tests; the app does the same in Swift)."""
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    out: dict[str, npt.NDArray[Any]] = {}
    for col in layout:
        dtype = np.dtype("<f8") if col["dtype"] == "f64" else np.dtype("<i2")
        out[col["name"]] = np.frombuffer(raw, dtype=dtype, count=col["count"], offset=col["offset"])
    return out
