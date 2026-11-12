# Shake Jelly Balls — Stats Site

A Basketball-Reference–style stats site for the team: home, schedule, per-game
box scores (with game-flow charts and five-man lineups), a players index, a page
per player, leaderboards, a team page, and a glossary. Everything links to
everything — a name goes to that player, a date goes to that game.

It replaces the old betting book as the main site. The betting code is still in
the repo (`server/app.py`, `web/`) but nothing runs it any more.

---

## How it works (the 30-second version)

1. The clean CSV exports for each game live in **`data/scores/`** — one
   `box-scores` CSV and one `play-by-play` CSV per game.
2. **`server/build_site.py`** reads them all, checks the numbers, computes every
   stat, and writes **`site/data.json`**.
3. **`site/`** is the website (one page, vanilla JavaScript). It reads
   `data.json` and renders everything. **`server/serve_site.py`** serves that
   folder.

No database, no accounts, no pip installs — standard-library Python only, same as
before.

---

## Run it on this machine

Double-click **`start.bat`** (rebuilds the data, then serves at
`http://localhost:8000`). For phones on the same wifi, use **`start-wifi.bat`**.

Or from a terminal:

```bash
python server/build_site.py      # build site/data.json
python server/serve_site.py      # serve http://localhost:8000
```

---

## Seasons

Games are grouped by season using folders inside `data/scores/`:

```
data/scores/
  season-1/      <- Season 1 games (the completed season)
  season-2/      <- Season 2 games (in progress)
```

A game's season is just which folder it's in. The folder name becomes the label
(`season-1` → "Season 1"). Player pages show one row **per season** plus a
Career row; the schedule groups games under season headings.

**Season switcher:** once there's more than one season, the Home, Team and Leaders
pages get a **"Showing" dropdown** (All-time / Season 1 / Season 2 / …) that
defaults to the latest season — so the record, team stats and leaderboards are
"this season" by default, with all-time and past seasons one click away. The
players index and individual player pages always show full career.

