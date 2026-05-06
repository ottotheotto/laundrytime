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
