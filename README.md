# Shake Jelly Balls — Stats

A Basketball-Reference–style stats site for the team: home, schedule, per-game
box scores (with game-flow charts and five-man lineups), a players index, a page
per player, leaderboards, a team page, and a glossary — all interlinked.

It's a static site: a small Python build step turns the game CSVs into one
`site/data.json`, and a tiny static server serves the `site/` folder. No
database, no accounts, standard-library Python only.

## Quick start

Double-click **`start.bat`** (rebuilds the data, then serves at
`http://localhost:8000`), or from a terminal:

```bash
python server/build_site.py      # build site/data.json from data/scores/
python server/serve_site.py      # serve http://localhost:8000
```

## Add a game

1. Drop the game's two CSVs (`box-scores` and `play-by-play`) into the right
   season folder, e.g. **`data/scores/season-2/`** — keep their original filenames.
2. Double-click **`build.bat`** (or run `python server/build_site.py`).
3. Reload the site.

Games are grouped by season via `data/scores/season-1/`, `season-2/`, … and each
player page shows a row per season plus a Career row. Player headshots go in
`site/img/players/<slug>.jpg` (initials shown until you add one). See
**[STATS-SITE.md](STATS-SITE.md)** for both.

## Everything else

Deployment (GitHub Actions → Cloudflare Pages), changing the domain, how the
build validates the numbers, and the full file map are in **[STATS-SITE.md](STATS-SITE.md)**.

```
data/scores/<season>/ the game CSVs (box + play-by-play per game)
site/img/players/     optional player headshots (<slug>.jpg)
server/build_site.py  parse + validate + write site/data.json
server/serve_site.py  static server for site/ (no login)
site/                 the website (index.html, app.js, styles.css, data.json)
build.bat start.bat   rebuild / rebuild-and-serve
```
