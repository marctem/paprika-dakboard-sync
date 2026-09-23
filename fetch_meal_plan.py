#!/usr/bin/env python3
"""
Fetch this week's meal plan from Paprika's (unofficial) Cloud Sync API and
write it out as (1) a plain JSON array and (2) a fully self-contained,
pre-rendered HTML page, meant to be served via GitHub Pages and shown on
Dakboard through a Website/iframe block (rather than Dakboard's built-in
External Data/JSON block, which has limited styling and has been observed
to drop entries).

Requires two environment variables:
    PAPRIKA_EMAIL    - the email address for your Paprika Cloud Sync account
    PAPRIKA_PASSWORD - the password for that account

These are read from the environment (GitHub Actions secrets, in the
intended setup) and are never written to disk or logged.

This uses Paprika's undocumented sync API, reverse-engineered by the
community (see https://github.com/aarons22/paprika-tools). It could break
if Paprika changes their backend.
"""

import base64
import gzip
import json
import os
import sys
from datetime import datetime, timedelta
from html import escape

import requests

PAPRIKA_BASE = "https://www.paprikaapp.com/api"
JSON_OUTPUT_FILE = "meal-plan.json"
HTML_OUTPUT_FILE = "index.html"

# Your planning cadence: you build the plan Thursday night, covering Friday
# through the following Thursday. Rather than a rolling "today + 6 days"
# window (which would cut a cycle in half depending on what day the script
# happens to run), we anchor to the most recent cycle-start weekday on or
# before today, so the full Fri-Thu cycle always displays together -
# whether the script runs Friday morning or the following Wednesday night.
# Monday=0 ... Sunday=6, so Friday=4.
WEEK_ANCHOR_WEEKDAY = 4
WEEK_LENGTH_DAYS = 7

MEAL_TYPE_NAMES = {0: "Breakfast", 1: "Lunch", 2: "Dinner", 3: "Snack"}
MEAL_TYPE_ORDER = {0: 0, 1: 1, 2: 2, 3: 3}

# The dashboard page only shows these two columns (Dinner left, Lunch
# right) - breakfast/snack entries, if you ever add any, are included in
# meal-plan.json but won't appear on the rendered page.
DINNER_TYPE = 2
LUNCH_TYPE = 1


def _parse_json_response(resp: requests.Response) -> dict:
    """Paprika sometimes gzips response bodies without setting the usual
    Content-Encoding header, so check the magic bytes ourselves rather than
    relying on `requests` to have already decompressed it."""
    raw = resp.content
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def login(email: str, password: str) -> str:
    credentials = f"{email}:{password}".encode("utf-8")
    auth_header = base64.b64encode(credentials).decode("ascii")
    resp = requests.post(
        f"{PAPRIKA_BASE}/v1/account/login/",
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"email": email, "password": password},
        timeout=30,
    )
    resp.raise_for_status()
    payload = _parse_json_response(resp)
    token = payload.get("result", {}).get("token")
    if not token:
        raise RuntimeError(f"Login response did not include a token: {payload}")
    return token