**Adding Season 1 later:** make a `data/scores/season-1/` folder, drop Season 1's
box-score + play-by-play CSVs in, and run `build.bat`. Every player's page grows
a Season 1 row and a Career row automatically — nothing else to do. (Players are
matched across seasons by **name**, so a player keeping the same name but a
different jersey number between seasons is still one person; the per-season table
shows each season's number.)

## Add a game (the main thing you'll do)

1. Export the game's two CSVs from the league app — the **box-scores** file and
   the **play-by-play** file. Keep the filenames as they come
   (`<opponent> vs Shake Jelly Balls (COMPLETE) box-scores-<date>.csv` etc.) —
   the build reads the opponent and date straight from the filename.
2. Drop **both** files into the right season folder, e.g. **`data/scores/season-2/`**.
3. Double-click **`build.bat`** (or run `python server/build_site.py`).
4. Reload the site. The new game, its box score, and every affected player and
   leader update automatically.

> **The date in the filename is the game date** — the build reads it from there,
> and the **round number** is worked out from it (weeks since the season's first
> game, so a bye or missing week still lands on the right round). If you re-export
> a game and the app names it with a different date (e.g. the export day), rename
> it back to the actual game date before dropping it in.

> **League off-weeks** — if the *whole league* skips a week (no round scheduled at
> all — not a bye SJB played around), that empty week would otherwise push every
> later round up by one. List any date inside such a week in
> **`data/off-weeks.json`** (`{"season-1": ["2026-06-07"]}`) and the build drops
> those weeks from the round count. Only list weeks the league held no round; a
> normal bye (others played, SJB didn't) is a real round SJB missed, so leave it.

The build prints a summary and a line for anything worth knowing — e.g. a game
where the opponent's turnovers came up short of our steals. If a number doesn't
reconcile (the points don't add up, or the play-by-play score doesn't match the
box) it tells you exactly which line, so you can fix the CSV and rebuild.

### Games that weren't fully recorded

The build handles three tiers automatically — no manual flagging:

- **Fully tracked** — box score + play-by-play. Everything.
- **Points + flow** (e.g. a game that wasn't video-recorded: per-player points in
  the box, plus a scoring play-by-play with a clock, but no shot attempts). The
  build **auto-detects** this (a box with points but zero field-goal attempts).
  The game counts in the record, score, points for/against and everyone's points;
  it shows the score, a points table, the half-by-half and the flow chart, and is
  **kept out of** shooting %, four factors, ratings and those season averages.
  Each player's rebounds/assists/shooting etc. are averaged only over the games
  that recorded them (the profile says "from X of Y games"); points span all games.
- **Points only** — just a final score and per-player points, no usable
  play-by-play: counts in the record and scoring, kept out of everything else.

To add a points-only game, put its CSVs in the season folder as usual — the box
with points filled and the other columns dashed (`-`), and the play-by-play
(scoring plays with their point value and a clock) if you have one.

**Extra detail a points-only box can't carry** (half-time scores when there's no
play-by-play, and a made-shot breakdown) goes in **`data/game-extras.json`**,
keyed by the game id (`<date>-<opponent-slug>`, e.g. `2026-10-11-helix`):

```json
{
  "2026-10-11-helix": {
    "half_scores": [ { "half": 1, "us": 40, "them": 26 },
                     { "half": 2, "us": 23, "them": 11 } ],
    "scoring": { "H. Lin": { "two": 8, "three": 0, "ft": 0 } }
  }
}
```

`half_scores` fills the "By half" box; `scoring` (counts of made 2s / 3s / FTs,
keyed by box name) shows a makes-only breakdown on the game page. Neither feeds
season shooting totals — there are no attempts — and the build checks both
reconcile to the box points, so a typo fails the build rather than going live.
The first such game is Round 3 of Season 2 (Helix, 11 Oct 2026, W 63-37).

### Pre-game penalty points (points credited to no player)

Sometimes the league puts points on the board that belong to no player — e.g.
team fouls/penalties applied **before tip-off** so the game starts, say, 6-5.
Those points count on the scoreboard but were never shot by anyone, so they
can't live in a player's box line. Declare them in **`data/game-extras.json`**
under the game id with `penalty_points`:

```json
{
  "2026-07-05-big-fellas": {
    "penalty_points": { "us": 5, "them": 6, "note": "Pre-game team penalties …" }
  }
}
```

The build leaves the box CSV completely untouched (so shooting, the points
identity and the play-by-play still reconcile to the **on-court** score) and
layers the penalty on top: `us`/`them` are added to make the **final score**,
which drives the result, the win/loss record and points for/against. Everything
statistical — player points, shooting, four factors, offensive/defensive rating
— stays on the on-court figures, so no player or efficiency number moves. On the
game page the scoreboard and the game-flow chart show the real final, the "By
half" box gains a **Pre-game** row so it still adds up to the final, and the
"Team totals" table is marked as on-court scoring. The build checks that on-court
+ penalty equals the final, so a wrong number fails the build. First use: Round
10 of Season 1 (Big Fellas, 5 Jul 2026 — started 6-5, finished 43-46 L). `note`
is optional; `us`/`them` default to 0.

### Forfeits (no box score at all)

A forfeit has no CSVs to drop in, so it's declared by hand in
**`data/forfeits.json`** — a list of entries:

```json
[
  { "season": "season-1", "date": "2026-05-24",
    "opponent": "Rainier Beach High School", "result": "W",
    "us": 20, "them": 0, "note": "Forfeit — ..." }
]
```

Run `build.bat` after editing. A forfeit **counts in the win/loss record** and
in the schedule (slotted into the right round by its date), and shows the
nominal score you give (`us`/`them`, optional — leave both out for a dash). It
is **kept out of everything statistical**: points for/against, team and player
averages, ratings and the scoring trend. It has its own stripped-down game page
(score + the note, no box score), and no player's numbers move. `result` is
optional when the score decides it.

## Player bio (positions)

Positions (and optional full-name overrides) live in **`data/players.json`**, keyed
by the box-score name:

```json
{ "H. Lin": { "position": "Guard" }, "M. Subramanian": { "position": "Forward" } }
```

Edit it and run `build.bat`. A blank position shows as a dash on the profile.
Each player can also have a `"nickname"` (shown in quotes under their name,
Basketball-Reference style) — blank hides it.

## Other-team seasons (players who played elsewhere)

A player who also played for another team can have that season shown on their
page and folded into their career (Basketball-Reference style), without it
touching SJB's record, leaders or team stats. These live in
**`data/external/*.json`** — e.g. `teddy-bears-2024.json`:

```json
{
  "season_label": "2024", "team": "Fluffy Teddy Bears", "sort_date": "2024-06-01",
  "players": {
    "S. King": { "appearances": 15, "pts": 106, "reb_games": 9, "reb": 45,
                 "ast_games": 10, "ast": 19, "box_games": 10, "box_pts": 74,
                 "fgm": 29, "fga": 66, "tpm": 3, "tpa": 10, "ftm": 16, "fta": 27,
                 "blk": 1, "stl": 4 }
  }
}
```

**Parking one:** files in `data/external/` are active; move one into
`data/external/disabled/` (and run `build.bat`) to take it off the site without
losing it — move it back up to reinstate. The Fluffy Teddy Bears 2024 season is
parked there now, ready to switch back on once its rescoring is done.

Keyed by SJB box name. Each stat carries its own tracked-game count
(`appearances` for points, `reb_games`, `ast_games`, `box_games` for shooting /
blk / stl), so it's averaged only over the games that recorded it — the uneven
tracking shows as blanks, exactly like an early-NBA season. Run `build.bat` after
editing. The player's SJB-only line (leaderboards, players index) is unaffected;
only their own page and career combine the two.

## Player photos

Each player page shows a headshot in the top-left. To add one, drop a JPG into
**`site/img/players/`** named after the player's slug (lowercase name, spaces and
dots → hyphens):

