# Paprika -> Dakboard meal plan sync

Pulls your weekly meal plan out of Paprika's Cloud Sync and publishes it as a
JSON file that Dakboard can display. Runs automatically once an hour via
GitHub Actions — no NAS, no manual export step.

## What's in this folder

- `fetch_meal_plan.py` — logs into Paprika, pulls the meal plan, writes `meal-plan.json`
- `requirements.txt` — the one Python dependency (`requests`)
- `.github/workflows/sync-meal-plan.yml` — the scheduled GitHub Actions job
- `meal-plan.json` — generated automatically; you don't need to create this yourself

## Setup steps

1. **Create a new GitHub repository.**
   Go to github.com -> New repository. Public is fine and simplest (see
   note below on why that's safe) — call it something like
   `paprika-dakboard-sync`.

2. **Upload these files, preserving the folder structure**, so you end up with:
   ```
   fetch_meal_plan.py
   requirements.txt
   .github/workflows/sync-meal-plan.yml
   ```
   Easiest way: `git clone` the new (empty) repo locally, copy this folder's
   contents in, then `git add . && git commit -m "initial setup" && git push`.
   (Or use GitHub's web "Add file" -> "Upload files" button, making sure the
   workflow file lands at exactly `.github/workflows/sync-meal-plan.yml`.)

3. **Add your Paprika credentials as repository secrets.**
   In the repo: Settings -> Secrets and variables -> Actions -> New
   repository secret.
   - Name: `PAPRIKA_EMAIL` — value: your Paprika account email
   - Name: `PAPRIKA_PASSWORD` — value: your Paprika account password

   These are encrypted by GitHub and never appear in logs or in the public
   repo, even though the repo itself is public.

4. **Run it once manually to test.**
   Go to the Actions tab -> "Sync Paprika Meal Plan" -> Run workflow. After
   it finishes (should take ~15-20 seconds), you should see a new
   `meal-plan.json` file committed to the repo with your current week's
   meals.

5. **Grab the raw file URL.**
   ```
   https://raw.githubusercontent.com/<your-username>/<repo-name>/main/meal-plan.json
   ```
   Open it in a browser to confirm it returns your meal JSON.

6. **Add it to Dakboard.**
   In your Dakboard dashboard, edit (or add) a Custom Screen, click **Add a
   Block** -> **External Data/Fetch**, paste the raw URL from step 5, and
   set the data type to JSON Array. Map `value` / `title` / `subtitle` to
   the fields you want displayed, and optionally set the "Icon Name" field
   to `icon` to show a little breakfast/lunch/dinner/snack icon per meal.
   Check the block's refresh/update interval and set it to something like
   30-60 minutes, in line with how often the GitHub Action runs.

That's it — from here on, entering meals in Paprika (on any device, thanks
to Cloud Sync) is the only step. The dashboard updates itself within an
hour.

## Notes

- **Why a public repo is fine:** your Paprika email/password live in GitHub
  Secrets, which are encrypted and never exposed — not in logs, not in the
  repo contents. The only thing a public repo exposes is `meal-plan.json`
  itself (just meal names and dates), plus the script/workflow code, which
  contains no credentials. If you'd rather keep the repo private, Dakboard's
  fetch block supports Bearer Token / Custom Header auth, but you'd need to
  point it at the GitHub REST API's file-contents endpoint instead of the
  plain raw URL, which is a bit more setup.
- **Friday-Thursday cycle window:** the script is anchored to a Fri-Thu
  planning cycle (matching a Thursday-night planning habit), not a rolling
  window from "today." It always shows the full current cycle - whether the
  Action happens to run on Friday morning or the following Wednesday night
  - and automatically switches over to the newly-entered next cycle as soon
  as the calendar rolls to Friday, even if those meals were entered a few
  days early. Change `WEEK_ANCHOR_WEEKDAY` in `fetch_meal_plan.py` (Monday=0
  ... Sunday=6) if your planning day ever changes.
- **How often it runs:** the workflow is set to run hourly
  (`cron: "0 * * * *"`). Change the cron expression in
  `.github/workflows/sync-meal-plan.yml` if you want it faster or slower —
  this is well within GitHub Actions' free usage limits either way.
- **This relies on an unofficial, reverse-engineered Paprika API** (there's
  no official one). If Paprika changes their backend, the workflow will
  start failing — check the Actions tab if the dashboard stops updating.
- **If login ever fails**, double check the `PAPRIKA_EMAIL` /
  `PAPRIKA_PASSWORD` secrets match your Paprika Cloud Sync login exactly.