def get_meals(token: str) -> list:
    resp = requests.get(
        f"{PAPRIKA_BASE}/v2/sync/meals/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    payload = _parse_json_response(resp)
    return payload.get("result", [])


def current_cycle_bounds(today: datetime.date) -> tuple:
    """Return (start, end) for the Fri-Thu cycle that contains `today`.

    This is anchored to the calendar, not to when meals were entered, so it
    stays correct no matter when during the week you add or edit meals:
    - Run it on a Friday -> that Friday through the next Thursday.
    - Run it on the Thursday night you're re-planning -> the *outgoing*
      cycle (prior Friday through today) still displays in full until the
      calendar actually rolls over to Friday, at which point the newly
      entered next cycle takes over automatically.
    """
    days_since_anchor = (today.weekday() - WEEK_ANCHOR_WEEKDAY) % 7
    start = today - timedelta(days=days_since_anchor)
    end = start + timedelta(days=WEEK_LENGTH_DAYS - 1)
    return start, end


def build_dakboard_json(meals: list, today: datetime.date = None) -> list:
    """Filter meals to the current Fri-Thu planning cycle and shape them
    into a plain {value, title, subtitle} list -- kept around as a
    general-purpose export (all meal types included), separate from the
    dinner/lunch-only columns the rendered page shows."""
    if today is None:
        today = datetime.now().date()
    window_start, window_end = current_cycle_bounds(today)

    entries = []
    for meal in meals:
        try:
            meal_date = datetime.strptime(meal["date"], "%Y-%m-%d %H:%M:%S").date()
        except (KeyError, ValueError, TypeError):
            continue
        if not (window_start <= meal_date <= window_end):
            continue

        meal_type = meal.get("type", 3)
        entries.append(
            {
                "_sort_key": (
                    meal_date,
                    MEAL_TYPE_ORDER.get(meal_type, 9),
                    meal.get("order_flag", 0),
                ),
                "value": meal.get("name") or "(untitled meal)",
                "title": "{day} · {meal_type}".format(
                    day=meal_date.strftime("%a %b %-d"),
                    meal_type=MEAL_TYPE_NAMES.get(meal_type, "Meal"),
                ),
                "subtitle": meal_date.isoformat(),
            }
        )

    entries.sort(key=lambda e: e["_sort_key"])
    for e in entries:
        del e["_sort_key"]
    return entries


def build_days(meals: list, today: datetime.date = None) -> list:
    """Shape meals into one entry per day of the current Fri-Thu cycle,
    each with a `dinner` and `lunch` slot (None if nothing's planned) --
    this is what the two-column page is built from. Every day in the
    cycle is included, even ones with no meals, so the table always shows
    a full week."""
    if today is None:
        today = datetime.now().date()
    window_start, window_end = current_cycle_bounds(today)

    by_slot = {}
    for meal in meals:
        try:
            meal_date = datetime.strptime(meal["date"], "%Y-%m-%d %H:%M:%S").date()
        except (KeyError, ValueError, TypeError):
            continue
        if not (window_start <= meal_date <= window_end):
            continue
        meal_type = meal.get("type")
        if meal_type not in (DINNER_TYPE, LUNCH_TYPE):
            continue
        key = (meal_date, meal_type)
        by_slot.setdefault(key, []).append(
            (meal.get("order_flag", 0), meal.get("name") or "(untitled meal)")
        )

    def slot_text(date_, meal_type):
        names = [name for _, name in sorted(by_slot.get((date_, meal_type), []))]
        return " / ".join(names) if names else None

    days = []
    for i in range(WEEK_LENGTH_DAYS):
        d = window_start + timedelta(days=i)
        days.append(
            {
                "date": d,
                "label": d.strftime("%a %-m/%-d"),
                "dinner": slot_text(d, DINNER_TYPE),
                "lunch": slot_text(d, LUNCH_TYPE),
                "is_today": d == today,
                "is_past": d < today,
            }
        )
    return days


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meal plan</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0;
    background-color: transparent;
    color: #f2f2f0;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  .meal, .day, .header {{
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.7);
  }}
  .card {{
    width: 500px;
    margin: 0 auto;
    padding: 14px 16px 10px;
  }}
  .header {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #8a8f98;
    margin-bottom: 8px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
  }}
  th {{
    text-align: left;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #6d7178;
    font-weight: 500;
    padding: 0 0 6px;
    border-bottom: 1px solid #2a2d31;
  }}
  th.day-col {{ width: 78px; }}
  th.meal-col {{ width: 46%; }}
  td {{
    padding: 6px 0;
    border-bottom: 1px solid #222427;
    vertical-align: top;
    font-size: 13px;
  }}
  tr:last-child td {{ border-bottom: none; }}
  td.day {{
    color: #8a8f98;
    font-size: 12px;
    padding-right: 8px;
    white-space: nowrap;
  }}
  td.meal {{
    padding-right: 10px;
    font-weight: 500;
    line-height: 1.3;
  }}
  td.meal.empty {{
    color: #4a4d52;
    font-weight: 400;
  }}
  tr.past td.day,
  tr.past td.meal {{
    color: #4d4f53;
  }}
  tr.past td.meal.empty {{
    color: #35373a;
  }}
  tr.today td {{
    background: #1f232a;
    font-weight: 700;
  }}
  tr.today td.day {{
    color: #d8dade;
    font-weight: 700;
  }}
  tr.today td.meal.empty {{
    color: #6b6e73;
    font-weight: 400;
  }}
  .footer {{
    font-size: 10px;
    color: #54585e;
    text-align: right;
    margin-top: 8px;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="header">This week's meals</div>
  <table>
    <tr>
      <th class="day-col"></th>
      <th class="meal-col">Dinner</th>
      <th class="meal-col">Lunch</th>
    </tr>
{rows}
  </table>
  <div class="footer">Updated {generated_at}</div>
</div>
</body>
</html>
"""

ROW_TEMPLATE = """    <tr{row_class}>
      <td class="day">{day}</td>
      {dinner_cell}
      {lunch_cell}
    </tr>"""


def _meal_cell(value):
    if value:
        return f'<td class="meal">{escape(value)}</td>'
    return '<td class="meal empty">–</td>'


def build_html(days: list, generated_at: datetime = None) -> str:
    """Render the day list as a fully self-contained, pre-rendered HTML
    page -- no client-side fetch/JS needed, since Dakboard's Website/iframe
    block just reloads this URL on whatever interval you set. Transparent
    background by design, so Dakboard's own wallpaper shows through (also
    check the block's own Formatting tab in Dakboard is set to no
    background, since that's a separate layer from this page's CSS)."""
    if generated_at is None:
        generated_at = datetime.now()

    rows_html = "\n".join(
        ROW_TEMPLATE.format(
            row_class=(
                ' class="{}"'.format(
                    " ".join(
                        c
                        for c, on in (("past", day["is_past"]), ("today", day["is_today"]))
                        if on
                    )
                )
                if day["is_past"] or day["is_today"]
                else ""
            ),
            day=escape(day["label"]),
            dinner_cell=_meal_cell(day["dinner"]),
            lunch_cell=_meal_cell(day["lunch"]),
        )
        for day in days
    )

    return HTML_TEMPLATE.format(
        rows=rows_html,
        generated_at=escape(generated_at.strftime("%a %b %-d, %-I:%M %p")),
    )


def main() -> None:
    email = os.environ.get("PAPRIKA_EMAIL")
    password = os.environ.get("PAPRIKA_PASSWORD")
    if not email or not password:
        print("PAPRIKA_EMAIL and PAPRIKA_PASSWORD must both be set", file=sys.stderr)
        sys.exit(1)

    token = login(email, password)
    meals = get_meals(token)
    dakboard_data = build_dakboard_json(meals)
    days = build_days(meals)

    with open(JSON_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dakboard_data, f, indent=2)
        f.write("\n")

    with open(HTML_OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(build_html(days))

    print(
        f"Wrote {len(dakboard_data)} meal entries to {JSON_OUTPUT_FILE} and "
        f"{len(days)} days to {HTML_OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