| Player         | File                              |
|----------------|-----------------------------------|
| H. Lin         | `site/img/players/h-lin.jpg`      |
| M. Subramanian | `site/img/players/m-subramanian.jpg` |
| V. Kanathigoda | `site/img/players/v-kanathigoda.jpg` |

No rebuild needed — just reload. Until a photo is there, the page shows the
player's initials. Roughly portrait (e.g. 300×380) looks best; it's cropped to
fit. The exact slug for anyone is the last part of their page URL
(`#/player/<slug>`).

---

## How it's deployed

The site is hosted on **Cloudflare Pages** and published by **GitHub Actions** —
nothing runs on a local machine. The CSVs in `data/scores/` are the source of
truth in the GitHub repo; the workflow in `.github/workflows/deploy.yml` runs
`fetch_ladder.py` + `build_site.py` on GitHub's servers and deploys the `site/`
folder to the Pages project **`sjb-stats`**, served at
**`stats.shakejellyballs.com`**.

It fires three ways:

- **On every push to `main`** (except doc-only changes) — add a game, it redeploys.
- **Weekly, Monday 08:00 Melbourne** (`cron: 0 21 * * 0`, UTC) — refreshes the
  live PlayHQ ladder. (GitHub cron is fixed UTC, so in Melbourne winter / AEST it
  lands an hour earlier, ~07:00; harmless.)
- **Manually** from the repo's **Actions** tab (**Run workflow**).

The committed `data/ladder.json` is the fallback: `fetch_ladder.py` refreshes it
in the runner only and the result is **not** committed back, so the repo copy
stays the last hand-saved ladder and is used if PlayHQ is ever unreachable.
`build_site.py`'s reconciliation checks run in CI, so a bad commit fails the build
and never publishes.

Two GitHub **secrets** power the deploy: `CLOUDFLARE_API_TOKEN` (an API token
scoped to *Account → Cloudflare Pages → Edit*) and `CLOUDFLARE_ACCOUNT_ID`.

Local preview is unchanged: `build.bat` then `start.bat` serves
`http://localhost:8000` on this machine whenever you want to look before pushing.

---

## Change the domain / subdomain

Your domain is **`shakejellyballs.com`** on Cloudflare. The public address is a
**custom domain on the Pages project**, so to change or add one (say
`www.shakejellyballs.com` or the bare apex):

1. Cloudflare dashboard → **Workers & Pages** → **`sjb-stats`** → **Custom
   domains** → **Set up a domain** → enter the name. Because the zone is already
   on Cloudflare, it creates the DNS record for you and issues the certificate.

2. To retire an old name, remove it under the same **Custom domains** panel (and
   delete any leftover DNS record for it in the dashboard).

No `config.yml`, tunnel, or service restarts are involved any more.

---

## Files

```
data/scores/<season>/     the clean game CSVs (box + play-by-play per game)
data/forfeits.json        forfeits / no-box results (optional; counts in record only)
data/off-weeks.json       weeks the league held no round (optional; fixes round numbers)
data/game-extras.json     half scores / made-shot breakdown / pre-game penalty points (optional)
site/img/players/<slug>.jpg  optional player headshots (initials shown if absent)
server/build_site.py      reads the CSVs, validates, writes site/data.json
server/serve_site.py      static server for the site/ folder (no login)
site/index.html           the page shell
site/app.js               the whole site (hash-routed, vanilla JS)
site/styles.css           Basketball-Reference-style look (light theme)
site/data.json            generated — do not edit by hand
build.bat / start.bat     rebuild / rebuild-and-serve

(retired) server/app.py, web/, server/sjb_book.db   the old betting book
```
