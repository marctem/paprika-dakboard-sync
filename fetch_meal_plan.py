#!/usr/bin/env python3
"""
Ties together paprika.py and nutrislice.py: fetches the current Fri-Thu
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

import nutrislice
import paprika

JSON_OUTPUT_FILE = "meal-plan.json"
HTML_OUTPUT_FILE = "index.html"

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

    token = paprika.login(email, password)
    meals = paprika.get_meals(token)

    today = datetime.now().date()
    window_start, window_end = paprika.current_cycle_bounds(today)

    dakboard_data = paprika.build_dakboard_json(meals, today=today)
    days = paprika.build_days(meals, today=today)

    school_lunch = nutrislice.get_school_lunch_days(window_start, window_end)
    for day in days:
        day["school_lunch"] = school_lunch.get(day["date"], [])

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
