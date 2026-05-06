# Electro-Price Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a static webpage at GitHub Pages that renders Nord Pool SE4 spot prices as a single filled-area chart (last 6h + next 18h, 15-min granularity), regenerated hourly by a GitHub Actions cron, optimized for the Kindle e-ink browser. No client-side JS for data.

**Architecture:** One Python file (`build.py`, stdlib only) fetches prices from elprisetjustnu.se for yesterday/today/tomorrow, computes the rolling 24h window, and renders a self-contained HTML+inline-SVG page. Two GitHub Actions workflows: `test.yml` runs pytest on push/PR; `publish.yml` runs the build hourly and deploys via `actions/upload-pages-artifact` + `actions/deploy-pages` (no `gh-pages` branch).

**Tech Stack:** Python 3.12 (stdlib: `urllib.request`, `json`, `datetime`, `zoneinfo`, `argparse`, `pathlib`), pytest 8 (dev only), GitHub Actions, GitHub Pages.

**Reference spec:** `docs/superpowers/specs/2026-05-06-electro-price-design.md`.

---

## File Structure

| Path | Purpose |
|---|---|
| `build.py` | Single-file generator. Contains `Slot` dataclass, parsing, time-window math, fetch with retry, HTML/SVG renderer, and `main()` CLI. Inline f-string template. |
| `tests/__init__.py` | Empty — marks `tests/` as a package. |
| `tests/test_build.py` | All pytest unit tests for `build.py`. |
| `pyproject.toml` | Project metadata + dev dep on `pytest`. |
| `README.md` | How to run locally; how to enable GitHub Pages. |
| `.github/workflows/test.yml` | Pytest on push to `main` and on PRs. |
| `.github/workflows/publish.yml` | Hourly cron + build + Pages deploy. |

`build.py` is intentionally a single file because the spec mandates it. Functions inside `build.py` (in dependency order):

```
Slot                       (dataclass)
parse_slots(payload)       (list[dict] -> list[Slot])
now_slot(slots, now)       (find current slot)
slice_window(slots, now, hours_back, hours_forward)
cheapest_upcoming(slots, now)
window_average(slots)
fetch_day(date, *, urlopen, sleep)        (one HTTP request, retry, 404→None)
fetch_dataset(now, *, fetch)              (yesterday/today/tomorrow, tolerates missing)
render(slots, now)                        (returns full HTML string)
main(argv)                                (CLI entry; argparse; writes file)
```

All test code lives in `tests/test_build.py`. JSON fixtures are inline Python literals — no separate fixture files (the data is small and stable).

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/test_build.py` (placeholder smoke test)
- Create: `build.py` (placeholder)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "electro-price"
version = "0.0.1"
requires-python = ">=3.12"

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Create `tests/__init__.py`**

Empty file — needed so `tests` is importable as a package.

```python
```

- [ ] **Step 3: Create `build.py` with module docstring + `__future__` import**

```python
"""Electro-price: render Nord Pool SE4 spot prices for a Kindle browser."""
from __future__ import annotations
```

- [ ] **Step 4: Create `tests/test_build.py` with one trivial smoke test**

```python
import build


def test_module_imports():
    assert build.__doc__
```

- [ ] **Step 5: Install pytest and verify it runs**

Run:
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
pytest
```

Expected: `1 passed` in green.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml build.py tests/__init__.py tests/test_build.py
git commit -m "Scaffold: pyproject, build.py stub, smoke test"
```

---

## Task 2: `Slot` dataclass and `parse_slots`

**What:** Convert raw API JSON dicts into a list of frozen `Slot` dataclasses with parsed timezone-aware datetimes and float prices.

**Files:**
- Modify: `build.py` (add imports, `Slot`, `parse_slots`)
- Modify: `tests/test_build.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
from datetime import datetime, timezone, timedelta

import build


SAMPLE_PAYLOAD = [
    {
        "SEK_per_kWh": 0.80,
        "EUR_per_kWh": 0.07,
        "EXR": 11.4,
        "time_start": "2026-05-06T14:00:00+02:00",
        "time_end":   "2026-05-06T14:15:00+02:00",
    },
    {
        "SEK_per_kWh": 0.76,
        "EUR_per_kWh": 0.067,
        "EXR": 11.4,
        "time_start": "2026-05-06T14:15:00+02:00",
        "time_end":   "2026-05-06T14:30:00+02:00",
    },
]


def test_parse_slots_returns_two_slots():
    slots = build.parse_slots(SAMPLE_PAYLOAD)
    assert len(slots) == 2


def test_parse_slots_extracts_sek_per_kwh():
    slots = build.parse_slots(SAMPLE_PAYLOAD)
    assert slots[0].sek_per_kwh == 0.80
    assert slots[1].sek_per_kwh == 0.76


def test_parse_slots_parses_tz_aware_datetimes():
    slots = build.parse_slots(SAMPLE_PAYLOAD)
    assert slots[0].time_start.tzinfo is not None
    assert slots[0].time_start == datetime(
        2026, 5, 6, 14, 0, 0, tzinfo=timezone(timedelta(hours=2))
    )
    assert slots[0].time_end == datetime(
        2026, 5, 6, 14, 15, 0, tzinfo=timezone(timedelta(hours=2))
    )


