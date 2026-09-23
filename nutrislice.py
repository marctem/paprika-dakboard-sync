"""
Nutrislice school lunch menu client.

Calls Nutrislice's public (also unofficial -- there's no official API
either) menu API to pull the school lunch menu. No credentials needed,
just a browser-like User-Agent header, or requests get rejected.

Change NUTRISLICE_DISTRICT / NUTRISLICE_SCHOOL / NUTRISLICE_MENU_TYPE below
to point this at a different district/school: if the menu lives at
    https://<district>.nutrislice.com/menu/<school>/<menu-type>
then NUTRISLICE_DISTRICT = "<district>", NUTRISLICE_SCHOOL = "<school>",
NUTRISLICE_MENU_TYPE = "<menu-type>".
"""

import sys
from datetime import datetime, timedelta

import requests

NUTRISLICE_DISTRICT = "lakewashingtonsd"
NUTRISLICE_SCHOOL = "einstein-elementary"
NUTRISLICE_MENU_TYPE = "lunch"
NUTRISLICE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


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
