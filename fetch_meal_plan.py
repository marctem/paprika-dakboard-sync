#!/usr/bin/env python3
"""
Fetch this week's meal plan from Paprika's (unofficial) Cloud Sync API,
plus the kids' school lunch menu from Nutrislice, and write it out as
(1) a plain JSON array (Paprika data only) and (2) a fully self-contained,
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

It also calls Nutrislice's public (also unofficial) menu API to pull the
school lunch menu -- no credentials needed there, just a browser-like
User-Agent header, or requests get rejected. See NUTRISLICE_* below to
point this at a different district/school.
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

# Where the generated files get written. Defaults to the current directory
# (handy for a local test run), but the GitHub Actions workflow points this
# at a scratch build folder (`_site`) that's never committed to the repo --
# it's uploaded straight to GitHub Pages as a build artifact instead.
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", ".")

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

# The dashboard page only shows these two Paprika slots (Dinner, Lunch) -
# breakfast/snack entries, if you ever add any, are included in
# meal-plan.json but won't appear on the rendered page.
DINNER_TYPE = 2
LUNCH_TYPE = 1

# Nutrislice school lunch menu. Change these to match your own district's
# Nutrislice site: if the menu lives at
#   https://<district>.nutrislice.com/menu/<school>/<menu-type>
# then NUTRISLICE_DISTRICT = "<district>", NUTRISLICE_SCHOOL = "<school>",
# NUTRISLICE_MENU_TYPE = "<menu-type>".
NUTRISLICE_DISTRICT = "lakewashingtonsd"
NUTRISLICE_SCHOOL = "einstein-elementary"
NUTRISLICE_MENU_TYPE = "lunch"
NUTRISLICE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


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
    dinner/lunch/school-lunch columns the rendered page shows."""
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


def _nutrislice_week_start(d):
    """Nutrislice's week endpoint returns a Sunday-Saturday calendar week;
    find the Sunday that starts the week containing `d`."""
    days_since_sunday = (d.weekday() + 1) % 7  # Mon=0..Sun=6 -> Sun=0
    return d - timedelta(days=days_since_sunday)


def fetch_nutrislice_week(any_date_in_week) -> dict:
    url = (
        f"https://{NUTRISLICE_DISTRICT}.api.nutrislice.com/menu/api/weeks/school/"
        f"{NUTRISLICE_SCHOOL}/menu-type/{NUTRISLICE_MENU_TYPE}/"
        f"{any_date_in_week.year}/{any_date_in_week.month}/{any_date_in_week.day}/"
    )
    resp = requests.get(url, headers={"User-Agent": NUTRISLICE_USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _extract_entrees(day_payload: dict) -> list:
    """Pull just the bold "main course" items out of one day's Nutrislice
    menu -- everything else (sides, condiments, snacks) is ignored.
    Nutrislice marks the main courses with food_category == "entree"."""
    names = []
    for item in day_payload.get("menu_items", []):
        if item.get("is_section_title") or item.get("is_station_header") or item.get("is_holiday"):
            continue
        food = item.get("food") or {}
        category = food.get("food_category") or item.get("food_category")
        if category != "entree":
            continue
        name = food.get("name") or item.get("text")
        if name:
            names.append(name)
    return names


def get_school_lunch_days(window_start, window_end) -> dict:
    """Fetch school lunch entrees for every day in [window_start,
    window_end]. Nutrislice's API returns a full Sunday-Saturday week per
    call, and the Fri-Thu planning cycle almost always spans two such
    weeks, so this fetches each distinct week once and merges the results.
    Returns {date: [entree names]}; days with no published menu (weekends,
    holidays, no data yet) simply won't have a key, which the caller
    treats the same as an empty list. Network or schema problems are
    swallowed (with a warning to stderr) so a Nutrislice hiccup never
    takes down the Paprika half of the page."""
    entrees_by_date = {}

    week_starts_needed = set()
    d = window_start
    while d <= window_end:
        week_starts_needed.add(_nutrislice_week_start(d))
        d += timedelta(days=1)

    for week_start in sorted(week_starts_needed):
        try:
            payload = fetch_nutrislice_week(week_start)
            for day in payload.get("days", []):
                date_str = day.get("date")
                if not date_str:
                    continue
                try:
                    day_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if window_start <= day_date <= window_end:
                    entrees_by_date[day_date] = _extract_entrees(day)
        except Exception as exc:  # best-effort: never fail the whole run over this
            print(
                f"Warning: couldn't fetch school lunch menu for week of "
                f"{week_start}: {exc}",
                file=sys.stderr,
            )

    return entrees_by_date


def build_days(meals: list, today: datetime.date = None, school_lunch: dict = None) -> list:
    """Shape meals into one entry per day of the current Fri-Thu cycle,
    each with `dinner`, `lunch`, and `school_lunch` slots -- this is what
    the three-column page is built from. Every day in the cycle is
    included, even ones with no meals, so the table always shows a full
    week."""
    if today is None:
        today = datetime.now().date()
    if school_lunch is None:
        school_lunch = {}
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
                "school_lunch": school_lunch.get(d, []),
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
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="card">
  <div class="header">This week's meals</div>
  <table>
    <colgroup>
      <col class="day-col">
      <col class="dinner-col">
      <col class="lunch-col">
      <col class="school-col">
    </colgroup>
    <tr>
      <th></th>
      <th>Dinner</th>
      <th style="text-align: center;">Lunch</th>
      <th>School lunch</th>
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
      {school_cell}
    </tr>"""


def _meal_cell(value, extra_class):
    cls = f"meal {extra_class}"
    if value:
        return f'<td class="{cls}">{escape(value)}</td>'
    return f'<td class="{cls} empty">–</td>'


def _school_cell(names):
    if names:
        lines = "".join(f'<div class="sline">{escape(n)}</div>' for n in names)
        return f'<td class="meal school">{lines}</td>'
    return '<td class="meal school empty">–</td>'


def build_html(days: list, generated_at: datetime = None) -> str:
    """Render the day list as a fully self-contained, pre-rendered HTML
    page -- no client-side fetch/JS needed, since Dakboard's Website/iframe
    block just reloads this URL on whatever interval you set. Background
    is a faint green tint (95% transparent) rather than fully clear, so
    Dakboard's own wallpaper still shows through (also check the block's
    own Formatting tab in Dakboard is set to no background, since that's a
    separate layer from this page's CSS)."""
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
            dinner_cell=_meal_cell(day["dinner"], "dinner"),
            lunch_cell=_meal_cell(day["lunch"], "lunch"),
            school_cell=_school_cell(day["school_lunch"]),
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

    today = datetime.now().date()
    window_start, window_end = current_cycle_bounds(today)

    dakboard_data = build_dakboard_json(meals, today=today)
    school_lunch = get_school_lunch_days(window_start, window_end)
    days = build_days(meals, today=today, school_lunch=school_lunch)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(OUTPUT_DIR, JSON_OUTPUT_FILE)
    html_path = os.path.join(OUTPUT_DIR, HTML_OUTPUT_FILE)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dakboard_data, f, indent=2)
        f.write("\n")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_html(days))

    print(
        f"Wrote {len(dakboard_data)} meal entries to {json_path} and "
        f"{len(days)} days to {html_path}"
    )


if __name__ == "__main__":
    main()
