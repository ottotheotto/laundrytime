"""Electro-price: render Nord Pool SE4 spot prices for a Kindle browser."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Slot:
    """A single price slot from the API. Times are timezone-aware."""
    time_start: datetime
    time_end: datetime
    sek_per_kwh: float


def parse_slots(payload: list[dict]) -> list[Slot]:
    """Convert raw API JSON list into Slot objects.

    The elprisetjustnu.se v1 API returns objects with keys
    ``SEK_per_kWh``, ``EUR_per_kWh``, ``EXR``, ``time_start``, ``time_end``.
    Only ``SEK_per_kWh`` and the timestamps are used downstream.
    """
    return [
        Slot(
            time_start=datetime.fromisoformat(item["time_start"]),
            time_end=datetime.fromisoformat(item["time_end"]),
            sek_per_kwh=float(item["SEK_per_kWh"]),
        )
        for item in payload
    ]
