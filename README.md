# Paprika -> Dakboard meal plan sync

Pulls your weekly meal plan out of Paprika's Cloud Sync, plus your kids'
school lunch menu from Nutrislice, and publishes them as a page Dakboard
displays in a Website/iframe block. A GitHub Actions workflow runs hourly,
builds the page, and deploys it to GitHub Pages.

## What's in this folder

- `fetch_meal_plan.py` — ties `paprika.py` and `nutrislice.py` together: fetches both, renders the page, writes `index.html` and `meal-plan.json`
- `paprika.py` — Paprika Cloud Sync client: login, fetch meals, shape them into the current Fri-Thu cycle
- `nutrislice.py` — Nutrislice client: fetch the school lunch menu, extract just the main-course entrees
- `style.css` — the page's styling
- `requirements.txt` — the one Python dependency (`requests`)
- `.github/workflows/sync-meal-plan.yml` — builds the page each run and deploys it to GitHub Pages
- `.gitignore` — keeps generated output (`index.html`, `meal-plan.json`, `_site/`) and local test/dev clutter out of the repo

## Setup

1. **Create a new GitHub repository** (public is fine — see Notes below).

2. **Upload these files, preserving the folder structure:**
   ```
   fetch_meal_plan.py
   paprika.py
   nutrislice.py
   style.css
   requirements.txt
   .github/workflows/sync-meal-plan.yml
   ```
   Easiest way: `git clone` the new (empty) repo locally, copy this
   folder's contents in, then `git add . && git commit -m "initial setup"
   && git push`.

3. **Add your Paprika credentials as repository secrets.**
   Settings -> Secrets and variables -> Actions -> New repository secret.
   - `PAPRIKA_EMAIL` — your Paprika account email
   - `PAPRIKA_PASSWORD` — your Paprika account password

   The school lunch menu needs no credentials (Nutrislice's API is
   public), but it is pointed at a specific district/school via
   `NUTRISLICE_DISTRICT`, `NUTRISLICE_SCHOOL`, and `NUTRISLICE_MENU_TYPE`
   near the top of `nutrislice.py` — edit those directly if you ever need
   a different school.

4. **Turn on GitHub Pages.**
   Settings -> Pages -> under "Build and deployment", set Source to
   **GitHub Actions**. It'll show you a URL like
   `https://<your-username>.github.io/<repo-name>/` — it won't resolve
   until the first successful run, next step.

5. **Run it once manually to test.**
   Actions tab -> "Sync Paprika Meal Plan" -> Run workflow. After it
   finishes (~15-20 seconds), open the Pages URL from step 4 to confirm
   you see your styled meal table.

6. **Add it to Dakboard as a Website/iframe block.**
   Edit (or add) a Custom Screen, click **Add a Block** -> **Website/iframe**,
   paste the Pages URL, size/position it, and set the refresh interval to
   something like 30-60 minutes.

From here on, entering meals in Paprika is the only step — the dashboard
updates itself within the hour.

## Customizing the look

Edit `style.css` directly and commit — it's static, so no need to re-run
the script. The row markup itself (what HTML each day's row is made of)
is in `HTML_TEMPLATE`/`ROW_TEMPLATE` inside `fetch_meal_plan.py`, if you
ever need to change structure rather than styling.

Current design:
- Three columns: Dinner, Lunch (Paprika), and School Lunch (Nutrislice
  entrees only — sides/condiments are filtered out). An empty slot shows
  a muted "–". Other Paprika meal types (breakfast/snack) aren't shown on
  the page, though they're still in `meal-plan.json`.
- One row per day of the current cycle, always all 7 days.
- Past days are dimmed (`tr.past`), today is bolded with a green
  background highlight (`tr.today`).
- Background is a faint green tint (95% transparent) so Dakboard's own
  wallpaper mostly shows through. If you see a solid box instead, check
  the block's own Formatting tab in Dakboard — its background needs to be
  set to none/transparent too, since that's a separate layer from this
  page's CSS.
- Sized for a ~500px-wide block (`.card { width: 500px; }`) — change
  that, and the `colgroup` widths in `style.css`, if you resize the block.
- School Lunch lines too wide to fit are truncated with an ellipsis
  rather than wrapped (`td.school .sline`).

## Notes

- **Why a public repo is fine:** your Paprika credentials live in GitHub
  Secrets, encrypted and never exposed in logs or repo contents. The only
  things a public repo (and public Pages site) exposes are the generated
  meal names/dates and the script/workflow code, which contains no
  credentials.
- **Friday-Thursday cycle window:** anchored to the calendar, not a
  rolling window from "today" — it always shows the full Fri-Thu cycle,
  and switches over automatically as soon as the calendar rolls to
  Friday. Change `WEEK_ANCHOR_WEEKDAY` in `paprika.py` (Monday=0 ...
  Sunday=6) if your planning day changes.
- **Run frequency:** hourly (`cron: "0 * * * *"` in the workflow). Change
  the cron expression if you want it faster or slower.
- **Both APIs are unofficial/reverse-engineered** (Paprika's Cloud Sync
  and Nutrislice's menu API) — there's no official public API for either.
  If either service changes their backend, the workflow (or just the
  School Lunch column) may start failing; check the Actions log.
- **If Paprika login fails**, double check the `PAPRIKA_EMAIL` /
  `PAPRIKA_PASSWORD` secrets match your Cloud Sync login exactly.
- **If the School Lunch column goes empty**, a Nutrislice fetch failure
  is logged as a warning but doesn't stop the rest of the page from
  updating — check the Actions log first.
