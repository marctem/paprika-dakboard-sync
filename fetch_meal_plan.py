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
MEAL_TYPE_ICONS = {
    0: "fa-solid fa-mug-hot",
    1: "fa-solid fa-bowl-food",
    2: "fa-solid fa-utensils",
    3: "fa-solid fa-cookie-bite",
}


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
    into the {value, title, subtitle, icon} format Dakboard's External
    Data/JSON block expects."""
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
                "icon": MEAL_TYPE_ICONS.get(meal_type, "fa-solid fa-utensils"),
            }
        )

    entries.sort(key=lambda e: e["_sort_key"])
    for e in entries:
        del e["_sort_key"]
    return entries


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meal plan</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden;
    background: #15171a;
    color: #f2f2f0;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  .header {{
    font-size: clamp(10px, 1.4vw, 14px);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #8a8f98;
    padding: 3vh 3vw 1vh;
  }}
  .list {{ padding: 0 3vw 2vh; }}
  .row {{
    display: flex;
    align-items: center;
    gap: 3%;
    padding: 1.4vh 0;
    border-bottom: 1px solid #2a2d31;
  }}
  .row:last-child {{ border-bottom: none; }}
  .row i {{
    font-size: clamp(16px, 2.2vw, 26px);
    color: #e8b95f;
    width: 6%;
    text-align: center;
    flex: none;
  }}
  .text {{ min-width: 0; }}
  .title {{
    font-size: clamp(11px, 1.3vw, 15px);
    color: #8a8f98;
  }}
  .value {{
    font-size: clamp(14px, 2vw, 22px);
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .empty {{
    padding: 4vh 3vw;
    color: #8a8f98;
    font-size: clamp(12px, 1.6vw, 16px);
  }}
  .footer {{
    font-size: clamp(8px, 1vw, 11px);
    color: #54585e;
    text-align: right;
    padding: 0 3vw 2vh;
  }}
</style>
</head>
<body>
  <div class="header">This week's meals</div>
  <div class="list">
{rows}
  </div>
  <div class="footer">Updated {generated_at}</div>
</body>
</html>
"""

ROW_TEMPLATE = """    <div class="row">
      <i class="{icon}" aria-hidden="true"></i>
      <div class="text">
        <div class="title">{title}</div>
        <div class="value">{value}</div>
      </div>
    </div>"""


def build_html(entries: list, generated_at: datetime = None) -> str:
    """Render the meal entries as a fully self-contained, pre-rendered HTML
    page -- no client-side fetch/JS needed, since Dakboard's Website/iframe
    block just reloads this URL on whatever interval you set."""
    if generated_at is None:
        generated_at = datetime.now()

    if entries:
        rows_html = "\n".join(
            ROW_TEMPLATE.format(
                icon=escape(e["icon"]),
                title=escape(e["title"]),
                value=escape(e["value"]),
            )
            for e in entries
        )
    else:
        rows_html = '    <div class="empty">No meals planned for this cycle yet.</div>'

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

    with open(JSON_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dakboard_data, f, indent=2)
        f.write("\n")

    with open(HTML_OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(build_html(dakboard_data))

    print(
        f"Wrote {len(dakboard_data)} meal entries to "
        f"{JSON_OUTPUT_FILE} and {HTML_OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