def test_parse_slots_empty_input_returns_empty_list():
    assert build.parse_slots([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build.py -k parse_slots
```

Expected: 4 failures, all `AttributeError: module 'build' has no attribute 'parse_slots'`.

- [ ] **Step 3: Implement `Slot` and `parse_slots` in `build.py`**

Append after the docstring:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build.py -k parse_slots
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add Slot dataclass and parse_slots"
```

---

## Task 3: `now_slot` lookup

**What:** Given a list of slots and a "now" datetime, return the slot satisfying `time_start <= now < time_end`, or `None`.

**Files:**
- Modify: `build.py`
- Modify: `tests/test_build.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
TZ_PLUS_2 = timezone(timedelta(hours=2))


def _slots_at_15min(start: datetime, count: int, prices: list[float]) -> list[build.Slot]:
    """Helper: build `count` consecutive 15-min slots from `start`, with given prices."""
    assert len(prices) == count
    return [
        build.Slot(
            time_start=start + timedelta(minutes=15 * i),
            time_end=start + timedelta(minutes=15 * (i + 1)),
            sek_per_kwh=prices[i],
        )
        for i in range(count)
    ]


def test_now_slot_finds_slot_inside_interval():
    slots = _slots_at_15min(
        datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2), 2, [0.80, 0.76],
    )
    now = datetime(2026, 5, 6, 14, 7, tzinfo=TZ_PLUS_2)
    assert build.now_slot(slots, now) is slots[0]


def test_now_slot_includes_lower_bound():
    slots = _slots_at_15min(
        datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2), 2, [0.80, 0.76],
    )
    now = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    assert build.now_slot(slots, now) is slots[0]


def test_now_slot_excludes_upper_bound():
    """At exactly time_end, we are in the next slot, not this one."""
    slots = _slots_at_15min(
        datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2), 2, [0.80, 0.76],
    )
    now = datetime(2026, 5, 6, 14, 15, tzinfo=TZ_PLUS_2)
    assert build.now_slot(slots, now) is slots[1]


def test_now_slot_returns_none_when_outside_all_slots():
    slots = _slots_at_15min(
        datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2), 2, [0.80, 0.76],
    )
    before = datetime(2026, 5, 6, 13, 59, tzinfo=TZ_PLUS_2)
    after = datetime(2026, 5, 6, 14, 30, tzinfo=TZ_PLUS_2)
    assert build.now_slot(slots, before) is None
    assert build.now_slot(slots, after) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build.py -k now_slot
```

Expected: 4 failures, `AttributeError: module 'build' has no attribute 'now_slot'`.

- [ ] **Step 3: Implement `now_slot`**

Append to `build.py`:

```python
def now_slot(slots: list[Slot], now: datetime) -> Slot | None:
    """Return the slot that contains `now`, or None if `now` is outside all slots.

    A slot contains `now` iff ``time_start <= now < time_end`` (inclusive lower,
    exclusive upper). Slots must be timezone-aware; comparison preserves offsets.
    """
    for slot in slots:
        if slot.time_start <= now < slot.time_end:
            return slot
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build.py -k now_slot
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add now_slot lookup with inclusive-start, exclusive-end semantics"
```

---

## Task 4: `slice_window` — last 6h .. next 18h

**What:** Given slots, "now", and window bounds (default `hours_back=6`, `hours_forward=18`), return slots whose interval `[time_start, time_end)` overlaps the window. Crucially, this also covers DST-day correctness because we filter by absolute timestamps, never by slot index.

**Files:**
- Modify: `build.py`
- Modify: `tests/test_build.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
def test_slice_window_keeps_only_slots_intersecting_window():
    # 100 slots covering 25h, starting 12h before "now"
    base = datetime(2026, 5, 6, 2, 0, tzinfo=TZ_PLUS_2)
    slots = _slots_at_15min(base, 100, [0.50] * 100)
    now = base + timedelta(hours=12)  # 14:00
    window = build.slice_window(slots, now)  # default 6h back, 18h forward
    # Window: [08:00, 32:00 next day) intersect dataset [02:00, 27:00)
    # Expect first slot starts at or after 07:45 (slot containing 08:00 starts at 07:45),
    # and last slot ends at or before 32:00 (which is past dataset end).
    assert window[0].time_start <= now - timedelta(hours=6)
    assert window[0].time_end > now - timedelta(hours=6)
    # Last kept slot is the dataset's last (we ran out before +18h)
    assert window[-1] is slots[-1]


def test_slice_window_excludes_slots_strictly_before_or_after():
    base = datetime(2026, 5, 6, 0, 0, tzinfo=TZ_PLUS_2)
    slots = _slots_at_15min(base, 96, [0.50] * 96)  # full day
    now = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    window = build.slice_window(slots, now)
    # Slots fully before 08:00 are excluded; fully after 32:00 (none today) excluded.
    for s in window:
        assert s.time_end > now - timedelta(hours=6)
        assert s.time_start < now + timedelta(hours=18)


def test_slice_window_dst_spring_forward_day_yields_92_slots():
    """Last Sunday of March: 02:00 -> 03:00 (skipped). API returns 92 slots."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Stockholm")
    # Build 92 actual UTC-anchored slots reflecting the gap at 01:00-02:00 UTC
    # (which is local 02:00 -> local 03:00 jump).
    slots = []
    cursor = datetime(2026, 3, 29, 0, 0, tzinfo=tz)
    end_of_day = datetime(2026, 3, 30, 0, 0, tzinfo=tz)
    while cursor < end_of_day:
        nxt = cursor + timedelta(minutes=15)
        slots.append(build.Slot(time_start=cursor, time_end=nxt, sek_per_kwh=0.50))
        cursor = nxt
    assert len(slots) == 92, f"Expected 92 slots on spring-forward day, got {len(slots)}"
    now = datetime(2026, 3, 29, 14, 0, tzinfo=tz)
    window = build.slice_window(slots, now)
    # All kept slots must fall within [now-6h, now+18h) by absolute timestamp,
    # regardless of DST jump.
    for s in window:
        assert s.time_end > now - timedelta(hours=6)
        assert s.time_start < now + timedelta(hours=18)


def test_slice_window_custom_bounds():
    base = datetime(2026, 5, 6, 0, 0, tzinfo=TZ_PLUS_2)
    slots = _slots_at_15min(base, 96, [0.50] * 96)
    now = datetime(2026, 5, 6, 12, 0, tzinfo=TZ_PLUS_2)
    window = build.slice_window(slots, now, hours_back=1, hours_forward=2)
    # Window: [11:00, 14:00) -> 12 slots
    assert len(window) == 12
    assert window[0].time_start == datetime(2026, 5, 6, 11, 0, tzinfo=TZ_PLUS_2)
    assert window[-1].time_end == datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build.py -k slice_window
```

Expected: 4 failures with `AttributeError: ... no attribute 'slice_window'`.

- [ ] **Step 3: Add the `timedelta` import and implement `slice_window`**

In `build.py`, replace the `from datetime import datetime` import with:

```python
from datetime import datetime, timedelta
```

Then append:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build.py -k slice_window
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add slice_window with DST-correct timestamp filtering"
```

---

## Task 5: `cheapest_upcoming`

**What:** Find the cheapest slot strictly after `now`. Tie-break by earliest `time_start`.

**Files:**
- Modify: `build.py`
- Modify: `tests/test_build.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
def test_cheapest_upcoming_returns_minimum_strictly_after_now():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    slots = _slots_at_15min(base, 4, [0.50, 0.30, 0.20, 0.40])
    now = base + timedelta(minutes=7)  # inside slot 0
    cheapest = build.cheapest_upcoming(slots, now)
    assert cheapest is slots[2]  # 0.20 at 14:30


def test_cheapest_upcoming_excludes_current_slot_even_if_cheapest():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    slots = _slots_at_15min(base, 3, [0.10, 0.30, 0.40])
    now = base + timedelta(minutes=7)  # inside slot 0 (the 0.10 one)
    cheapest = build.cheapest_upcoming(slots, now)
    assert cheapest is slots[1]  # 0.30 — slot 0 is "now", not "upcoming"


def test_cheapest_upcoming_tie_breaks_by_earliest_time():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    slots = _slots_at_15min(base, 4, [0.50, 0.20, 0.40, 0.20])
    now = base - timedelta(minutes=5)
    cheapest = build.cheapest_upcoming(slots, now)
    assert cheapest is slots[1]  # earlier of the two 0.20s


def test_cheapest_upcoming_returns_none_when_no_future_slots():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    slots = _slots_at_15min(base, 2, [0.50, 0.30])
    now = base + timedelta(hours=10)
    assert build.cheapest_upcoming(slots, now) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build.py -k cheapest_upcoming
```

Expected: 4 failures with `AttributeError`.

- [ ] **Step 3: Implement `cheapest_upcoming`**

Append to `build.py`:

```python
def cheapest_upcoming(slots: list[Slot], now: datetime) -> Slot | None:
    """Return the cheapest slot whose ``time_start > now``, or None if no such slot.

    Ties on price are broken by earliest ``time_start``.
    """
    upcoming = [s for s in slots if s.time_start > now]
    if not upcoming:
        return None
    return min(upcoming, key=lambda s: (s.sek_per_kwh, s.time_start))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build.py -k cheapest_upcoming
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add cheapest_upcoming with strict-future and earliest-tie-break"
```

---

## Task 6: `window_average`

**What:** Arithmetic mean of `sek_per_kwh` across the slots passed in. Empty list returns 0.0. Negative prices average normally.

**Files:**
- Modify: `build.py`
- Modify: `tests/test_build.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
def test_window_average_simple():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    slots = _slots_at_15min(base, 4, [0.20, 0.40, 0.60, 0.80])
    assert build.window_average(slots) == 0.50


def test_window_average_empty_list_returns_zero():
    assert build.window_average([]) == 0.0


def test_window_average_with_negative_prices():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    slots = _slots_at_15min(base, 3, [-0.10, 0.20, 0.50])
    assert build.window_average(slots) == pytest.approx(0.20)
```

Add to imports at the top of `tests/test_build.py`:

```python
import pytest
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build.py -k window_average
```

Expected: 3 failures with `AttributeError`.

- [ ] **Step 3: Implement `window_average`**

Append to `build.py`:

```python
def window_average(slots: list[Slot]) -> float:
    """Arithmetic mean of ``sek_per_kwh`` across the given slots. Empty -> 0.0."""
    if not slots:
        return 0.0
    return sum(s.sek_per_kwh for s in slots) / len(slots)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build.py -k window_average
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add window_average"
```

---

## Task 7: `fetch_day` — single-day HTTP fetch with retry

**What:** Issue one `GET https://www.elprisetjustnu.se/api/v1/prices/<YYYY>/<MM-DD>_SE4.json` with a 10-second timeout. Retry once after a 5-second sleep on transient failures (connection error, 5xx). Return parsed JSON on 200, `None` on 404, raise on persistent failure.

We inject `urlopen` and `sleep` so tests don't hit the network or really wait.

**Files:**
- Modify: `build.py`
- Modify: `tests/test_build.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
import io
import json as _json
from urllib.error import HTTPError, URLError
from datetime import date as _date


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return _json.dumps(self._payload).encode("utf-8")


def _fake_urlopen_returning(payload):
    """Return a urlopen stand-in that always serves the given payload."""
    def _open(url, timeout=None):
        return _FakeResponse(payload)
    return _open


def test_fetch_day_returns_parsed_payload_on_200():
    payload = [{"SEK_per_kWh": 0.5, "EUR_per_kWh": 0.044, "EXR": 11.4,
                "time_start": "2026-05-06T00:00:00+02:00",
                "time_end":   "2026-05-06T00:15:00+02:00"}]

    captured = {}
    def opener(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse(payload)

    result = build.fetch_day(_date(2026, 5, 6), urlopen=opener, sleep=lambda _: None)
    assert result == payload
    assert captured["url"] == (
        "https://www.elprisetjustnu.se/api/v1/prices/2026/05-06_SE4.json"
    )
    assert captured["timeout"] == 10


def test_fetch_day_returns_none_on_404():
    def opener(url, timeout=None):
        raise HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
    assert build.fetch_day(_date(2026, 5, 6), urlopen=opener, sleep=lambda _: None) is None


def test_fetch_day_retries_once_on_500_then_succeeds():
    payload = [{"SEK_per_kWh": 0.5, "EUR_per_kWh": 0.044, "EXR": 11.4,
                "time_start": "2026-05-06T00:00:00+02:00",
                "time_end":   "2026-05-06T00:15:00+02:00"}]
    calls = {"n": 0}

    def opener(url, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise HTTPError(url, 503, "Service Unavailable", hdrs=None, fp=None)
        return _FakeResponse(payload)

    sleeps = []
    result = build.fetch_day(_date(2026, 5, 6), urlopen=opener, sleep=sleeps.append)
    assert result == payload
    assert calls["n"] == 2
    assert sleeps == [5]


def test_fetch_day_raises_after_retry_still_failing():
    def opener(url, timeout=None):
        raise URLError("connection refused")

    with pytest.raises(URLError):
        build.fetch_day(_date(2026, 5, 6), urlopen=opener, sleep=lambda _: None)


def test_fetch_day_raises_immediately_on_4xx_other_than_404():
    def opener(url, timeout=None):
        raise HTTPError(url, 400, "Bad Request", hdrs=None, fp=None)

    with pytest.raises(HTTPError):
        build.fetch_day(_date(2026, 5, 6), urlopen=opener, sleep=lambda _: None)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build.py -k fetch_day
```

Expected: 5 failures with `AttributeError: ... 'fetch_day'`.

- [ ] **Step 3: Implement `fetch_day`**

Add imports near the top of `build.py`:

```python
import json
import time
import urllib.error
import urllib.request
from datetime import date
```

Append to `build.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build.py -k fetch_day
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add fetch_day with 10s timeout, single retry, and 404 tolerance"
```

---

## Task 8: `fetch_dataset` — yesterday/today/tomorrow

**What:** Compose `fetch_day` to retrieve up to three days. Today is required (errors propagate). Yesterday and tomorrow are best-effort (None / errors are swallowed). Return a flat list of `Slot`s in chronological order.

**Files:**
- Modify: `build.py`
- Modify: `tests/test_build.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
def _payload_at(start_iso: str, n: int) -> list[dict]:
    """Build n consecutive 15-min slots starting at ISO timestamp, all priced 0.5."""
    base = datetime.fromisoformat(start_iso)
    out = []
    for i in range(n):
        s = base + timedelta(minutes=15 * i)
        e = base + timedelta(minutes=15 * (i + 1))
        out.append({
            "SEK_per_kWh": 0.5,
            "EUR_per_kWh": 0.044,
            "EXR": 11.4,
            "time_start": s.isoformat(),
            "time_end": e.isoformat(),
        })
    return out


def test_fetch_dataset_returns_yesterday_today_tomorrow_slots():
    yesterday_payload = _payload_at("2026-05-05T00:00:00+02:00", 96)
    today_payload     = _payload_at("2026-05-06T00:00:00+02:00", 96)
    tomorrow_payload  = _payload_at("2026-05-07T00:00:00+02:00", 96)

    calls: list[_date] = []
    def fake_fetch(d):
        calls.append(d)
        return {
            _date(2026, 5, 5): yesterday_payload,
            _date(2026, 5, 6): today_payload,
            _date(2026, 5, 7): tomorrow_payload,
        }[d]

    now = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    slots = build.fetch_dataset(now, fetch=fake_fetch)
    assert len(slots) == 96 * 3
    assert calls == [_date(2026, 5, 5), _date(2026, 5, 6), _date(2026, 5, 7)]


def test_fetch_dataset_tolerates_missing_yesterday():
    today_payload = _payload_at("2026-05-06T00:00:00+02:00", 96)

    def fake_fetch(d):
        if d == _date(2026, 5, 5):
            return None
        if d == _date(2026, 5, 6):
            return today_payload
        return None  # tomorrow not yet available

    now = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    slots = build.fetch_dataset(now, fetch=fake_fetch)
    assert len(slots) == 96


def test_fetch_dataset_propagates_failure_on_today():
    def fake_fetch(d):
        if d == _date(2026, 5, 6):
            raise URLError("blew up")
        return None

    now = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    with pytest.raises(RuntimeError, match="today"):
        build.fetch_dataset(now, fetch=fake_fetch)


def test_fetch_dataset_swallows_failure_on_tomorrow():
    today_payload = _payload_at("2026-05-06T00:00:00+02:00", 96)

    def fake_fetch(d):
        if d == _date(2026, 5, 6):
            return today_payload
        if d == _date(2026, 5, 7):
            raise URLError("not yet")
        return None  # yesterday missing too

    now = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    slots = build.fetch_dataset(now, fetch=fake_fetch)
    assert len(slots) == 96


def test_fetch_dataset_uses_stockholm_local_date_for_url():
    """At UTC midnight, Stockholm is already the next day — URL should reflect that."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Stockholm")
    # 23:30 UTC on 2026-05-06 == 01:30 CEST on 2026-05-07
    now = datetime(2026, 5, 7, 1, 30, tzinfo=tz)
    requested = []
    def fake_fetch(d):
        requested.append(d)
        return _payload_at("2026-05-07T00:00:00+02:00", 4) if d == _date(2026, 5, 7) else None
    build.fetch_dataset(now, fetch=fake_fetch)
    # today must be 2026-05-07 (Stockholm local), not 2026-05-06 (UTC)
    assert _date(2026, 5, 7) in requested
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build.py -k fetch_dataset
```

Expected: 5 failures with `AttributeError`.

- [ ] **Step 3: Implement `fetch_dataset`**

Append to `build.py`:

```python
def fetch_dataset(now: datetime, *, fetch=None) -> list[Slot]:
    """Fetch yesterday, today, and tomorrow's slots and return them as a flat list.

    "Today" is whichever date `now` falls in *in its own timezone* (the caller
    is expected to pass a Stockholm-local datetime). Today is required — any
    error fetching it surfaces as ``RuntimeError``. Yesterday and tomorrow are
    best-effort: missing data (``None``) and exceptions are swallowed.
    """
    if fetch is None:
        fetch = fetch_day

    today = now.date()
    days = [
        ("yesterday", today - timedelta(days=1), False),
        ("today",     today,                     True),
        ("tomorrow",  today + timedelta(days=1), False),
    ]

    slots: list[Slot] = []
    for label, day, required in days:
        try:
            payload = fetch(day)
        except Exception as e:
            if required:
                raise RuntimeError(f"Failed to fetch {label} ({day}): {e}") from e
            payload = None
        if payload is None:
            if required:
                raise RuntimeError(f"Required data for {label} ({day}) unavailable (404)")
            continue
        slots.extend(parse_slots(payload))
    return slots
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build.py -k fetch_dataset
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add fetch_dataset (yesterday/today/tomorrow) with required-today semantics"
```

---

## Task 9: `render` — full HTML/SVG output

**What:** Produce the complete `<!DOCTYPE html>...</html>` string for the v3 visual. Inline CSS, inline SVG, no external assets, no JS for data, `<meta http-equiv="refresh" content="3600">`.

This is the largest single task in the plan (~120 lines of f-string template). We test invariants only — per the spec, no snapshot tests; the published Kindle page is the source of truth for visuals.

**Files:**
- Modify: `build.py`
- Modify: `tests/test_build.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
def _typical_dataset(now: datetime) -> list[build.Slot]:
    """Build a 24h dataset of varying prices around `now` for render tests."""
    base = (now - timedelta(hours=6)).replace(minute=0, second=0, microsecond=0)
    # 96 slots covering 24h; sinusoidal-ish prices so min/max differ
    import math
    prices = [0.50 + 0.50 * math.sin(i / 96 * 2 * math.pi) for i in range(96)]
    return _slots_at_15min(base, 96, prices)


def test_render_emits_valid_html5_document():
    now = datetime(2026, 5, 6, 14, 2, tzinfo=TZ_PLUS_2)
    slots = _typical_dataset(now)
    html = build.render(slots, now)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert '<html lang="sv"' in html


def test_render_includes_hourly_auto_refresh_meta():
    now = datetime(2026, 5, 6, 14, 2, tzinfo=TZ_PLUS_2)
    html = build.render(_typical_dataset(now), now)
    assert '<meta http-equiv="refresh" content="3600">' in html


def test_render_shows_uppdaterad_with_now_local_time():
    now = datetime(2026, 5, 6, 14, 2, tzinfo=TZ_PLUS_2)
    html = build.render(_typical_dataset(now), now)
    assert "Uppdaterad" in html
    assert "14:02" in html


def test_render_shows_just_nu_label_and_current_price():
    now = datetime(2026, 5, 6, 14, 2, tzinfo=TZ_PLUS_2)
    slots = _typical_dataset(now)
    html = build.render(slots, now)
    assert "JUST NU" in html
    current = build.now_slot(slots, now)
    assert current is not None
    expected_ore = round(current.sek_per_kwh * 100)
    # The price appears as a standalone token (the big number); use a
    # surrounding-context check instead of `str(expected_ore) in html`,
    # which could match adjacent values.
    import re
    assert re.search(rf">\s*{expected_ore}\s*<", html), html


def test_render_shows_either_vanta_or_billigast_just_nu_in_footer():
    now = datetime(2026, 5, 6, 14, 2, tzinfo=TZ_PLUS_2)
    html = build.render(_typical_dataset(now), now)
    assert ("Vänta till kl" in html) or ("Billigast just nu" in html)


def test_render_shows_24h_average_in_footer():
    now = datetime(2026, 5, 6, 14, 2, tzinfo=TZ_PLUS_2)
    html = build.render(_typical_dataset(now), now)
    assert "Snitt 24h" in html


def test_render_swedish_weekday_and_month_names():
    # 2026-05-06 is a Wednesday in Swedish: "Onsdag 6 maj"
    now = datetime(2026, 5, 6, 14, 2, tzinfo=TZ_PLUS_2)
    html = build.render(_typical_dataset(now), now)
    assert "Onsdag" in html
    assert "6 maj" in html


def test_render_contains_inline_svg_chart_with_nu_marker():
    now = datetime(2026, 5, 6, 14, 2, tzinfo=TZ_PLUS_2)
    html = build.render(_typical_dataset(now), now)
    assert "<svg" in html
    # NU marker label is rendered as text node next to the dot:
    assert "NU · " in html


def test_render_no_external_assets_or_scripts():
    now = datetime(2026, 5, 6, 14, 2, tzinfo=TZ_PLUS_2)
    html = build.render(_typical_dataset(now), now)
    # Self-contained: no <link rel="stylesheet">, no <script src=...>, no <img>
    assert "<link " not in html
    assert "<script" not in html
    assert "<img" not in html


def test_render_handles_negative_prices_in_window():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    base = now - timedelta(hours=6)
    prices = [-0.10] * 24 + [0.20] * 72  # negative early, positive later
    slots = _slots_at_15min(base, 96, prices)
    html = build.render(slots, now)
    # Just verify it renders without raising and includes a "now" price.
    assert "JUST NU" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build.py -k render
```

Expected: 10 failures with `AttributeError: ... 'render'`.

- [ ] **Step 3: Implement `render`**

Add to imports at the top of `build.py`:

```python
from zoneinfo import ZoneInfo
```

Append to `build.py`:

```python
_STOCKHOLM = ZoneInfo("Europe/Stockholm")

# Swedish day-of-week names (Monday=0)
_SV_WEEKDAYS = [
    "Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag",
]
# Swedish month names (1-indexed)
_SV_MONTHS = [
    "", "januari", "februari", "mars", "april", "maj", "juni",
    "juli", "augusti", "september", "oktober", "november", "december",
]


def _ore(sek_per_kwh: float) -> int:
    """Convert SEK/kWh to integer öre/kWh (rounded)."""
    return round(sek_per_kwh * 100)


def _format_swedish_date(dt: datetime) -> str:
    """e.g. 'Onsdag 6 maj' (no year, no leading zero)."""
    return f"{_SV_WEEKDAYS[dt.weekday()]} {dt.day} {_SV_MONTHS[dt.month]}"


def _build_chart_svg(
    window: list[Slot],
    now: datetime,
    now_x_pct: float = 25.0,
) -> str:
    """Render the inline SVG chart. Pure function — no side effects."""
    if not window:
        return '<svg viewBox="0 0 720 260" preserveAspectRatio="none"></svg>'

    win_start = window[0].time_start
    win_end = window[-1].time_end
    total_seconds = (win_end - win_start).total_seconds()

    def x_for(t: datetime) -> float:
        return ((t - win_start).total_seconds() / total_seconds) * 720.0

    prices = [s.sek_per_kwh for s in window]
    y_max = max(prices)
    y_min = min(0.0, min(prices))  # baseline includes negatives if present
    y_range = y_max - y_min if y_max > y_min else 1.0

    def y_for(price: float) -> float:
        # SVG y=20 is top, y=180 is baseline (zero)
        return 180.0 - ((price - y_min) / y_range) * 160.0

    # Build the filled area path: step shape across slots, closed at baseline.
    parts: list[str] = [f"M {x_for(window[0].time_start):.2f},{y_for(y_min):.2f}"]
    for s in window:
        x0 = x_for(s.time_start)
        x1 = x_for(s.time_end)
        y = y_for(s.sek_per_kwh)
        parts.append(f"L {x0:.2f},{y:.2f} L {x1:.2f},{y:.2f}")
    baseline_y = y_for(y_min)
    parts.append(f"L {x_for(window[-1].time_end):.2f},{baseline_y:.2f}")
    parts.append(f"L {x_for(window[0].time_start):.2f},{baseline_y:.2f} Z")
    path_d = " ".join(parts)

    current = now_slot(window, now) or window[0]
    nu_x = x_for(now)
    nu_y = y_for(current.sek_per_kwh)
    nu_ore = _ore(current.sek_per_kwh)

    cheapest = cheapest_upcoming(window, now)
    cheapest_marker = ""
    if cheapest is not None:
        cx = x_for(cheapest.time_start + (cheapest.time_end - cheapest.time_start) / 2)
        cy = y_for(cheapest.sek_per_kwh)
        kl = cheapest.time_start.astimezone(_STOCKHOLM).strftime("%H")
        cheapest_marker = (
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="4" fill="#000"/>'
            f'<text x="{cx:.2f}" y="{cy - 8:.2f}" font-size="11" font-weight="700" '
            f'text-anchor="middle">↑ billigast {_ore(cheapest.sek_per_kwh)} öre (kl {kl})</text>'
        )

    # X-axis ticks every 6h, anchored to NU
    tick_lines: list[str] = []
    for offset_h in (-6, 0, 6, 12, 18):
        t = now + timedelta(hours=offset_h)
        if not (win_start <= t <= win_end):
            continue
        tx = x_for(t)
        local = t.astimezone(_STOCKHOLM)
        label = local.strftime("%H")
        if offset_h == 0:
            tick_lines.append(
                f'<text x="{tx:.2f}" y="200" font-size="11" font-weight="700" '
                f'text-anchor="middle">{label} (NU)</text>'
            )
        else:
            tick_lines.append(
                f'<text x="{tx:.2f}" y="200" font-size="11" '
                f'text-anchor="middle">{label}</text>'
            )

    return f"""<svg viewBox="0 0 720 260" preserveAspectRatio="none" aria-hidden="true">
  <path d="{path_d}" fill="#cfcfcf" stroke="#000" stroke-width="1.5" stroke-linejoin="miter"/>
  <line x1="{nu_x:.2f}" y1="20" x2="{nu_x:.2f}" y2="180" stroke="#000" stroke-width="1" stroke-dasharray="2 3"/>
  <circle cx="{nu_x:.2f}" cy="{nu_y:.2f}" r="7" fill="#000"/>
  <text x="{nu_x + 10:.2f}" y="{nu_y - 4:.2f}" font-size="15" font-weight="700">NU · {nu_ore}</text>
  {cheapest_marker}
  <line x1="0" y1="180" x2="720" y2="180" stroke="#000" stroke-width="1.5"/>
  <text x="2" y="28" font-size="10">{_ore(y_max)}</text>
  <text x="2" y="180" font-size="10">{_ore(y_min)}</text>
  {''.join(tick_lines)}
  <text x="{(nu_x / 2):.2f}" y="220" font-size="10" letter-spacing="1.5" text-anchor="middle">SENASTE 6 H</text>
  <text x="{(nu_x + (720 - nu_x) / 2):.2f}" y="220" font-size="10" letter-spacing="1.5" text-anchor="middle">KOMMANDE 18 H</text>
</svg>"""


def render(slots: list[Slot], now: datetime) -> str:
    """Render the complete HTML page as a string.

    `slots` is the full multi-day dataset; this function slices the display
    window itself. `now` should be timezone-aware; for display, it's converted
    to Europe/Stockholm.
    """
    now_local = now.astimezone(_STOCKHOLM)
    window = slice_window(slots, now)

    current = now_slot(window, now)
    nu_ore = _ore(current.sek_per_kwh) if current else 0

    cheapest = cheapest_upcoming(window, now)
    avg = _ore(window_average(window))

    if cheapest is None:
        footer_left = "Inga kommande priser"
    elif current is not None and cheapest.sek_per_kwh >= current.sek_per_kwh:
        footer_left = "Billigast just nu"
    else:
        kl = cheapest.time_start.astimezone(_STOCKHOLM).strftime("%H")
        footer_left = (
            f"<b>Vänta till kl {kl}</b> för billigaste pris "
            f"({_ore(cheapest.sek_per_kwh)} öre/kWh)"
        )

    chart_svg = _build_chart_svg(window, now)

    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="3600">
<title>El SE4</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #fff; color: #000;
                font-family: Georgia, "Times New Roman", serif; }}
  .page {{ max-width: 760px; margin: 0 auto; padding: 22px 22px 16px; }}
  .top {{ display: flex; justify-content: space-between; align-items: flex-end;
          border-bottom: 1px solid #000; padding-bottom: 10px; margin-bottom: 16px; }}
  .now-big {{ font-size: 52px; font-weight: 800; line-height: 1; }}
  .now-big small {{ font-size: 16px; font-weight: 600; letter-spacing: 1.5px;
                    display: block; margin-bottom: 4px; }}
  .now-big .unit {{ font-size: 20px; font-weight: 600; }}
  .meta {{ text-align: right; font-size: 14px; line-height: 1.5; }}
  .meta b {{ font-size: 18px; }}
  svg {{ display: block; width: 100%; height: auto; }}
  .foot {{ display: flex; justify-content: space-between; font-size: 13px;
           margin-top: 12px; padding-top: 8px; border-top: 1px solid #000; }}
</style>
</head>
<body>
<div class="page">
  <div class="top">
    <div class="now-big"><small>JUST NU</small>{nu_ore} <span class="unit">öre/kWh</span></div>
    <div class="meta">Uppdaterad <b>{now_local.strftime('%H:%M')}</b><br>{_format_swedish_date(now_local)}</div>
  </div>
  {chart_svg}
  <div class="foot">
    <span>{footer_left}</span>
    <span>Snitt 24h: {avg} öre</span>
  </div>
</div>
</body>
</html>"""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build.py -k render
```

Expected: 10 passed.

- [ ] **Step 5: Run the full suite to make sure nothing regressed**

```bash
pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add render(): full HTML+SVG page with v3 visual locked"
```

---

## Task 10: `main()` CLI entry

**What:** Argparse-based entry. Defaults: `--output index.html`, `--now` defaults to "now in Europe/Stockholm". Compose `fetch_dataset` + `render`, write to disk. Tested by injecting a fake `fetch`.

**Files:**
- Modify: `build.py`
- Modify: `tests/test_build.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
from pathlib import Path


def test_main_writes_html_to_output(tmp_path, monkeypatch):
    today_payload = _payload_at("2026-05-06T00:00:00+02:00", 96)
    yesterday_payload = _payload_at("2026-05-05T00:00:00+02:00", 96)
    tomorrow_payload = _payload_at("2026-05-07T00:00:00+02:00", 96)

    def fake_fetch(d):
        if d == _date(2026, 5, 5): return yesterday_payload
        if d == _date(2026, 5, 6): return today_payload
        if d == _date(2026, 5, 7): return tomorrow_payload
        return None

    monkeypatch.setattr(build, "fetch_day", fake_fetch)

    out = tmp_path / "index.html"
    rc = build.main([
        "--output", str(out),
        "--now", "2026-05-06T14:02:00+02:00",
    ])
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    assert "Uppdaterad" in text
    assert "14:02" in text


def test_main_creates_parent_directories(tmp_path, monkeypatch):
    today_payload = _payload_at("2026-05-06T00:00:00+02:00", 96)
    monkeypatch.setattr(build, "fetch_day",
                        lambda d: today_payload if d == _date(2026, 5, 6) else None)
    out = tmp_path / "_site" / "index.html"
    rc = build.main([
        "--output", str(out),
        "--now", "2026-05-06T14:02:00+02:00",
    ])
    assert rc == 0
    assert out.exists()


def test_main_propagates_required_today_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "fetch_day", lambda d: None)  # 404 for everything
    with pytest.raises(RuntimeError):
        build.main([
            "--output", str(tmp_path / "index.html"),
            "--now", "2026-05-06T14:02:00+02:00",
        ])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build.py -k main
```

Expected: 3 failures with `AttributeError`.

- [ ] **Step 3: Implement `main()`**

Add to imports at the top of `build.py`:

```python
import argparse
import sys
from pathlib import Path
```

Append to `build.py`:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the SE4 spot-price page to a static HTML file.",
    )
    parser.add_argument("--output", default="index.html",
                        help="Destination HTML path (default: index.html)")
    parser.add_argument("--now", default=None,
                        help="ISO-8601 timestamp to render for "
                             "(default: current time in Europe/Stockholm)")
    args = parser.parse_args(argv)

    if args.now is None:
        now = datetime.now(_STOCKHOLM)
    else:
        parsed = datetime.fromisoformat(args.now)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_STOCKHOLM)
        now = parsed.astimezone(_STOCKHOLM)

    slots = fetch_dataset(now)
    html = render(slots, now)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build.py -k main
