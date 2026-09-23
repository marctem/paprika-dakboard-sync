# Paprika -> Dakboard meal plan sync

Pulls your weekly meal plan out of Paprika's Cloud Sync and publishes it as a
page Dakboard can display in a Website/iframe block. Runs automatically once
an hour via GitHub Actions — no NAS, no manual export step.

Also still writes a plain `meal-plan.json`, in case you want it for anything
else, but the primary output is `index.html` -- a fully self-styled page,
which gives full control over layout/fonts/colors and sidesteps the bugs and
limited styling of Dakboard's built-in External Data/JSON block.

## What's in this folder

- `fetch_meal_plan.py` — logs into Paprika, pulls the meal plan, writes `index.html` and `meal-plan.json`
- `requirements.txt` — the one Python dependency (`requests`)
- `.github/workflows/sync-meal-plan.yml` — the scheduled GitHub Actions job
- `.nojekyll` — tells GitHub Pages to serve files as-is, skipping its default Jekyll processing
- `index.html` / `meal-plan.json` — generated automatically; you don't need to create these yourself

## Setup steps

1. **Create a new GitHub repository.**
   Go to github.com -> New repository. Public is fine and simplest (see
   note below on why that's safe) — call it something like
   `paprika-dakboard-sync`.

2. **Upload these files, preserving the folder structure**, so you end up with:
   ```
   fetch_meal_plan.py
   requirements.txt
   .nojekyll
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
   it finishes (should take ~15-20 seconds), you should see new
   `index.html` and `meal-plan.json` files committed to the repo with your
   current cycle's meals.

5. **Turn on GitHub Pages.**
   Repo Settings -> Pages -> under "Build and deployment", set Source to
   "Deploy from a branch", Branch to `main` / `(root)`. Save. GitHub will
   give you a URL like:
   ```
   https://<your-username>.github.io/<repo-name>/
   ```
   It can take a minute or two to go live the first time. Open it in a
   browser to confirm you see your styled meal list (dark background,
   icon + day/meal-type + meal name per row).

6. **Add it to Dakboard as a Website/iframe block.**
   In your Dakboard dashboard, edit (or add) a Custom Screen, click **Add a
   Block** -> **Website/iframe**, paste the GitHub Pages URL from step 5,
   size/position the block, and set the refresh interval to something like
   30-60 minutes (matching, or a little slower than, how often the GitHub
   Action runs — no point refreshing faster than the data actually
   changes).

That's it — from here on, entering meals in Paprika (on any device, thanks
to Cloud Sync) is the only step. The dashboard updates itself within an
hour, and now you have full control over the look via the CSS in
`fetch_meal_plan.py`'s `HTML_TEMPLATE` — colors, fonts, spacing, row
layout, all of it.

### Customizing the look

Everything about the page's appearance lives in `HTML_TEMPLATE` and
`ROW_TEMPLATE` inside `fetch_meal_plan.py` — plain HTML/CSS, no build step.
Change the colors (currently a dark `#15171a` background), font sizes,
spacing, or the row layout, then commit — the next Action run (or a manual
"Run workflow") regenerates `index.html` with your changes, and GitHub
Pages picks it up automatically.

## Notes

- **Why a public repo is fine:** your Paprika email/password live in GitHub
  Secrets, which are encrypted and never exposed — not in logs, not in the
  repo contents. The only thing a public repo (and a public GitHub Pages
  site) exposes is `index.html`/`meal-plan.json` (just meal names and
  dates), plus the script/workflow code, which contains no credentials.
- **Why GitHub Pages instead of the raw file URL:** `raw.githubusercontent.com`
  serves everything as `text/plain`, so a browser (or an iframe) won't
  render an HTML page from it — it just shows the source code. GitHub Pages
  serves the same files with proper `text/html` headers, and doesn't send
  an `X-Frame-Options` header, so it's embeddable in Dakboard's iframe
  block. This is also why we moved off Dakboard's External Data/JSON block
  in the first place — a hand-built page gives full control over styling,
  where the built-in block's field-mapping and rendering are limited (and
  were dropping entries).
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
