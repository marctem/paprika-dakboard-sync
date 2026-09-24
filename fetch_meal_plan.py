#!/usr/bin/env python3
"""
Ties together paprika.py and nutrislice.py: fetches the current Fri-Fri
cycle's meal plan from Paprika and the matching school lunch menu from
Nutrislice, then renders and writes (1) a plain JSON array (Paprika data
only) and (2) a fully self-contained, pre-rendered HTML page, meant to be
served via GitHub Pages and shown on Dakboard through a Website/iframe
block (rather than Dakboard's built-in External Data/JSON block, which has
limited styling and has been observed to drop entries).

Requires two environment variables:
    PAPRIKA_EMAIL    - the email address for your Paprika Cloud Sync account
    PAPRIKA_PASSWORD - the password for that account

These are read from the environment (GitHub Actions secrets, in the
intended setup) and are never written to disk or logged.
"""

import json
import os
import sys
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import nutrislice
import paprika

JSON_OUTPUT_FILE = "meal-plan.json"
HTML_OUTPUT_FILE = "index.html"

# GitHub Actions runners run in UTC, not your local time -- without this,
# "today" (and therefore which row is highlighted/dimmed) would flip over
# at midnight UTC, which is still evening/afternoon in most US timezones.
# Seattle is America/Los_Angeles (Pacific Time); change this if you ever
# move or want the page anchored to a different timezone.
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")

# Where the generated files get written. Defaults to the current directory
# (handy for a local test run), but the GitHub Actions workflow points this
# at a scratch build folder (`_site`) that's never committed to the repo --
# it's uploaded straight to GitHub Pages as a build artifact instead.
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", ".")

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


def _meal_cell(value, extra_class, error=None):
    cls = f"meal {extra_class}"
    if error:
        return f'<td class="{cls} error">⚠ {escape(error)}</td>'
    if value:
        return f'<td class="{cls}">{escape(value)}</td>'
    return f'<td class="{cls} empty">–</td>'


def _school_cell(names, error=None):
    if error:
        return f'<td class="meal school error"><div class="sline">⚠ {escape(error)}</div></td>'
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
        generated_at = datetime.now(LOCAL_TIMEZONE)

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
            dinner_cell=_meal_cell(day["dinner"], "dinner", error=day.get("dinner_error")),
            lunch_cell=_meal_cell(day["lunch"], "lunch"),
            # Past days drop the school lunch detail entirely (rather than
            # showing it, now-irrelevant) so those rows compact down to a
            # single line instead of staying tall from old entree lists.
            school_cell=(
                '<td class="meal school empty">–</td>'
                if day["is_past"]
                else _school_cell(day["school_lunch"], error=day.get("school_lunch_error"))
            ),
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

    today = datetime.now(LOCAL_TIMEZONE).date()
    window_start, window_end = paprika.current_cycle_bounds(today)

    # Paprika: if login or the fetch itself fails, don't take the whole page
    # down with it -- still render the full 7-day structure, with the error
    # surfaced in the Dinner column instead of silently showing dashes.
    try:
        token = paprika.login(email, password)
        meals = paprika.get_meals(token)
        paprika_error = None
    except Exception as exc:
        print(f"Warning: couldn't fetch Paprika meal plan: {exc}", file=sys.stderr)
        meals = []
        paprika_error = str(exc) or type(exc).__name__

    dakboard_data = paprika.build_dakboard_json(meals, today=today) if not paprika_error else []
    days = paprika.build_days(meals, today=today)
    for day in days:
        day["dinner_error"] = paprika_error

    # Nutrislice: a fetch failure for a given week is surfaced in the
    # School Lunch column for just the days in that week, rather than
    # failing the run or silently showing dashes.
    school_lunch, school_lunch_errors = nutrislice.get_school_lunch_days(window_start, window_end)
    for day in days:
        d = day["date"]
        day["school_lunch"] = school_lunch.get(d, [])
        day["school_lunch_error"] = school_lunch_errors.get(d)

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
