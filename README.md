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