```

Expected: 3 passed.

- [ ] **Step 5: Run the full suite**

```bash
pytest
```

Expected: all green.

- [ ] **Step 6: End-to-end smoke (manual)**

Run the build against the live API for today:

```bash
python build.py --output _site/index.html
ls -la _site/
open _site/index.html  # macOS; on Linux use xdg-open
```

Expected: a static `index.html` opens in the browser showing today's SE4 prices. If the API is down or returns unexpected JSON shape, this is the moment to find out — adjust `parse_slots` field mapping if the live API field names have changed (note: the API has been stable since 2022).

- [ ] **Step 7: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add main() CLI: argparse, fetch_dataset, render, write file"
```

---

## Task 11: `test.yml` workflow — pytest on push and PR

**What:** Run pytest on every push to `main` and every pull request. This guards against regressions independently of the publish cadence.

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Create `.github/workflows/test.yml`**

```yaml
name: test
on:
  push:
    branches: [main]
  pull_request:
jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install pytest
        run: pip install -e .[dev]
      - name: Run pytest
        run: pytest
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "Add test workflow: pytest on push and PR"
```

- [ ] **Step 3: Push and verify**

```bash
git push
```

Then visit `https://github.com/ottotheotto/laundrytime/actions` and confirm the `test` workflow ran and passed on the new commit.

