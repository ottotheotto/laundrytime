"""Electro-price: render Nord Pool SE4 spot prices for a Kindle browser."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


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


def now_slot(slots: list[Slot], now: datetime) -> Slot | None:
    """Return the slot that contains `now`, or None if `now` is outside all slots.

    A slot contains `now` iff ``time_start <= now < time_end`` (inclusive lower,
    exclusive upper). Slots must be timezone-aware; comparison preserves offsets.
    """
    for slot in slots:
        if slot.time_start <= now < slot.time_end:
            return slot
    return None


def slice_window(
    slots: list[Slot],
    now: datetime,
    *,
    hours_back: int = 6,
    hours_forward: int = 18,
) -> list[Slot]:
    """Return the slots whose interval overlaps [now - hours_back, now + hours_forward).

    Filtering is by absolute timestamp, so DST transitions are handled correctly
    by the underlying tz-aware datetimes — no slot-index assumptions.
    """
    start = now - timedelta(hours=hours_back)
    end = now + timedelta(hours=hours_forward)
    return [s for s in slots if s.time_start < end and s.time_end > start]
