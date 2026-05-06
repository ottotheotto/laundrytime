"""Electro-price: render Nord Pool SE4 spot prices for a Kindle browser."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta


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


def cheapest_upcoming(slots: list[Slot], now: datetime) -> Slot | None:
    """Return the cheapest slot whose ``time_start > now``, or None if no such slot.

    Ties on price are broken by earliest ``time_start``.
    """
    upcoming = [s for s in slots if s.time_start > now]
    if not upcoming:
        return None
    return min(upcoming, key=lambda s: (s.sek_per_kwh, s.time_start))


def window_average(slots: list[Slot]) -> float:
    """Arithmetic mean of ``sek_per_kwh`` across the given slots. Empty -> 0.0."""
    if not slots:
        return 0.0
    return sum(s.sek_per_kwh for s in slots) / len(slots)


_API_TEMPLATE = "https://www.elprisetjustnu.se/api/v1/prices/{year}/{mm:02d}-{dd:02d}_SE4.json"


def fetch_day(
    day: date,
    *,
    urlopen=None,
    sleep=time.sleep,
) -> list[dict] | None:
    """Fetch one day of price data. Returns parsed JSON, or None on 404.

    Retries once after 5s on transient failures (URLError or HTTP 5xx).
    Raises on any other failure (including 4xx other than 404, and a second
    transient failure after the retry).
    """
    if urlopen is None:
        urlopen = urllib.request.urlopen
    url = _API_TEMPLATE.format(year=day.year, mm=day.month, dd=day.day)

    last_err: Exception | None = None
    for attempt in range(2):
        try:
            with urlopen(url, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if 500 <= e.code < 600:
                last_err = e
            else:
                raise
        except urllib.error.URLError as e:
            last_err = e
        except TimeoutError as e:
            last_err = e
        if attempt == 0:
            sleep(5)
    assert last_err is not None
    raise last_err
