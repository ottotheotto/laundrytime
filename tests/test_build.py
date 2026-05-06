from datetime import datetime, timezone, timedelta
import math
import re

import pytest

import build


def test_module_imports():
    assert build.__doc__


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


def test_slice_window_dst_correctness_via_absolute_timestamps():
    """DST-correctness: filter by absolute timestamps, not slot indices."""
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


import io
import json as _json
from pathlib import Path
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


def _typical_dataset(now: datetime) -> list[build.Slot]:
    """Build a 24h dataset of varying prices around `now` for render tests."""
    base = (now - timedelta(hours=6)).replace(minute=0, second=0, microsecond=0)
    # 96 slots covering 24h; sinusoidal-ish prices so min/max differ
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


def test_render_raises_on_empty_window():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    # All slots are far in the future, outside the [now-6h, now+18h) window.
    far_future = now + timedelta(days=10)
    slots = _slots_at_15min(far_future, 4, [0.50] * 4)
    with pytest.raises(ValueError, match="No price slots"):
        build.render(slots, now)


def test_render_handles_negative_prices_in_window():
    now = datetime(2026, 5, 6, 14, 0, tzinfo=TZ_PLUS_2)
    base = now - timedelta(hours=6)
    prices = [-0.10] * 24 + [0.20] * 72  # negative early, positive later
    slots = _slots_at_15min(base, 96, prices)
    html = build.render(slots, now)
    assert "JUST NU" in html
    # The bottom y-axis label should reflect the negative minimum.
    # _ore(-0.10) == -10, which should appear as the bottom axis tick.
    assert ">-10<" in html


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
