"""The simulated "now" shared by the mock sources, the seed and the pipeline.

The synthetic world runs to a fixed date so results are reproducible. `fleetbi advance --days N` moves
this clock forward, which makes the next day's TMS, telematics, ERP and fuel records appear.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import synth


def _path(state_dir: Path) -> Path:
    return state_dir / "clock.json"


def now(state_dir: Path) -> datetime:
    p = _path(state_dir)
    if p.exists():
        return datetime.fromisoformat(json.loads(p.read_text())["now_utc"])
    return synth.default_clock()


def set_now(state_dir: Path, value: datetime) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    _path(state_dir).write_text(json.dumps({"now_utc": value.isoformat()}))


def business_date(value: datetime) -> date:
    """Last operating date whose ERP postings and fuel files exist at `value` (the day before)."""
    return value.date() - timedelta(days=1)
