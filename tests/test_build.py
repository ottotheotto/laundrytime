from datetime import datetime, timezone, timedelta

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