---

## Task 12: `publish.yml` workflow — hourly cron + Pages deploy

**What:** Hourly build that fetches data, runs tests, generates `_site/index.html`, and deploys via the official Pages artifact action. No commits to any branch — Pages serves the artifact directly.

**Files:**
- Create: `.github/workflows/publish.yml`

- [ ] **Step 1: Create `.github/workflows/publish.yml`**

```yaml
name: publish
on:
  schedule:
    - cron: "2 * * * *"
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install pytest
        run: pip install -e .[dev]
      - name: Run tests
        run: pytest
      - name: Build site
        run: python build.py --output _site/index.html
      - uses: actions/upload-pages-artifact@v3
        with:
          path: _site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/publish.yml
git commit -m "Add publish workflow: hourly cron + Pages artifact deploy"
git push
```

- [ ] **Step 3: Enable GitHub Pages with "GitHub Actions" as source**

In the GitHub web UI:
1. Open `https://github.com/ottotheotto/laundrytime/settings/pages`.
2. Under **Build and deployment → Source**, select **GitHub Actions**.
3. Save.

(This is a one-time manual step — there's no clean way to script it through the public API without an admin PAT.)

- [ ] **Step 4: Trigger the workflow manually to verify**

In the GitHub UI:
1. Open `https://github.com/ottotheotto/laundrytime/actions/workflows/publish.yml`.
2. Click **Run workflow** → **Run workflow**.
3. Wait for both `build` and `deploy` jobs to go green.
4. Visit the published URL (shown on the deploy job's summary, usually `https://ottotheotto.github.io/laundrytime/`).
5. Open it in a regular browser first; verify the chart renders and shows realistic SE4 prices.
6. Then open it on the Kindle. Confirm legibility.

---

## Task 13: README

**What:** A short README documenting how to develop locally, how to deploy, and where to find the spec.

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

Replace the published-URL placeholder once you confirm it (default GitHub Pages URL for this repo is `https://ottotheotto.github.io/laundrytime/`).

```markdown
# laundrytime

A static webpage rendering Nord Pool SE4 spot prices for a Kindle e-ink browser.
Answers "is electricity cheap right now?" at a glance — designed to help time
laundry / dishwasher / EV charging.

**Live:** https://ottotheotto.github.io/laundrytime/

**Design spec:** [`docs/superpowers/specs/2026-05-06-electro-price-design.md`](docs/superpowers/specs/2026-05-06-electro-price-design.md)

## How it works

1. A GitHub Actions cron runs `build.py` every hour.
2. `build.py` fetches yesterday/today/tomorrow's SE4 prices from
   [elprisetjustnu.se](https://www.elprisetjustnu.se/) and renders a single
   self-contained HTML page with an inline SVG chart.
3. The page is published to GitHub Pages via `actions/deploy-pages` — no
   `gh-pages` branch, no commits per build.

## Run locally

Requires Python 3.12+.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]

# Generate index.html for the current moment
python build.py --output _site/index.html

# Generate for a specific moment (useful for testing)
python build.py --output _site/index.html --now 2026-05-06T14:02:00+02:00

# Run the test suite
pytest
```

## Project layout

```
build.py                      Single-file generator (stdlib only)
tests/test_build.py           pytest unit tests
.github/workflows/test.yml    pytest on push/PR
.github/workflows/publish.yml hourly cron + Pages deploy
docs/superpowers/specs/       Approved design spec
docs/superpowers/plans/       Implementation plan
```

## License

MIT.
```

- [ ] **Step 2: Commit and push**

```bash
git add README.md
git commit -m "Add README"
git push
```

---

## Self-Review (run before handing off)

**1. Spec coverage**

| Spec section | Implemented in |
|---|---|
| Static HTML, no JS for data | Task 9 (render) |
| SE4, elprisetjustnu.se | Task 7 (fetch_day URL template) |
| 15-min granularity, iterate over API output | Tasks 2, 4 (we never assume slot count) |
| Yesterday/today/tomorrow, today required | Task 8 (fetch_dataset) |
| 10s timeout, 1 retry, 5s backoff, 404→None | Task 7 (fetch_day) |
| last 6h .. +18h rolling window | Task 4 (slice_window default args) |
| now slot definition (`time_start <= now < time_end`) | Task 3 (now_slot) |
| Cheapest upcoming, tie-break by earliest | Task 5 (cheapest_upcoming) |
| 24h average | Task 6 (window_average) |
| DST-day correctness | Task 4 (timestamp filtering, 92-slot test) |
| Negative price baseline | Task 9 (`y_min = min(0.0, ...)` in `_build_chart_svg`) |
| `<meta http-equiv="refresh" content="3600">` | Task 9 (render) |
| Inline CSS, no external assets | Task 9 (render + test invariants) |
| Swedish weekday/month, "Uppdaterad HH:MM" | Task 9 |
| "Vänta till kl HH" / "Billigast just nu" footer | Task 9 (footer logic) |
| Cron `2 * * * *`, workflow_dispatch | Task 12 (publish.yml) |
| Tests run before deploy | Task 12 (`pytest` step before build) |
| Tests on push/PR | Task 11 (test.yml) |
| Pages artifact deploy (no gh-pages branch) | Task 12 (publish.yml) |

**2. No placeholders** — verified. Every code step contains complete code; every command step shows the exact command and expected output.

**3. Type/name consistency** — verified:
- `Slot` fields: `time_start`, `time_end`, `sek_per_kwh` — used identically across all tasks.
- Function signatures stable: `slice_window(slots, now, *, hours_back=6, hours_forward=18)` keyword-only after `now` from Task 4 onward; tests in Task 4 use both positional `now` and keyword `hours_back`/`hours_forward` consistent with the implementation.
- `fetch_day(day, *, urlopen=None, sleep=time.sleep)` — `urlopen` defaults to `None` so we can override default-args by injection in tests; tests pass `urlopen=opener` consistently.
- `fetch_dataset(now, *, fetch=None)` — same pattern; tests inject via `fetch=fake_fetch`.
- `render(slots, now)` — signature stable across Tasks 9 and 10.
- `main(argv=None)` — `argv` is positional with `None` default; tests in Task 10 pass an explicit `list[str]`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-06-electro-price.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
