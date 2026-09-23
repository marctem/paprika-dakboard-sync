#!/usr/bin/env python3
"""
Fetch this week's meal plan from Paprika's (unofficial) Cloud Sync API and
write it out as a Dakboard-compatible JSON array.

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

import requests

PAPRIKA_BASE = "https://www.paprikaapp.com/api"
OUTPUT_FILE = "meal-plan.json"

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


def main() -> None:
    email = os.environ.get("PAPRIKA_EMAIL")
    password = os.environ.get("PAPRIKA_PASSWORD")
    if not email or not password:
        print("PAPRIKA_EMAIL and PAPRIKA_PASSWORD must both be set", file=sys.stderr)
        sys.exit(1)

    token = login(email, password)
    meals = get_meals(token)
    dakboard_data = build_dakboard_json(meals)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dakboard_data, f, indent=2)
        f.write("\n")

    print(f"Wrote {len(dakboard_data)} meal entries to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
