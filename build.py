"""Electro-price: render Nord Pool SE4 spot prices for a Kindle browser."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


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
_USER_AGENT = "laundrytime/0.1 (+https://github.com/ottotheotto/laundrytime)"


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
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    last_err: Exception | None = None
    for attempt in range(2):
        try:
            with urlopen(request, timeout=10) as resp:
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

    if total_seconds == 0.0:
        return '<svg viewBox="0 0 720 260" preserveAspectRatio="none"></svg>'

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

    cheapest = cheapest_upcoming(window, now)
    cheapest_dot = ""
    if cheapest is not None:
        cx = x_for(cheapest.time_start + (cheapest.time_end - cheapest.time_start) / 2)
        cy = y_for(cheapest.sek_per_kwh)
        cheapest_dot = f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="4" fill="#000"/>'

    # X-axis ticks every 6h, anchored to NU
    tick_lines: list[str] = []
    for offset_h in (-6, 0, 6, 12, 18):
        t = now + timedelta(hours=offset_h)
        if not (win_start <= t < win_end):
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

    return f"""<svg viewBox="0 0 720 235" preserveAspectRatio="none" aria-hidden="true">
  <path d="{path_d}" fill="#cfcfcf" stroke="#000" stroke-width="1.5" stroke-linejoin="miter"/>
  <line x1="{nu_x:.2f}" y1="20" x2="{nu_x:.2f}" y2="180" stroke="#000" stroke-width="1" stroke-dasharray="2 3"/>
  <circle cx="{nu_x:.2f}" cy="{nu_y:.2f}" r="7" fill="#000"/>
  {cheapest_dot}
  <line x1="0" y1="180" x2="720" y2="180" stroke="#000" stroke-width="1.5"/>
  <text x="2" y="28" font-size="10">{_ore(y_max)}</text>
  <text x="2" y="180" font-size="10">{_ore(y_min)}</text>
  {''.join(tick_lines)}
  <text x="{(nu_x / 2):.2f}" y="220" font-size="10" letter-spacing="1.5" text-anchor="middle">SENASTE 6 H</text>
  <text x="{(nu_x + (720 - nu_x) / 2):.2f}" y="220" font-size="10" letter-spacing="1.5" text-anchor="middle">KOMMANDE 18 H</text>
</svg>"""


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


def render(slots: list[Slot], now: datetime) -> str:
    """Render the complete HTML page as a string.

    `slots` is the full multi-day dataset; this function slices the display
    window itself. `now` should be timezone-aware; for display, it's converted
    to Europe/Stockholm.
    """
    now_local = now.astimezone(_STOCKHOLM)
    window = slice_window(slots, now)

    if not window:
        raise ValueError("No price slots in display window — cannot render")

    current = now_slot(window, now)
    nu_ore = _ore(current.sek_per_kwh) if current else 0

    cheapest = cheapest_upcoming(window, now)
    avg = _ore(window_average(window))

    cheaper_ahead = (
        cheapest is not None
        and current is not None
        and cheapest.sek_per_kwh < current.sek_per_kwh
    )

    if cheapest is None:
        footer_left = "Inga kommande priser"
    elif not cheaper_ahead:
        footer_left = "Billigast just nu"
    else:
        kl = cheapest.time_start.astimezone(_STOCKHOLM).strftime("%H")
        footer_left = (
            f"<b>Vänta till kl {kl}</b> för billigaste pris "
            f"({_ore(cheapest.sek_per_kwh)} öre/kWh)"
        )

    if cheaper_ahead:
        kl = cheapest.time_start.astimezone(_STOCKHOLM).strftime("%H")
        now_sub_html = (
            f'<div class="now-sub">↑ billigast {_ore(cheapest.sek_per_kwh)} öre kl {kl}</div>'
        )
    else:
        now_sub_html = ""

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
  .now-sub {{ font-size: 13px; font-weight: 600; margin-top: 8px;
              letter-spacing: 0.3px; }}
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
    <div class="now-big"><small>JUST NU</small>{nu_ore} <span class="unit">öre/kWh</span>{now_sub_html}</div>
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
