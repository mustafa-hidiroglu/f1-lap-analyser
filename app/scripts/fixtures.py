"""Regenerate Swift test fixtures from real sidecar replies (needs the FastF1 cache).

    uv run python app/scripts/fixtures.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from f1lap.server import Server, _finite

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "app" / "Tests" / "F1LapKitTests" / "Fixtures"
SES = {"year": 2024, "event": "Monza", "session": "Q"}


async def main() -> None:
    server = Server(ROOT / "cache")
    replies = {
        "schedule": await server.call("schedule", {"year": 2024}),
        "session": await server.call("session", SES),
        "compare": await server.call(
            "compare", {**SES, "reference": {"driver": "LEC"}, "other": {"driver": "SAI"}}
        ),
        "rate": await server.call("rate", {**SES, "driver": "LEC"}),
    }
    server.close()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, result in replies.items():
        (OUT / f"{name}.json").write_text(json.dumps(_finite(result), allow_nan=False))
        print(f"wrote {name}.json ({(OUT / f'{name}.json').stat().st_size // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
