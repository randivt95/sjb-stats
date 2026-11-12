"""Build the Shake Jelly Balls reference site's data layer.

Reads every game's clean CSV exports from data/scores/ (one box-score CSV and
one play-by-play CSV per game), runs the validation discipline from the build
brief, computes season/game/player stats, and writes site/data.json -- the only
thing the static site consumes. Re-run it after dropping a new game's pair of
CSVs into data/scores/ to refresh the whole site.

Pure standard library (csv, json, re, pathlib) -- the project ships with zero
pip dependencies and this keeps it that way.

Usage:
    python server/build_site.py              # build with validation
    python server/build_site.py --strict     # exit non-zero if any check fails

The source CSVs are the CLEAN exports (real player names, made-attempted splits,
two team-total rows, full play-by-play). This is a different, tidier source than
the betting book's old docs/box_scores.csv -- do not mix them.
"""

import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCORES_DIR = ROOT / "data" / "scores"
OUT = ROOT / "site" / "data.json"

TEAM_NAME = "Shake Jelly Balls"
TEAM_KEY = "shake jelly balls"          # how our side is labelled in the CSVs (lowered)

# Full names for the seven regulars, so player pages read like a real site
# rather than box-score initials. Anyone not here (one-off fill-ins) just shows
# the name the box score gives. Keyed by the box-score name.
FULL_NAMES = {
    "H. Lin": "Harry Lin",
    "S. King": "Sam King",
    "L. Pham": "Leo Pham",
    "R. Tennekoon": "Randiv Tennekoon",
    "V. Kanathigoda": "Viran Kanathigoda",
    "M. Subramanian": "Mithun Subramanian",
    "J. Paul": "Jake Paul",
}
CORE_NAMES = set(FULL_NAMES)

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# Opponent names look nicer title-cased, but a couple are special (an acronym,
# and a lowercase "old xaverians" that should read "Old Xaverians").
def pretty_opponent(raw):
    raw = raw.strip()
    if raw.lower().startswith("rmit"):
        return "RMIT " + " ".join(w.capitalize() for w in raw.split()[1:])
    return " ".join(w.capitalize() for w in raw.split())


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "x"


# --- CSV parsing -----------------------------------------------------------

def _clean_row(row):
    """CSV fields carry a leading space in this export (' 8-16'); strip keys
    and values so downstream code never has to think about it."""
    return {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def parse_split(cell):
    """'6-9' -> (6, 9). '-' or blank -> (0, 0)."""
    if not cell or cell == "-":
        return (0, 0)
    m = re.search(r"(\d+)\s*-\s*(\d+)", cell)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def parse_num(cell):
    cell = (cell or "").strip()
    if cell in ("", "-"):
        return 0
    try:
        return int(cell)
    except ValueError:
        try:
            return float(cell)
        except ValueError:
            return 0


def parse_opt_num(cell):
    """Like parse_num but returns None for a missing value (for +/- and min,
    which are '-' on the team-total rows)."""
    cell = (cell or "").strip()
    if cell in ("", "-"):
        return None
    try:
        return int(cell)
    except ValueError:
        try:
            return float(cell)
        except ValueError:
            return None


def _blank(cell):
    return (cell or "").strip() in ("", "-")


def _line_from_row(row):
    """Turn one cleaned box-score row into a stat line. Points are DERIVED from
    the shooting split, never trusted from the CSV -- see the points identity
    check in validation. `_present` records which stats were actually recorded (a
    cell that isn't '-'), so a partially-tracked game (points plus a few stats but
    no shooting) can keep what it has instead of being nuked to points-only."""
    fgm, fga = parse_split(row.get("fg"))
    tpm, tpa = parse_split(row.get("3pt"))
    ftm, fta = parse_split(row.get("ft"))
    oreb, dreb = parse_num(row.get("oreb")), parse_num(row.get("dreb"))
    reb_cell = row.get("reb")                                   # optional total-rebounds column
    reb = parse_num(reb_cell) if not _blank(reb_cell) else oreb + dreb

    present = set()
    if not _blank(row.get("fg")): present |= {"fgm", "fga"}
    if not _blank(row.get("3pt")): present |= {"tpm", "tpa"}
    if not _blank(row.get("ft")): present |= {"ftm", "fta"}
    for k, col in (("oreb", "oreb"), ("dreb", "dreb"), ("foul", "foul"), ("stl", "stl"),
                   ("to", "to"), ("blk", "blk"), ("min", "min"), ("plus_minus", "+/-")):
        if not _blank(row.get(col)): present.add(k)
    if not _blank(row.get("asst")) or not _blank(row.get("ast")): present.add("ast")
    if not _blank(reb_cell) or "oreb" in present or "dreb" in present: present.add("reb")

    return {
        "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa, "ftm": ftm, "fta": fta,
        "oreb": oreb, "dreb": dreb, "reb": reb,
        "foul": parse_num(row.get("foul")), "stl": parse_num(row.get("stl")),
        "to": parse_num(row.get("to")), "blk": parse_num(row.get("blk")),
        "ast": parse_num(row.get("asst") or row.get("ast")),
        "pts_csv": parse_num(row.get("pts")),
        "pts": 2 * (fgm - tpm) + 3 * tpm + ftm,
        "min": parse_opt_num(row.get("min")),
        "plus_minus": parse_opt_num(row.get("+/-")),
        "_present": present,
    }


def _player_name(cell):
    """' #22 H. Lin' -> (22, 'H. Lin'). Returns (None, name) if no number."""
    m = re.match(r"^#\s*(\d+)\s*(.*)$", cell.strip())
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, cell.strip()


def _is_dnp(line):
    """A did-not-play row is all dashes: every counting stat zero and no points.
    Uses the CSV points column too, so a points-only box (derived pts == 0 but the
    pts column filled) isn't mistaken for a DNP."""
    return (line["fga"] == 0 and line["fta"] == 0 and line["pts"] == 0
            and line.get("pts_csv", 0) == 0
            and line["reb"] == 0 and line["ast"] == 0 and line["stl"] == 0
            and line["to"] == 0 and line["blk"] == 0 and line["foul"] == 0
            and (line["min"] in (0, None)))


def parse_box(path, opp_pretty):
    """Parse one box-score CSV -> {players, team, opp}. DNP rows are dropped."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [_clean_row(r) for r in csv.DictReader(fh)]

    players, team, opp = [], None, None
    for row in rows:
        label = row.get("player", "")
        if not label:
            continue
        low = label.lower()
        line = _line_from_row(row)
        if TEAM_KEY in low:                       # our team-total row
            team = line
            continue
        if opp_pretty.lower() in low or (team is not None and not low.startswith("#")
                                         and "#" not in label):
            # the opponent total row (lowercased team name, no jersey)
            if "#" not in label:
                opp = line
                continue
        jersey, name = _player_name(label)
        if jersey is None and "#" not in label:
            # a non-player, non-matched total row -- treat as opponent total if
            # we don't have one yet
            if opp is None and team is not None:
                opp = line
            continue
        if _is_dnp(line):
            continue
        players.append({"jersey": jersey, "name": name, **line})
    return {"players": players, "team": team, "opp": opp}


# --- play-by-play ----------------------------------------------------------

MADE = {"TwoPointFG": 2, "ThreePointFG": 3, "OnePointFG": 1}


def _pbp_name(cell):
    """'#0 S. King' -> 'S. King'; a bare team name stays as-is."""
    m = re.match(r"^#\s*\d+\s*(.*)$", cell.strip())
    return m.group(1).strip() if m else cell.strip()


def parse_pbp(path):
    events = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            lineup = [l.strip() for l in (row.get("lineup") or "").split(",") if l.strip()]
            events.append({
                "stat": row.get("stat", ""),
                "is_opp": row.get("is_opp") == "1",
                "half": parse_num(row.get("time_period")) or 1,
                "clock": parse_num(row.get("game_time_sec")),
                "created_at": row.get("created_at", ""),
                "player": _pbp_name(row.get("player", "")),
                "lineup": [_pbp_name(x) for x in lineup],
            })
    # chronological: half ascending, then clock descending (counts down from 1200),
    # then insertion/created order as a tiebreak.
    events.sort(key=lambda e: (e["half"], -e["clock"], e["created_at"]))
    return events


def analyse_pbp(events):
    """Everything derived from the play-by-play: reconstructed score, flow,
    half scores, biggest lead, longest run, lineup minutes/+-, player on-court +/-."""
    us = them = 0
    flow = [[0, 0, 0, 0]]   # [event index, margin, us, them]
    biggest_lead = 0
    run_us = 0          # current unanswered run of our points
    longest_run = 0
    half_scores = {}
    player_pm = {}
    lineup_stats = {}   # key -> {"min":.., "for":.., "against":..}

    # lineup minutes: walk each half separately
    by_half = {}
    for e in events:
        by_half.setdefault(e["half"], []).append(e)

    for half, evs in sorted(by_half.items()):
        half_scores.setdefault(half, {"us": 0, "them": 0})
        if not evs:
            continue
        # minutes: credit the gap between consecutive events to the lineup on the
        # floor during it. Bound the half by the clock range the play-by-play
        # actually covers (first tip → last event), NOT an assumed 20:00→0:00: some
        # halves are called before the clock hits zero, so bookending to 0 credited
        # the on-court five minutes that were never played (a 37-min game read 40).
        prev_clock = max(e["clock"] for e in evs)
        prev_lineup = tuple(sorted(evs[0]["lineup"]))
        for e in evs:
            seg = prev_clock - e["clock"]
            if seg > 0 and prev_lineup:
                ls = lineup_stats.setdefault(prev_lineup, {"min": 0.0, "for": 0, "against": 0})
                ls["min"] += seg
            prev_clock = e["clock"]
            prev_lineup = tuple(sorted(e["lineup"]))
        # no tail past the last event — prev_clock is already the half's final moment

    # scoring walk (chronological across the whole game)
    half_marks = []     # flow indices where a new half/period begins (for the chart divider)
    prev_half = None
    for e in events:
        pts = MADE.get(e["stat"])
        if pts is None:
            continue
        if prev_half is not None and e["half"] != prev_half:
            half_marks.append(len(flow) - 0.5)   # sits between the last and first event of the halves
        prev_half = e["half"]
        key = tuple(sorted(e["lineup"]))
        ls = lineup_stats.setdefault(key, {"min": 0.0, "for": 0, "against": 0})
        if e["is_opp"]:
            them += pts
            half_scores[e["half"]]["them"] += pts
            ls["against"] += pts
            for name in e["lineup"]:
                player_pm[name] = player_pm.get(name, 0) - pts
            run_us = 0
        else:
            us += pts
            half_scores[e["half"]]["us"] += pts
            ls["for"] += pts
            for name in e["lineup"]:
                player_pm[name] = player_pm.get(name, 0) + pts
            run_us += pts
            longest_run = max(longest_run, run_us)
        margin = us - them
        biggest_lead = max(biggest_lead, margin)
        flow.append([len(flow), margin, us, them])

    lineups = []
    for key, ls in lineup_stats.items():
        if not key:                       # crude play-by-play with no lineup column
            continue
        lineups.append({
            "players": list(key),
            "min": round(ls["min"] / 60.0, 1),
            "for": ls["for"], "against": ls["against"],
            "plus_minus": ls["for"] - ls["against"],
        })
    lineups.sort(key=lambda l: -l["min"])

    return {
        "recon_us": us, "recon_them": them,
        "flow": flow,
        "flow_meta": {"half_marks": half_marks},
        "half_scores": [{"half": h, **half_scores[h]} for h in sorted(half_scores)],
        "biggest_lead": biggest_lead, "longest_run": longest_run,
        "player_pm": player_pm,
        "lineups": lineups,
    }


# --- play-by-play feed & auto highlights -----------------------------------

PBP_PTS = {"TwoPointFG": 2, "ThreePointFG": 3, "OnePointFG": 1}
PBP_LABELS = {
    "TwoPointFG": "made a 2",
    "ThreePointFG": "made a 3",
    "OnePointFG": "made a free throw",
    "TwoPointFGMiss": "missed a 2",
    "ThreePointFGMiss": "missed a 3",
    "OnePointFGMiss": "missed a free throw",
    "Steal": "steal",
    "Block": "blocked a shot",
    "DefReb": "defensive rebound",
    "OffReb": "offensive rebound",
    "Turnover": "turnover",
    "Foul": "foul",
}
# which event kinds count as "action" worth keeping in the readable feed
PBP_KEEP = set(PBP_LABELS)


def clock_str(sec):
    sec = max(0, int(sec or 0))
    return f"{sec // 60}:{sec % 60:02d}"


def build_pbp_feed(events, opponent):
    """A readable, chronological play-by-play: one entry per on-court action, with
    the running score carried on every row and assists folded into the make."""
    feed = []
    us = them = 0
    last_make = {"us": None, "them": None}
    for e in events:
        stat = e["stat"]
        if stat == "Assist":
            side = "them" if e["is_opp"] else "us"
            idx = last_make[side]
            if idx is not None and not e["is_opp"]:   # only SJB assists carry a real name
                feed[idx]["assist"] = e["player"]
            continue
        if stat not in PBP_KEEP:
            continue
        pts = PBP_PTS.get(stat, 0)
        side = "them" if e["is_opp"] else "us"
        if pts:
            if e["is_opp"]:
                them += pts
            else:
                us += pts
        feed.append({
            "half": e["half"], "clock": e["clock"], "t": clock_str(e["clock"]),
            "team": side, "kind": stat, "pts": pts, "score": pts > 0,
            "who": opponent if e["is_opp"] else e["player"],
            "label": PBP_LABELS[stat], "us": us, "them": them,
        })
        if pts:
            last_make[side] = len(feed) - 1
    return feed


def build_highlights(feed, opponent):
    """Auto-pick the key moments from the feed: scoring runs (>=6 unanswered),
    lead changes and ties, the biggest SJB lead, and the final bucket. Returned in
    chronological order; each carries the clock, the score at that point and a tag."""
    scores = [e for e in feed if e["score"]]
    if not scores:
        return []
    hl = []
    last_half = max(e["half"] for e in feed)

    # scoring runs: consecutive points by one side with no answer
    run_team, run_pts, run_last = None, 0, None
    def flush(end):
        if run_team and run_pts >= 6 and end:
            who = TEAM_NAME if run_team == "us" else opponent
            hl.append({"half": end["half"], "clock": end["clock"], "t": end["t"],
                       "team": run_team, "kind": "run",
                       "text": f"{who} on a {run_pts}–0 run",
                       "us": end["us"], "them": end["them"]})
    for e in scores:
        if e["team"] != run_team:
            flush(run_last)
            run_team, run_pts = e["team"], e["pts"]
        else:
            run_pts += e["pts"]
        run_last = e
    flush(run_last)

    # lead changes & ties (skip the opening basket); keep them from getting spammy
    prev_sign = 0
    for e in scores:
        m = e["us"] - e["them"]
        sign = (m > 0) - (m < 0)
        if prev_sign != 0 and sign == 0:
            hl.append({"half": e["half"], "clock": e["clock"], "t": e["t"], "team": None,
                       "kind": "tie", "text": "Tie game",
                       "us": e["us"], "them": e["them"]})
        elif prev_sign != 0 and sign != 0 and sign != prev_sign:
            who = TEAM_NAME if sign > 0 else opponent
            hl.append({"half": e["half"], "clock": e["clock"], "t": e["t"],
                       "team": "us" if sign > 0 else "them", "kind": "lead",
                       "text": f"{who} take the lead",
                       "us": e["us"], "them": e["them"]})
        if sign != 0:
            prev_sign = sign

    # biggest SJB lead (only if it was a real cushion)
    best = max(scores, key=lambda e: e["us"] - e["them"])
    if best["us"] - best["them"] >= 8:
        hl.append({"half": best["half"], "clock": best["clock"], "t": best["t"], "team": "us",
                   "kind": "lead-max", "text": f"SJB's biggest lead (+{best['us'] - best['them']})",
                   "us": best["us"], "them": best["them"]})

    # the final made basket of the game
    fin = scores[-1]
    hl.append({"half": fin["half"], "clock": fin["clock"], "t": fin["t"], "team": fin["team"],
               "kind": "final", "text": "Final score",
               "us": fin["us"], "them": fin["them"]})

    # chronological, de-duplicated by (half, clock, text); cap the list
    hl.sort(key=lambda h: (h["half"], -h["clock"]))
    seen, out = set(), []
    for h in hl:
        k = (h["half"], h["clock"], h["text"])
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out[:14]


# --- metrics ---------------------------------------------------------------

def _r(x, n=1):
    return round(x, n) if x is not None else None


def game_score(l):
    return (l["pts"] + 0.4 * l["fgm"] - 0.7 * l["fga"] - 0.4 * (l["fta"] - l["ftm"])
            + 0.7 * l["oreb"] + 0.3 * l["dreb"] + l["stl"] + 0.7 * l["ast"]
            + 0.7 * l["blk"] - 0.4 * l["foul"] - l["to"])


def fantasy(l):
    return (l["pts"] + 2 * l["fgm"] - l["fga"] + l["tpm"] + l["ftm"] - l["fta"]
            + l["reb"] + 2 * l["ast"] + 4 * l["stl"] + 4 * l["blk"] - 2 * l["to"])


def possessions(l):
    return l["fga"] - l["oreb"] + l["to"] + 0.44 * l["fta"]


def pct(made, att):
    return round(100 * made / att, 1) if att else None


def four_factors(l, opp_dreb):
    poss_denom = l["fga"] + 0.44 * l["fta"] + l["to"]
    return {
        "efg": round(100 * (l["fgm"] + 0.5 * l["tpm"]) / l["fga"], 1) if l["fga"] else None,
        "tov_pct": round(100 * l["to"] / poss_denom, 1) if poss_denom else None,
        "oreb_pct": round(100 * l["oreb"] / (l["oreb"] + opp_dreb), 1) if (l["oreb"] + opp_dreb) else None,
        "ft_rate": round(l["fta"] / l["fga"], 3) if l["fga"] else None,
    }


# --- assembling the game ---------------------------------------------------

FILE_RE = re.compile(r"^(.*?) vs Shake Jelly Balls.*?(box-scores|play-by-play)-(\d{1,2}) (\w{3}) (\d{4})",
                     re.IGNORECASE)


def season_label(folder_name):
    """'season-2' -> 'Season 2'; '2025' -> '2025'; anything else title-cased."""
    m = re.match(r"^season[-_ ]?(\d+)$", folder_name.strip(), re.IGNORECASE)
    if m:
        return f"Season {int(m.group(1))}"
    return folder_name.replace("-", " ").replace("_", " ").strip().title()


def _scan_csv_dir(directory, season_key, season_name, pairs):
    """Pair up box-score and play-by-play CSVs in one directory by (opponent, date)."""
    for path in sorted(directory.glob("*.csv")):
        m = FILE_RE.match(path.name)
        if not m:
            continue
        opp_raw, kind, day, mon, year = m.groups()
        month = MONTHS.get(mon.lower()[:3])
        if month is None:
            continue
        iso = f"{int(year):04d}-{month:02d}-{int(day):02d}"
        key = (season_key, opp_raw.strip().lower(), iso)
        pairs.setdefault(key, {"opp_raw": opp_raw.strip(), "iso": iso,
                               "season_key": season_key, "season_label": season_name})
        pairs[key]["box" if "box" in kind.lower() else "pbp"] = path


def discover_games(scores_dir):
    """Find every game across season subfolders.

    Games live in `data/scores/<season>/` subfolders (e.g. `season-1`, `season-2`),
    and each game's season is taken from its folder. Loose CSVs sitting directly in
    `data/scores/` are accepted too and treated as the latest/only season, so a
    first-timer who just drops files in doesn't get an empty site.
    """
    pairs = {}
    subdirs = sorted([d for d in scores_dir.iterdir() if d.is_dir()]) if scores_dir.is_dir() else []
    for d in subdirs:
        _scan_csv_dir(d, d.name.lower(), season_label(d.name), pairs)
    loose = list(scores_dir.glob("*.csv"))
    if loose:
        # no folder to name them -> call it the highest season we have, else Season 1
        default_key = "season-1"
        default_name = "Season 1"
        _scan_csv_dir(scores_dir, default_key, default_name, pairs)
    # order seasons by their earliest game date, games within a season by date
    metas = list(pairs.values())
    season_first = {}
    for mta in metas:
        k = mta["season_key"]
        season_first[k] = min(season_first.get(k, mta["iso"]), mta["iso"])
    metas.sort(key=lambda mta: (season_first[mta["season_key"]], mta["iso"]))
    return metas


def build_game(meta, warnings):
    opp = pretty_opponent(meta["opp_raw"])
    box = parse_box(meta["box"], opp)
    gid = f"{meta['iso']}-{slugify(opp)}"
    date = dt.date.fromisoformat(meta["iso"])
    date_disp = date.strftime("%d %b %Y").lstrip("0")

    team, oppl = box["team"], box["opp"]

    # A "points-only box" (a game that wasn't video-recorded): per-player points
    # but no shot attempts logged. We detect it rather than flag it by hand — a
    # fully-tracked game always has field-goal attempts. For such a game, trust
    # the CSV's points column and mark every other stat UNKNOWN (None), not zero,
    # so it's never averaged as a zero rebound night.
    partial = (team.get("fga", 0) == 0 and team.get("pts_csv", 0) > 0)
    level = "partial" if partial else "full"

    UNKNOWN = ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "reb",
               "foul", "stl", "to", "blk", "ast", "min", "plus_minus")

    def points_only(line):
        """Shooting can't be reconstructed without the splits, so trust the CSV's
        points column and drop shooting; but KEEP any counting stats that were
        actually recorded (rebounds / assists / fouls on a non-video game), and
        null only the ones this game didn't track."""
        out = dict(line)
        out["pts"] = line.get("pts_csv", 0)
        present = line.get("_present", set())
        for k in UNKNOWN:
            if k not in present:
                out[k] = None
        return out

    if partial:
        team, oppl = points_only(team), points_only(oppl)
        box_players = [points_only(p) for p in box["players"]]
    else:
        box_players = box["players"]

    g = {
        "id": gid, "date": meta["iso"], "date_disp": date_disp,
        "season": meta.get("season_key", "season-1"),
        "season_label": meta.get("season_label", "Season 1"),
        "opponent": opp, "opponent_slug": slugify(opp),
        "us": team["pts"], "them": oppl["pts"],
        "margin": team["pts"] - oppl["pts"],
        "result": "W" if team["pts"] > oppl["pts"] else ("L" if team["pts"] < oppl["pts"] else "D"),
        "level": level, "partial": partial, "tracked": not partial, "points_only": False,
        "notes": [],
    }

    # per-player box with derived metrics
    def enrich(line, name, jersey):
        out = dict(line)
        out.pop("_present", None)
        out["name"] = name
        out["jersey"] = jersey
        out["slug"] = slugify(name)
        if partial:
            out["fg_pct"] = out["tp_pct"] = out["ft_pct"] = None
            out["gmsc"] = out["fp"] = None
        else:
            out["fg_pct"] = pct(line["fgm"], line["fga"])
            out["tp_pct"] = pct(line["tpm"], line["tpa"])
            out["ft_pct"] = pct(line["ftm"], line["fta"])
            out["gmsc"] = round(game_score(line), 1)
            out["fp"] = round(fantasy(line), 1)
        return out

    g["box_us"] = [enrich(p, p["name"], p["jersey"]) for p in box_players]
    g["box_us"].sort(key=lambda p: -(p["pts"] or 0))

    g["team_line"] = enrich(team, TEAM_NAME, None)
    g["opp_line"] = enrich(oppl, opp, None)

    if partial:
        g["four_factors"] = g["opp_four_factors"] = None
        g["poss"] = g["opp_poss"] = None
        g["ratings"] = {"off": None, "def": None, "net": None}
        g["tov_margin"] = None
        g["pct_pts_from_3"] = None
        g["opp_reliable"] = True
        if team.get("reb") is not None or team.get("ast") is not None:
            g["notes"].append(
                "Not video-recorded — points, rebounds, assists and fouls were kept on a "
                "stat sheet, but no shooting splits, steals, blocks or play-by-play. The "
                "missing stats stay out of shooting/efficiency figures and those averages; "
                "points, rebounds, assists and the result all count.")
        else:
            g["notes"].append(
                "Not video-recorded — only the final score and per-player points are available "
                "for this game. No shooting, rebounds, assists or advanced stats, so it's kept "
                "out of shooting/efficiency figures and those season averages. The points and "
                "the result still count.")
    else:
        g["four_factors"] = four_factors(team, oppl["dreb"])
        g["opp_four_factors"] = four_factors(oppl, team["dreb"])
        poss = possessions(team)
        opp_poss = possessions(oppl)
        g["poss"] = round(poss, 1)
        g["opp_poss"] = round(opp_poss, 1)
        g["ratings"] = {
            "off": round(100 * team["pts"] / poss, 1) if poss else None,
            "def": round(100 * oppl["pts"] / opp_poss, 1) if opp_poss else None,
        }
        if g["ratings"]["off"] is not None and g["ratings"]["def"] is not None:
            g["ratings"]["net"] = round(g["ratings"]["off"] - g["ratings"]["def"], 1)
        g["tov_margin"] = oppl["to"] - team["to"]
        g["pct_pts_from_3"] = round(100 * 3 * team["tpm"] / team["pts"], 1) if team["pts"] else None

        # opponent-stat reliability: a steal always logs a paired opponent turnover,
        # so opp TO must be >= our steals. If it's short, turnovers are missing.
        opp_reliable = oppl["to"] >= team["stl"]
        g["opp_reliable"] = opp_reliable
        if not opp_reliable:
            missing = team["stl"] - oppl["to"]
            g["missing_turnovers"] = missing
            g["notes"].append(
                f"Opponent turnovers look {missing} short of our steals "
                f"({oppl['to']} vs {team['stl']} steals) — a steal or two logged without "
                f"its paired turnover. Defensive rating uses the recorded figure.")

    # play-by-play
    if meta.get("pbp") and meta["pbp"].is_file():
        events = parse_pbp(meta["pbp"])
        pbp = analyse_pbp(events)
        g["half_scores"] = pbp["half_scores"]
        g["biggest_lead"] = pbp["biggest_lead"]
        g["longest_run"] = pbp["longest_run"]
        g["flow"] = pbp["flow"]
        g["flow_meta"] = pbp["flow_meta"]
        g["lineups"] = [l for l in pbp["lineups"] if l["min"] >= 0.5][:8]
        g["_recon"] = (pbp["recon_us"], pbp["recon_them"])
        g["_player_pm"] = pbp["player_pm"]
        g["pbp"] = build_pbp_feed(events, g["opponent"])
        g["highlights"] = build_highlights(g["pbp"], g["opponent"])
    else:
        g["notes"].append("No play-by-play for this game — flow, lineups and half splits unavailable.")

    # a partial game with no play-by-play flow AND no box counting stats is a
    # "points only" game (just a final score and per-player points). A partial game
    # that still has rebounds/assists/fouls recorded (a non-video game someone kept
    # a stat sheet for) is "box only" — richer than points-only, so flag it apart.
    has_box = any((p.get("reb") is not None or p.get("ast") is not None)
                  for p in g["box_us"])
    g["points_only"] = bool(partial and not g.get("flow") and not has_box)
    g["box_only"] = bool(partial and not g.get("flow") and has_box)
    # half scores may still be supplied by hand via game-extras.json, merged in build().
    return g


# --- forfeits (no box score to parse) --------------------------------------

def load_forfeits():
    """Results with no box score or play-by-play to parse — a forfeit, say —
    declared by hand in data/forfeits.json. Each entry counts in the win/loss
    record and may show a nominal score "for the record", but carries NO player
    or team stats: it's kept out of points-for/against, averages and ratings, so
    nobody's numbers move. Shape (a list):
        [{"season": "season-1", "date": "2026-05-24",
          "opponent": "Rainier Beach High School", "result": "W",
          "us": 20, "them": 0, "note": "Forfeit — ..."}]
    `us`/`them` are optional (default 0-0, i.e. no score shown); `result` is
    optional when a score decides it.
    """
    path = ROOT / "data" / "forfeits.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARNING: couldn't read data/forfeits.json ({e}); ignoring it")
        return []
    return data if isinstance(data, list) else []


def load_game_extras():
    """Hand-entered extras for games whose league export was incomplete, keyed by
    game id (`<date>-<opponent-slug>`). Two optional pieces a points-only box CSV
    can't carry: `half_scores` (feeds the By-half box when there's no play-by-play
    to derive it from) and `scoring` (per-player made-shot breakdown — two/three/ft
    makes — shown on the game page as makes-only). Neither feeds season shooting
    totals; the build checks both reconcile to the box points. Shape:
        {"2026-10-11-helix": {"half_scores": [{"half":1,"us":40,"them":26}, ...],
                              "scoring": {"H. Lin": {"two":8,"three":0,"ft":0}}}}"""
    path = ROOT / "data" / "game-extras.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARNING: couldn't read data/game-extras.json ({e}); ignoring it")
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and not k.startswith("_")}


def load_off_weeks():
    """Weeks the LEAGUE held no round at all (not a bye — nobody played).
    data/off-weeks.json maps a season key to a list of ISO dates, any one inside
    such a week. Round numbers are weeks-since-the-opener, so an empty league week
    would otherwise push every later round up by one; the build subtracts these.
    A real bye (the league played, SJB sat out) is NOT listed — that week is a
    round SJB genuinely missed. Shape: {"season-1": ["2026-06-07"]}."""
    path = ROOT / "data" / "off-weeks.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARNING: couldn't read data/off-weeks.json ({e}); ignoring it")
        return {}
    return {k: v for k, v in data.items() if isinstance(v, list)}


def load_ladder():
    """League ladder / standings, hand-entered per season in data/ladder.json (the
    exports only carry SJB's own games, so the league-wide table can't be derived).
    Keyed by season; each season has metadata + a 'teams' list in official order.
    Rows are passed through to the site as-is; the SJB row is flagged for
    highlighting by matching the team name. Missing file or bad JSON is fine — the
    site just shows no ladder."""
    path = ROOT / "data" / "ladder.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARNING: couldn't read data/ladder.json ({e}); ignoring it")
        return {}
    out = {}
    for season, blk in data.items():
        if season.startswith("_") or not isinstance(blk, dict):
            continue
        teams = blk.get("teams") or []
        rows = []
        for i, t in enumerate(teams):
            row = dict(t)
            row["rank"] = i + 1
            row["is_sjb"] = (t.get("team", "").strip().lower() == TEAM_NAME.lower())
            rows.append(row)
        out[season] = {
            "updated": blk.get("updated"),
            "status": blk.get("status"),
            "ranked_by": blk.get("ranked_by"),
            "note": blk.get("note"),
            "teams": rows,
        }
    return out


def build_forfeit(f):
    """A forfeit/no-box result as a game object, shaped enough to flow through the
    schedule, record and its own game page — but with level 'forfeit', empty box
    and no advanced stats, so aggregation skips it everywhere that matters."""
    iso = f["date"]
    date = dt.date.fromisoformat(iso)
    opp = (f.get("opponent") or "Opponent").strip()
    season_key = f.get("season", "season-1")
    us = int(f.get("us", 0) or 0)
    them = int(f.get("them", 0) or 0)
    result = (f.get("result") or ("W" if us > them else "L" if us < them else "D")).upper()
    note = f.get("note") or (
        "Forfeit — counts as a result in the standings. Any score shown is nominal "
        "and kept out of points-for/against, averages and ratings, so no player or "
        "team stats are affected.")
    return {
        "id": f"{iso}-{slugify(opp)}", "date": iso,
        "date_disp": date.strftime("%d %b %Y").lstrip("0"),
        "season": season_key, "season_label": season_label(season_key),
        "opponent": opp, "opponent_slug": slugify(opp),
        "us": us, "them": them, "margin": us - them, "result": result,
        "level": "forfeit", "partial": False, "tracked": False, "points_only": False,
        "forfeit": True, "nominal_score": (us > 0 or them > 0),
        "notes": [note], "box_us": [], "lineups": [],
    }


# --- validation ------------------------------------------------------------

def validate(games, warnings):
    checks = []

    def check(ok, label):
        checks.append({"ok": bool(ok), "label": label})
        if not ok:
            warnings.append(label)

    for g in games:
        if g.get("level") == "forfeit":
            continue                              # no box or play-by-play to check
        tag = f"{g['date']} vs {g['opponent']}"
        # 1. points identity on every line (players + both teams) — only for
        #    fully-tracked games; a points-only box has no shooting to check.
        if not g.get("partial"):
            for p in g["box_us"]:
                ident = 2 * (p["fgm"] - p["tpm"]) + 3 * p["tpm"] + p["ftm"]
                check(ident == p["pts"] == p["pts_csv"] if p["pts_csv"] else ident == p["pts"],
                      f"{tag}: points identity for {p['name']} ({ident} vs box {p['pts_csv']})")
            for line, who in ((g["team_line"], TEAM_NAME), (g["opp_line"], g["opponent"])):
                ident = 2 * (line["fgm"] - line["tpm"]) + 3 * line["tpm"] + line["ftm"]
                check(ident == line["pts"], f"{tag}: points identity for {who} total")

        # 2. reconstruct final score from the play-by-play — against the ON-COURT
        #    score (the play-by-play logs only on-court points; any pre-game
        #    penalty points are layered on separately and checked in #5).
        if "_recon" in g:
            ru, rt = g["_recon"]
            cu = g.get("us_oncourt", g["us"])
            ct = g.get("them_oncourt", g["them"])
            check(ru == cu and rt == ct,
                  f"{tag}: play-by-play score {ru}-{rt} vs box {cu}-{ct}")

        # 2b. pre-game penalty points must reconcile: on-court + penalty == final.
        if g.get("penalty"):
            pu, pt = g["penalty"]["us"], g["penalty"]["them"]
            check(g.get("us_oncourt", 0) + pu == g["us"]
                  and g.get("them_oncourt", 0) + pt == g["them"],
                  f"{tag}: penalty {pu}-{pt} + on-court "
                  f"{g.get('us_oncourt')}-{g.get('them_oncourt')} != final "
                  f"{g['us']}-{g['them']}")

        # 3. reconstruct each player's on-court +/- from the play-by-play
        if "_player_pm" in g:
            for p in g["box_us"]:
                if p["plus_minus"] is None:
                    continue
                recon = g["_player_pm"].get(p["name"])
                if recon is None:
                    continue
                check(recon == p["plus_minus"],
                      f"{tag}: +/- for {p['name']} reconstructs to {recon}, box says {p['plus_minus']}")

        # 4. hand-entered extras for a points-only game must reconcile to the box:
        #    each player's made-shot breakdown back to their points, and the
        #    half-by-half scores back to the final.
        if g.get("scoring"):
            for p in g["box_us"]:
                s = g["scoring"].get(p["name"])
                if not s:
                    continue
                recon = 2 * s.get("two", 0) + 3 * s.get("three", 0) + s.get("ft", 0)
                check(recon == p["pts"],
                      f"{tag}: scoring breakdown for {p['name']} ({recon}) vs points {p['pts']}")
        if g.get("partial") and g.get("half_scores"):
            hu = sum(h["us"] for h in g["half_scores"])
            ht = sum(h["them"] for h in g["half_scores"])
            check(hu == g["us"] and ht == g["them"],
                  f"{tag}: half scores {hu}-{ht} vs final {g['us']}-{g['them']}")
    return checks


# --- season aggregation ----------------------------------------------------

STAT_KEYS = ["fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "reb",
             "foul", "stl", "to", "blk", "ast", "pts"]


def accumulate(lines):
    """Sum each stat over the lines, skipping UNKNOWN (None) values, and count how
    many games actually tracked each stat. A points-only game contributes to the
    points sum/count but not to rebounds etc., so a rebound isn't averaged as zero."""
    tot = {k: 0 for k in STAT_KEYS}
    cnt = {k: 0 for k in STAT_KEYS}
    for l in lines:
        for k in STAT_KEYS:
            v = l.get(k)
            if v is not None:
                tot[k] += v
                cnt[k] += 1
    return tot, cnt


def averages(tot, cnt):
    """Per-stat average over the games where that stat was recorded (None if never)."""
    return {k: (round(tot[k] / cnt[k], 1) if cnt[k] else None) for k in tot}


def display_block(raw):
    """Turn a raw aggregate (totals + per-stat counts + sums) into the display
    block the site renders. Works the same for an SJB season, a career, or an
    external (other-team) season — and combined blocks (see combine_raw) too."""
    t, c = raw["totals"], raw["counts"]

    def avg(k):
        return round(t[k] / c[k], 1) if c[k] and t[k] is not None else None

    fga, fta, fgm, tpm = (t["fga"] or 0), (t["fta"] or 0), (t["fgm"] or 0), (t["tpm"] or 0)
    tpa, ftm = (t["tpa"] or 0), (t["ftm"] or 0)

    # per-36-minutes line (BBref "Per 36 Minutes") — total stat / total minutes * 36
    mp_sum = raw["mp_sum"]
    def p36(k):
        return round((t[k] or 0) / mp_sum * 36, 1) if mp_sum else None
    per36 = {k: p36(k) for k in STAT_KEYS} if mp_sum else None

    # shooting profile (BBref "Shooting" table, minus the shot chart we can't build):
    # how a player's points are distributed across 2P / 3P / FT, and efficiency on
    # each. Shares use shooting-game points as the denominator (so they sum to 100
    # even when some games were points-only).
    pts2, pts3, ptsft = 2 * (fgm - tpm), 3 * tpm, ftm
    sh_pts = pts2 + pts3 + ptsft
    shot = {
        "pts2": pts2, "pts3": pts3, "ptsft": ptsft,
        "pct_pts_2": round(100 * pts2 / sh_pts, 1) if sh_pts else None,
        "pct_pts_3": round(100 * pts3 / sh_pts, 1) if sh_pts else None,
        "pct_pts_ft": round(100 * ptsft / sh_pts, 1) if sh_pts else None,
        "fg2_pct": pct(fgm - tpm, fga - tpa), "fg3_pct": pct(tpm, tpa),
        "fg3a_rate": round(tpa / fga, 3) if fga else None,   # share of FGA that are threes
    }
    return {
        "games": raw["games"],
        "games_detail": c["reb"],
        "mp_avg": round(raw["mp_sum"] / raw["mp_count"], 1) if raw["mp_count"] else None,
        "mp_total": round(raw["mp_sum"]) if raw["mp_count"] else None,
        "totals": t,
        "averages": {k: avg(k) for k in STAT_KEYS},
        "per36": per36,
        "shot": shot,
        "fg_pct": pct(fgm, fga), "tp_pct": pct(tpm, t["tpa"] or 0), "ft_pct": pct(t["ftm"] or 0, fta),
        "efg": round(100 * (fgm + 0.5 * tpm) / fga, 1) if fga else None,
        "ts": round(100 * raw["pts_shooting"] / (2 * (fga + 0.44 * fta)), 1) if (fga + fta) else None,
        "gmsc_total": round(raw["gmsc_sum"], 1) if raw["gmsc_count"] else None,
        "gmsc_avg": round(raw["gmsc_sum"] / raw["gmsc_count"], 1) if raw["gmsc_count"] else None,
        "fp_total": round(raw["fp_sum"], 1) if raw["fp_count"] else None,
        "fp_avg": round(raw["fp_sum"] / raw["fp_count"], 1) if raw["fp_count"] else None,
        "plus_minus_total": raw["pm_sum"] if raw["pm_count"] else None,
        "plus_minus_avg": round(raw["pm_sum"] / raw["pm_count"], 1) if raw["pm_count"] else None,
        "_raw": raw,
    }


def raw_from_lines(lines):
    tot, cnt = accumulate(lines)
    tot = {k: (tot[k] if cnt[k] else None) for k in STAT_KEYS}
    gmscs = [p["gmsc"] for p in lines if p.get("gmsc") is not None]
    fps = [p["fp"] for p in lines if p.get("fp") is not None]
    pm_vals = [p["plus_minus"] for p in lines if p.get("plus_minus") is not None]
    mins = [p["min"] for p in lines if p.get("min") is not None]
    return {
        "games": len(lines), "totals": tot, "counts": cnt,
        "pts_shooting": sum(p["pts"] for p in lines if p.get("fga") is not None and p.get("pts") is not None),
        "gmsc_sum": sum(gmscs), "gmsc_count": len(gmscs),
        "fp_sum": sum(fps), "fp_count": len(fps),
        "pm_sum": sum(pm_vals), "pm_count": len(pm_vals),
        "mp_sum": sum(mins), "mp_count": len(mins),
    }


def combine_raw(a, b):
    """Merge two raw aggregates (e.g. an SJB career + an external season)."""
    def tot(k):
        va, vb = a["totals"][k], b["totals"][k]
        return None if (va is None and vb is None) else (va or 0) + (vb or 0)
    out = {"games": a["games"] + b["games"],
           "totals": {k: tot(k) for k in STAT_KEYS},
           "counts": {k: a["counts"][k] + b["counts"][k] for k in STAT_KEYS}}
    for k in ("pts_shooting", "gmsc_sum", "gmsc_count", "fp_sum", "fp_count",
              "pm_sum", "pm_count", "mp_sum", "mp_count"):
        out[k] = a[k] + b[k]
    return out


def split_stats(lines):
    """Display block for a set of SJB game lines (a season or a career)."""
    return display_block(raw_from_lines(lines))


def load_player_meta():
    """Optional per-player bio info, hand-kept in data/players.json and keyed by the
    box-score name. Any field is optional; a missing file or bad JSON is fine — the
    site just omits whatever isn't given. Recognised fields per player:
        position   -> shown on the profile header (e.g. "Guard", "Center")
        nickname   -> shown in parentheses under the name
        jersey     -> authoritative squad number; overrides the auto-derived one and
                      is the only number shown as "No." on the profile header
        full_name  -> overrides the displayed full name (else FULL_NAMES / box name)
    Example:
        {
          "H. Lin":          {"position": "Center", "nickname": "Flying Dragon", "jersey": 22},
          "M. Subramanian":  {"position": "Forward", "jersey": 77}
        }
    """
    path = ROOT / "data" / "players.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARNING: couldn't read data/players.json ({e}); ignoring it")
    return {}


def load_external_seasons():
    """Seasons a player had on another team (data/external/*.json). These are shown
    on that player's page and folded into their career, Basketball-Reference style,
    but never touch SJB's record, schedule, leaders or team stats. Keyed by box name
    -> list of display blocks. Counting-stat totals come each with their own tracked-
    game count; shooting/blk/stl come from the box-scores subset."""
    out = {}
    d = ROOT / "data" / "external"
    if not d.is_dir():
        return out
    for path in sorted(d.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARNING: couldn't read external/{path.name} ({e}); ignoring it")
            continue
        label, team = data.get("season_label", path.stem), data.get("team", "")
        sort_date = data.get("sort_date", "2000-01-01")
        for name, e in (data.get("players") or {}).items():
            bg = int(e.get("box_games", 0) or 0)
            totals = {"pts": e.get("pts"), "reb": e.get("reb"), "ast": e.get("ast"),
                      "stl": e.get("stl"), "blk": e.get("blk"), "fgm": e.get("fgm"),
                      "fga": e.get("fga"), "tpm": e.get("tpm"), "tpa": e.get("tpa"),
                      "ftm": e.get("ftm"), "fta": e.get("fta"),
                      "oreb": None, "dreb": None, "foul": None, "to": None}
            counts = {"pts": int(e.get("appearances", 0) or 0),
                      "reb": int(e.get("reb_games", 0) or 0),
                      "ast": int(e.get("ast_games", 0) or 0),
                      "stl": bg, "blk": bg, "fgm": bg, "fga": bg, "tpm": bg,
                      "tpa": bg, "ftm": bg, "fta": bg,
                      "oreb": 0, "dreb": 0, "foul": 0, "to": 0}
            raw = {"games": int(e.get("appearances", 0) or 0), "totals": totals, "counts": counts,
                   "pts_shooting": e.get("box_pts", 0) or 0,
                   "gmsc_sum": 0, "gmsc_count": 0, "fp_sum": 0, "fp_count": 0,
                   "pm_sum": 0, "pm_count": 0, "mp_sum": 0, "mp_count": 0}
            block = display_block(raw)
            block.update({"season": "external", "season_label": label, "team": team,
                          "sort_date": sort_date, "jersey": None, "external": True})
            out.setdefault(name, []).append(block)
    return out


# stats that get a career/season "game high" (BBref-style), with display labels
HIGH_KEYS = [("pts", "Points"), ("reb", "Rebounds"), ("ast", "Assists"),
             ("stl", "Steals"), ("blk", "Blocks"), ("tpm", "3-pointers"),
             ("fp", "Fantasy"), ("gmsc", "Game Score")]


def compute_highs(entries):
    """Best single-game value for each tracked stat over (game, line) entries, with
    the game it first happened in and how many games tied that high. Skips stats a
    game didn't record. `entries` is in date order, so the linked game is the
    earliest time the high was reached."""
    out = {}
    for key, _ in HIGH_KEYS:
        vals = []
        for g, p in entries:
            v = p.get(key)
            if v is not None:
                vals.append((g, round(v, 1) if isinstance(v, float) else v))
        if not vals:
            continue
        best_val = max(v for _, v in vals)
        matches = [g for g, v in vals if v == best_val]
        g0 = matches[0]
        out[key] = {"value": best_val, "game_id": g0["id"], "opponent": g0["opponent"],
                    "date_disp": g0["date_disp"], "count": len(matches)}
    return out


def usage_rate(entries):
    """Approximate USG% over a player's fully-tracked games: the share of the
    team's scoring possessions a player used while on the floor, minute-adjusted.
    USG% = 100·(FGA + 0.44·FTA + TOV)·(TmMP/5) / (MP·(TmFGA + 0.44·TmFTA + TmTOV)).
    Team minutes for a game = the sum of all SJB players' minutes (5 on court at
    all times), so TmMP/5 is the game length."""
    pmp = pfga = pfta = pto = 0.0
    tfga = tfta = tto = tmp = 0.0
    for g, p in entries:
        tl = g.get("team_line") or {}
        if p.get("fga") is None or p.get("min") is None or tl.get("fga") is None:
            continue
        pmp += p["min"]; pfga += p["fga"]; pfta += (p.get("fta") or 0); pto += (p.get("to") or 0)
        tfga += tl["fga"]; tfta += (tl.get("fta") or 0); tto += (tl.get("to") or 0)
        tmp += sum((q["min"] or 0) for q in g["box_us"] if q.get("min") is not None)
    denom = pmp * (tfga + 0.44 * tfta + tto)
    if not denom:
        return None
    return round(100 * (pfga + 0.44 * pfta + pto) * (tmp / 5) / denom, 1)


def split_group(label, rows):
    """A splits row (BBref player splits): games, W-L-D and headline averages over
    a subset of a player's game log. Averages skip games that didn't track a stat."""
    def avg(k):
        vals = [r[k] for r in rows if r.get(k) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None
    return {
        "label": label, "g": len(rows),
        "w": sum(1 for r in rows if r["result"] == "W"),
        "l": sum(1 for r in rows if r["result"] == "L"),
        "d": sum(1 for r in rows if r["result"] == "D"),
        "pts": avg("pts"), "reb": avg("reb"), "ast": avg("ast"), "gmsc": avg("gmsc"),
    }


MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def compute_splits(log):
    """Player splits by result, by opponent and by month — all from the game log."""
    by_result = []
    for res, lab in (("W", "Wins"), ("L", "Losses"), ("D", "Draws")):
        rows = [r for r in log if r["result"] == res]
        if rows:
            by_result.append(split_group(lab, rows))

    opps = {}
    for r in log:
        opps.setdefault(r["opponent"], []).append(r)
    by_opponent = [split_group(opp, rows) for opp, rows in opps.items()]
    by_opponent.sort(key=lambda s: (-s["g"], s["label"]))

    months = {}
    for r in log:
        key = r["date"][:7]
        months.setdefault(key, []).append(r)
    by_month = []
    for key in sorted(months):
        y, m = key.split("-")
        by_month.append(split_group(f"{MONTH_ABBR[int(m)]} {y}", months[key]))

    # regular season vs finals — only shown when the player has a playoff game,
    # so an ordinary log isn't cluttered with a pointless one-row split.
    reg = [r for r in log if not r.get("stage")]
    post = [r for r in log if r.get("stage")]
    by_phase = []
    if post:
        if reg:
            by_phase.append(split_group("Regular season", reg))
        by_phase.append(split_group("Playoffs", post))

    return {"by_result": by_result, "by_opponent": by_opponent,
            "by_month": by_month, "by_phase": by_phase}


def build_players(games):
    meta = load_player_meta()
    external = load_external_seasons()
    logs = {}
    for g in games:
        for p in g["box_us"]:
            e = logs.setdefault(p["name"], [])
            e.append((g, p))

    # season display order, oldest first (matches the game order)
    season_order = []
    for g in games:
        if g["season"] not in season_order:
            season_order.append(g["season"])
    season_names = {g["season"]: g["season_label"] for g in games}

    players = []
    for name, entries in logs.items():
        entries.sort(key=lambda ep: ep[0]["date"])
        lines = [p for _, p in entries]
        n = len(lines)
        career = split_stats(lines)
        jersey = entries[-1][1]["jersey"]
        # best game by Game Score where it exists, else by points (partial games
        # have no Game Score)
        best = max(entries, key=lambda ep: (ep[1]["gmsc"] if ep[1]["gmsc"] is not None else -999,
                                            ep[1]["pts"] or 0))

        # per-season splits (SJB), plus any other-team seasons, oldest first
        seasons = []
        for sk in season_order:
            s_entries = [(g, p) for g, p in entries if g["season"] == sk]
            if not s_entries:
                continue
            block = split_stats([p for _, p in s_entries])
            block["season"] = sk
            block["season_label"] = season_names[sk]
            block["jersey"] = s_entries[-1][1]["jersey"]
            block["team"] = TEAM_NAME
            block["sort_date"] = min(g["date"] for g, _ in s_entries)
            block["usg"] = usage_rate(s_entries)
            block["highs"] = compute_highs(s_entries)
            seasons.append(block)

        ext_blocks = external.get(name, [])
        seasons = sorted(seasons + ext_blocks, key=lambda b: b.get("sort_date", ""))

        # full career folds in the external seasons (BBref-style, spans teams);
        # `career` stays SJB-only and feeds the leaderboards / players index.
        career_raw = career["_raw"]
        for eb in ext_blocks:
            career_raw = combine_raw(career_raw, eb["_raw"])
        career_full = display_block(career_raw)
        career_full.update({"season_label": "Career", "jersey": jersey})
        career_full["usg"] = usage_rate(entries)
        teams = {b.get("team", TEAM_NAME) for b in seasons}

        log = []
        for g, p in entries:
            log.append({
                "game_id": g["id"], "date": g["date"], "date_disp": g["date_disp"],
                "round": g.get("round"), "stage": g.get("stage"),
                "season": g["season"], "season_label": g["season_label"],
                "opponent": g["opponent"], "result": g["result"],
                "us": g["us"], "them": g["them"],
                "min": p["min"], "pts": p["pts"],
                "oreb": p["oreb"], "dreb": p["dreb"], "reb": p["reb"], "ast": p["ast"],
                "stl": p["stl"], "blk": p["blk"], "to": p["to"], "foul": p["foul"],
                "fgm": p["fgm"], "fga": p["fga"], "tpm": p["tpm"], "tpa": p["tpa"],
                "ftm": p["ftm"], "fta": p["fta"],
                "fg_pct": p["fg_pct"], "tp_pct": p["tp_pct"], "ft_pct": p["ft_pct"],
                "gmsc": p["gmsc"], "fp": p["fp"], "plus_minus": p["plus_minus"],
            })
        info = meta.get(name, {})
        meta_jersey = info.get("jersey")
        players.append({
            "slug": slugify(name), "name": name,
            "full_name": info.get("full_name") or FULL_NAMES.get(name, name),
            "position": info.get("position") or None,
            "nickname": info.get("nickname") or None,
            # auto-derived jersey from the box scores (unstable; #99 for guests) feeds
            # the inline player links. A number set in players.json overrides it AND is
            # the only thing shown as "No." on the profile header (via "number").
            "jersey": meta_jersey if meta_jersey is not None else jersey,
            "number": meta_jersey,
            "core": name in CORE_NAMES,
            "games": n, "small_sample": n < 2,
            "num_seasons": len(seasons),
            "multi_team": len(teams) > 1,
            "seasons": seasons,
            "career": career_full,
            # SJB-only career kept at top level (leaderboards, players index, back-compat)
            "totals": career["totals"],
            "averages": career["averages"],
            "fg_pct": career["fg_pct"], "tp_pct": career["tp_pct"], "ft_pct": career["ft_pct"],
            "efg": career["efg"], "ts": career["ts"],
            "mp_avg": career["mp_avg"], "mp_total": career["mp_total"],
            "gmsc_total": career["gmsc_total"], "gmsc_avg": career["gmsc_avg"],
            "fp_total": career["fp_total"], "fp_avg": career["fp_avg"],
            "plus_minus_total": career["plus_minus_total"],
            "plus_minus_avg": career["plus_minus_avg"],
            "best_game": {"game_id": best[0]["id"], "opponent": best[0]["opponent"],
                          "date_disp": best[0]["date_disp"], "gmsc": best[1]["gmsc"],
                          "pts": best[1]["pts"]},
            "career_highs": compute_highs(entries),
            "splits": compute_splits(log),
            "trend": [p["pts"] for _, p in entries],
            "gmsc_trend": [p["gmsc"] for _, p in entries],
            "log": log,
        })
    players.sort(key=lambda p: (-p["totals"]["pts"], p["name"]))
    return players


# Minimum games a player must have (within the scope being viewed — all-time or
# a single season) to qualify for the Leaders lists. Keeps one- and two-game
# cameos off the leaderboards. Change this one number to retune the cutoff.
MIN_LEADER_GAMES = 3


def build_leaders(players):
    def board(key, fn, min_games=MIN_LEADER_GAMES, hi=True):
        pool = [p for p in players if p["games"] >= min_games and fn(p) is not None]
        pool.sort(key=lambda p: fn(p), reverse=hi)
        return [{"slug": p["slug"], "name": p["name"], "full_name": p["full_name"],
                 "games": p["games"], "small_sample": p["small_sample"],
                 "value": fn(p)} for p in pool[:6]]
    return {
        "ppg": board("ppg", lambda p: p["averages"]["pts"]),
        "rpg": board("rpg", lambda p: p["averages"]["reb"]),
        "apg": board("apg", lambda p: p["averages"]["ast"]),
        "spg": board("spg", lambda p: p["averages"]["stl"]),
        "bpg": board("bpg", lambda p: p["averages"]["blk"]),
        "fp": board("fp", lambda p: p["fp_avg"]),
        "gmsc": board("gmsc", lambda p: p["gmsc_avg"]),
        "plus_minus": board("plus_minus", lambda p: p["plus_minus_avg"]),
    }


def season_leader_entries(players, season_key):
    """Each player's per-season SJB stat line, shaped for build_leaders — for the
    season-scoped leaderboards. External (other-team) seasons are excluded."""
    out = []
    for p in players:
        blk = next((s for s in p["seasons"]
                    if s.get("season") == season_key and not s.get("external")), None)
        if not blk:
            continue
        out.append({"slug": p["slug"], "name": p["name"], "full_name": p["full_name"],
                    "games": blk["games"], "small_sample": blk["games"] < 2,
                    "averages": blk["averages"], "fp_avg": blk["fp_avg"],
                    "gmsc_avg": blk["gmsc_avg"], "plus_minus_avg": blk["plus_minus_avg"]})
    return out


def build_team(games):
    # Record, score and points-for/against span ALL games (points are always
    # known). Shooting, four factors and ratings use only fully-tracked games —
    # a points-only game has no attempts to pool in.
    n_all = len(games)
    # forfeits count in the record but have no real score — keep them out of
    # points-for/against and every average/rating.
    scored = [g for g in games if g.get("level") != "forfeit"]
    n_scored = len(scored)
    tracked = [g for g in games if g.get("level", "full") == "full"]
    n = len(tracked)
    n_forfeit = n_all - n_scored
    team_lines = [g["team_line"] for g in tracked]
    opp_lines = [g["opp_line"] for g in tracked]
    tot, _ = accumulate(team_lines)
    otot, _ = accumulate(opp_lines)
    poss = sum(possessions(l) for l in team_lines)
    opp_poss = sum(possessions(l) for l in opp_lines)
    w = sum(1 for g in games if g["result"] == "W")
    loss = sum(1 for g in games if g["result"] == "L")
    d = sum(1 for g in games if g["result"] == "D")
    pts_for = sum(g["us"] for g in scored)
    pts_against = sum(g["them"] for g in scored)

    # season five-man lineups, aggregated across games
    lagg = {}
    for g in games:
        for l in g.get("lineups", []):
            key = tuple(l["players"])
            e = lagg.setdefault(key, {"min": 0.0, "for": 0, "against": 0})
            e["min"] += l["min"]
            e["for"] += l["for"]
            e["against"] += l["against"]
    lineups = [{"players": list(k), "min": round(v["min"], 1), "for": v["for"],
                "against": v["against"], "plus_minus": v["for"] - v["against"]}
               for k, v in lagg.items()]
    lineups.sort(key=lambda l: -l["min"])

    # head-to-head record vs each opponent (record spans all games incl. forfeits;
    # points averages use scored games only)
    h2h = {}
    for g in games:
        e = h2h.setdefault(g["opponent"], {
            "opponent": g["opponent"], "opponent_slug": g.get("opponent_slug"),
            "w": 0, "l": 0, "d": 0, "g": 0, "pf": 0, "pa": 0, "scored": 0, "last_id": g["id"]})
        e["g"] += 1
        e["w" if g["result"] == "W" else "l" if g["result"] == "L" else "d"] += 1
        if g.get("level") != "forfeit":
            e["pf"] += g["us"]; e["pa"] += g["them"]; e["scored"] += 1
        e["last_id"] = g["id"]
    head_to_head = []
    for e in h2h.values():
        s = e["scored"]
        head_to_head.append({**e,
            "ppg_for": round(e["pf"] / s, 1) if s else None,
            "ppg_against": round(e["pa"] / s, 1) if s else None,
            "margin": round((e["pf"] - e["pa"]) / s, 1) if s else None})
    head_to_head.sort(key=lambda x: (-x["g"], x["opponent"]))

    # scoring by half, averaged over fully-tracked games that carry half splits —
    # shows whether the team starts fast or finishes strong
    hs_acc = {"h1_us": 0, "h1_them": 0, "h2_us": 0, "h2_them": 0, "n": 0}
    for g in tracked:
        hd = {x["half"]: x for x in (g.get("half_scores") or [])}
        if 1 in hd and 2 in hd:
            hs_acc["h1_us"] += hd[1]["us"]; hs_acc["h1_them"] += hd[1]["them"]
            hs_acc["h2_us"] += hd[2]["us"]; hs_acc["h2_them"] += hd[2]["them"]; hs_acc["n"] += 1
    scoring_by_half = None
    if hs_acc["n"]:
        nn = hs_acc["n"]
        scoring_by_half = {
            "games": nn,
            "h1": {"us": round(hs_acc["h1_us"] / nn, 1), "them": round(hs_acc["h1_them"] / nn, 1)},
            "h2": {"us": round(hs_acc["h2_us"] / nn, 1), "them": round(hs_acc["h2_them"] / nn, 1)},
        }

    # margins & results (scored games only)
    def gref(g):
        return {"margin": g["margin"], "opponent": g["opponent"],
                "game_id": g["id"], "date_disp": g["date_disp"]}
    wins_s = [g for g in scored if g["result"] == "W"]
    losses_s = [g for g in scored if g["result"] == "L"]
    close = [g for g in scored if abs(g["margin"]) <= 5]
    blowout = [g for g in scored if g["margin"] >= 15]
    results = {
        "avg_margin": round((pts_for - pts_against) / n_scored, 1) if n_scored else None,
        "best_win": gref(max(wins_s, key=lambda g: g["margin"])) if wins_s else None,
        "worst_loss": gref(min(losses_s, key=lambda g: g["margin"])) if losses_s else None,
        "close": {"g": len(close),
                  "w": sum(1 for g in close if g["result"] == "W"),
                  "l": sum(1 for g in close if g["result"] == "L"),
                  "d": sum(1 for g in close if g["result"] == "D")},
        "blowout_wins": sum(1 for g in blowout if g["result"] == "W"),
    }

    reliable_games = [g for g in tracked if g["opp_reliable"]]
    return {
        "name": TEAM_NAME,
        "record": {"w": w, "l": loss, "d": d},
        "head_to_head": head_to_head,
        "scoring_by_half": scoring_by_half,
        "results": results,
        "games_played": n_all, "games_tracked": n,
        "games_scored": n_scored, "games_forfeit": n_forfeit,
        "pts_for": pts_for, "pts_against": pts_against,
        "ppg_for": round(pts_for / n_scored, 1) if n_scored else 0,
        "ppg_against": round(pts_against / n_scored, 1) if n_scored else 0,
        "totals": tot, "opp_totals": otot,
        "per_game": averages(tot, {k: n for k in tot}), "opp_per_game": averages(otot, {k: n for k in otot}),
        "fg_pct": pct(tot["fgm"], tot["fga"]), "tp_pct": pct(tot["tpm"], tot["tpa"]),
        "ft_pct": pct(tot["ftm"], tot["fta"]),
        "opp_fg_pct": pct(otot["fgm"], otot["fga"]), "opp_tp_pct": pct(otot["tpm"], otot["tpa"]),
        "advanced": {
            "off_rtg": round(100 * tot["pts"] / poss, 1) if poss else None,
            "def_rtg": round(100 * otot["pts"] / opp_poss, 1) if opp_poss else None,
            "net_rtg": round(100 * tot["pts"] / poss - 100 * otot["pts"] / opp_poss, 1) if poss and opp_poss else None,
            "pace": round((poss + opp_poss) / (2 * n), 1) if n else None,
            "pct_pts_from_3": round(100 * 3 * tot["tpm"] / tot["pts"], 1) if tot["pts"] else None,
        },
        "four_factors": four_factors(tot, otot["dreb"]),
        "opp_four_factors": four_factors(otot, tot["dreb"]),
        "tov_margin": otot["to"] - tot["to"],
        "lineups": lineups[:10],
        "defense_rows": [
            {"game_id": g["id"], "opponent": g["opponent"], "date_disp": g["date_disp"],
             "date": g["date"], "partial": g.get("partial", False),
             "opp_pts": g["them"], "def_rtg": g["ratings"].get("def"),
             "opp_poss": g["opp_poss"], "tov_forced": g["opp_line"]["to"],
             "tov_margin": g["tov_margin"], "reliable": g["opp_reliable"]}
            for g in scored],
        "reliable_count": len(reliable_games),
    }


# --- awards ----------------------------------------------------------------
# A computed (not voted) awards layer, Basketball-Reference style. Regular season
# only (semi-finals/forfeits excluded). Everything here is transparent so the site
# can show the formula: MVP is value per team game, Spark is value per minute,
# Clutch is real crunch-time scoring from the play-by-play.

AW_MIN_GAMES = 3            # a candidate must have at least this many tracked games
AW_MIN_SHARE = 1 / 3.0     # ...and have played at least this share of the team's games
AW_REL_MIN_GAMES = 5       # Mr. Reliable needs more games — a swing over 3 games is noise
CLUTCH_SECS = 300          # "clutch" = last 5:00 of the final half...
CLUTCH_MARGIN = 5          # ...with the score within 5 points at the basket


def _aw_reg(g):
    """A regular-season game that carries player stats (not a final, not a forfeit)."""
    return not g.get("stage") and g.get("level") != "forfeit"


def _ts_pct(pts, fga, fta):
    tsa = fga + 0.44 * fta
    return round(100.0 * pts / (2 * tsa), 1) if tsa > 0 else None


def _clutch_points(g):
    """{player: clutch points} for one game, from the play-by-play: SJB makes in the
    last CLUTCH_SECS of the final half while the margin was within CLUTCH_MARGIN."""
    out = {}
    feed = g.get("pbp") or []
    if not feed:
        return out
    last_half = max((e["half"] for e in feed), default=1)
    for e in feed:
        if not e.get("score") or e.get("team") != "us":
            continue
        if e.get("half") != last_half or (e.get("clock") or 9999) > CLUTCH_SECS:
            continue
        after = e["us"] - e["them"]
        before = (e["us"] - e["pts"]) - e["them"]
        if min(abs(after), abs(before)) <= CLUTCH_MARGIN:
            out[e["who"]] = out.get(e["who"], 0) + e["pts"]
    return out


def _aw_blank(name):
    return {"name": name, "slug": slugify(name), "g": 0, "min": 0.0, "gmsc": 0.0,
            "pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0, "fga": 0, "fta": 0,
            "pm": 0, "clutch": 0, "pra_log": []}


def _aw_aggregate(games):
    """season key -> {team_games, players: {name: totals}} over regular-season games.
    A player line counts only when the game is fully tracked (has a Game Score)."""
    seasons = {}
    for g in games:
        if not _aw_reg(g):
            continue
        blk = seasons.setdefault(g["season"], {"team_games": 0, "players": {}})
        tracked = False
        for p in g["box_us"]:
            pts, reb, ast = p.get("pts"), p.get("reb"), p.get("ast")
            # consistency log (for Mr. Reliable): every regular-season game that has
            # points, rebounds AND assists recorded — including a box-only game that
            # carries no Game Score. Kept separate from the Game-Score-gated totals.
            if pts is not None and reb is not None and ast is not None:
                blk["players"].setdefault(p["name"], _aw_blank(p["name"]))["pra_log"].append((pts, reb, ast))
            if p.get("gmsc") is None:
                continue
            tracked = True
            d = blk["players"].setdefault(p["name"], _aw_blank(p["name"]))
            d["g"] += 1
            d["min"] += p["min"] or 0
            d["gmsc"] += p["gmsc"]
            for k in ("pts", "reb", "ast", "stl", "blk", "fga", "fta"):
                d[k] += p.get(k) or 0
            d["pm"] += p.get("plus_minus") or 0
        if tracked:
            blk["team_games"] += 1
        for name, pts in _clutch_points(g).items():
            d = blk["players"].setdefault(name, _aw_blank(name))
            d["clutch"] += pts
    return seasons


def _aw_rows(blk):
    """Per-player display metrics for one season block."""
    tg = blk["team_games"] or 1
    rows = []
    for d in blk["players"].values():
        g = d["g"]
        rows.append({
            "name": d["name"], "slug": d["slug"], "g": g, "team_games": blk["team_games"],
            "mpg": round(d["min"] / g, 1) if g else 0.0,
            "gmsc_avg": round(d["gmsc"] / g, 1) if g else 0.0,
            "pts": round(d["pts"] / g, 1) if g else 0.0,
            "reb": round(d["reb"] / g, 1) if g else 0.0,
            "ast": round(d["ast"] / g, 1) if g else 0.0,
            "stl": round(d["stl"] / g, 1) if g else 0.0,
            "blk": round(d["blk"] / g, 1) if g else 0.0,
            "pm": round(d["pm"] / g, 1) if g else 0.0,
            "ts": _ts_pct(d["pts"], d["fga"], d["fta"]),
            "def": round((d["stl"] + d["blk"]) / g, 1) if g else 0.0,
            "per36": round(d["gmsc"] / d["min"] * 36, 1) if d["min"] > 0 else 0.0,
            "mvp": round(d["gmsc"] / tg, 2),              # value per team game
            "avail": round(g / tg, 2) if tg else 0.0,
            "clutch": d["clutch"],
            "min_total": round(d["min"]),
        })
    return rows


def compute_awards(games, seasons_meta):
    order = [s["key"] for s in seasons_meta]
    labels = {s["key"]: s["label"] for s in seasons_meta}
    agg = _aw_aggregate(games)
    derived = {sk: _aw_rows(blk) for sk, blk in agg.items()}
    has_stage = {g["season"] for g in games if g.get("stage")}

    honors = {}

    def add_honor(sk, winner, award):
        honors.setdefault(winner["name"], []).append(
            {"season": sk, "label": labels.get(sk, sk), "award": award})

    def eligible(r):
        return r["g"] >= AW_MIN_GAMES and r["g"] >= r["team_games"] * AW_MIN_SHARE

    def pick(rows, key, extra_key=None, need_positive=False, pool=None):
        cand = pool if pool is not None else [r for r in rows if eligible(r)]
        cand = [r for r in cand if r.get(key) is not None]
        if need_positive:
            cand = [r for r in cand if r[key] > 0]
        cand = sorted(cand, key=lambda r: (-r[key], -(r.get(extra_key) or 0) if extra_key else 0))
        return cand

    out_seasons = {}
    for idx, sk in enumerate(order):
        rows = derived.get(sk)
        if not rows:
            continue
        is_final = sk != order[-1] or sk in has_stage
        elig = [r for r in rows if eligible(r)]
        awards = {}

        def with_share(cands, key):
            """Attach a BBref-style 'award share' to each candidate: its metric as a
            % of the whole field's positive total. Copies the rows so each award
            carries its own share without clobbering another's."""
            total = sum(max(c.get(key) or 0, 0) for c in cands) or 1
            out = []
            for c in cands:
                d = dict(c)
                d["share"] = round(100.0 * max(c.get(key) or 0, 0) / total, 1)
                out.append(d)
            return out

        def award(name, short, cand, key, final=is_final, s=sk):
            if cand:
                cand = with_share(cand, key)
                awards[name] = {"winner": cand[0], "candidates": cand[:5]}
                if final:
                    add_honor(s, cand[0], short)

        award("mvp", "MVP", pick(elig, "mvp", "gmsc_avg"), "mvp")
        award("dpoy", "DPOY", pick(elig, "def", "stl"), "def")
        award("ironman", "Durability", pick(elig, "min_total", "g"), "min_total")
        award("clutch", "Clutch", pick(rows, "clutch", "pts", need_positive=True, pool=rows), "clutch")

        if idx > 0:                                   # Most Improved needs a prior season
            # MIP = the biggest all-round jump in Game Score per game. Game Score already
            # weighs scoring, shooting efficiency, rebounds (0.7/0.3), assists (0.7),
            # steals (1.0), blocks (0.7), turnovers and fouls, so a leap in ANY facet —
            # a scoring breakout, a passing surge, a defensive step-up — is captured in one
            # number. Change in availability (share of games played) is only a tiebreaker,
            # never a driver.
            prev = {r["name"]: r for r in derived.get(order[idx - 1], [])}
            mip = []
            for r in elig:
                pr = prev.get(r["name"])
                if not (pr and pr["g"] >= AW_MIN_GAMES):
                    continue
                score = r["gmsc_avg"] - pr["gmsc_avg"]
                mip.append({**r, "mip_score": round(score, 1),
                            "d_avail": round((r["avail"] - pr["avail"]) * 100),
                            "prev_gmsc": pr["gmsc_avg"], "prev_ppg": pr["pts"]})
            mip = sorted([m for m in mip if m["mip_score"] > 0],
                         key=lambda m: (-m["mip_score"], -m["d_avail"]))
            award("mip", "Most Improved", mip, "mip_score")

        # Mr. Reliable: steadiest all-round. Game-to-game swing (standard deviation)
        # in points, rebounds and assists, each weighed against that category's typical
        # size across the candidate pool, then averaged — so no category dominates and a
        # low-volume line isn't blown up the way a per-player ratio would. Lower swing is
        # steadier; the award ranks (and takes its share) on an inverted rating so it fits
        # the higher-is-better share framework like every other award.
        rel_pool = [r for r in elig
                    if len(agg[sk]["players"][r["name"]]["pra_log"]) >= AW_REL_MIN_GAMES]
        if rel_pool:
            logs = {r["name"]: agg[sk]["players"][r["name"]]["pra_log"] for r in rel_pool}
            allp = [t[0] for lg in logs.values() for t in lg]
            allr = [t[1] for lg in logs.values() for t in lg]
            alla = [t[2] for lg in logs.values() for t in lg]
            typ_p = (sum(allp) / len(allp)) or 1
            typ_r = (sum(allr) / len(allr)) or 1
            typ_a = (sum(alla) / len(alla)) or 1
            rel = []
            for r in rel_pool:
                lg = logs[r["name"]]
                sp = _stdev_raw([t[0] for t in lg])
                sr = _stdev_raw([t[1] for t in lg])
                sa = _stdev_raw([t[2] for t in lg])
                composite = (sp / typ_p + sr / typ_r + sa / typ_a) / 3 * 100
                rel.append({**r, "rel_swing": round(composite, 1),
                            "rel_rating": round(max(0.0, 100 - composite), 1), "rel_g": len(lg),
                            "sw_pts": round(sp, 1), "sw_reb": round(sr, 1), "sw_ast": round(sa, 1)})
            rel.sort(key=lambda m: -m["rel_rating"])
            award("reliable", "Mr. Reliable", rel, "rel_rating")

        def title(key):
            c = pick(elig, key)
            return c[0] if c else None
        awards["titles"] = {"scoring": title("pts"), "rebounding": title("reb"),
                            "playmaking": title("ast"), "efficiency": title("ts")}

        out_seasons[sk] = {"label": labels.get(sk, sk), "is_final": is_final,
                           "team_games": rows[0]["team_games"], "awards": awards}

    # --- all-time / career (regular season, summed across seasons) ---
    career, total_tg = {}, 0
    for blk in agg.values():
        total_tg += blk["team_games"]
        for d in blk["players"].values():
            c = career.setdefault(d["name"], {"name": d["name"], "slug": d["slug"],
                                              "g": 0, "min": 0.0, "gmsc": 0.0, "pts": 0,
                                              "stl": 0, "blk": 0, "clutch": 0})
            for k in ("g", "min", "gmsc", "pts", "stl", "blk", "clutch"):
                c[k] += d[k]
    tg = total_tg or 1
    car = [{"name": c["name"], "slug": c["slug"], "g": c["g"],
            "mvp": round(c["gmsc"] / tg, 2), "gmsc_avg": round(c["gmsc"] / c["g"], 1) if c["g"] else 0,
            "clutch": c["clutch"], "stlblk": c["stl"] + c["blk"],
            "def": round((c["stl"] + c["blk"]) / c["g"], 1) if c["g"] else 0}
           for c in career.values()]
    career_leaders = {
        "mvp": sorted(car, key=lambda r: -r["mvp"])[:5],
        "clutch": sorted([r for r in car if r["clutch"] > 0], key=lambda r: -r["clutch"])[:5],
        "defense": sorted(car, key=lambda r: -r["stlblk"])[:5],
    }
    winners = []
    for sk in order:
        s = out_seasons.get(sk)
        if not s or not s["is_final"]:
            continue
        aw = s["awards"]
        winners.append({"label": s["label"], **{k: aw.get(k, {}).get("winner")
                        for k in ("mvp", "mip", "dpoy", "clutch", "ironman", "reliable")}})

    awards_data = {"order": order, "seasons": out_seasons,
                   "all_time": {"career_leaders": career_leaders, "winners": winners,
                                "team_games": total_tg}}
    return awards_data, honors


# --- frivolities -----------------------------------------------------------
# A "did you know" grab-bag, BasketballGM-style: niche, fun, sometimes asinine
# cuts of the data. Each card is {section, id, title, note, items}; an item is
# {players?: [{name,slug}], game?: {id,label}, label?, val, sub?, join?}. The
# frontend renders them generically, so cards can be pruned freely.

def _fp(name):
    return {"name": name, "slug": slugify(name)}


def _last(name):
    return name.split()[-1]


def _stdev_raw(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


def _stdev(xs):
    return round(_stdev_raw(xs), 1)


def compute_frivolities(games, players):
    from collections import Counter, defaultdict
    cards = []

    def card(section, cid, title, note, items):
        items = [it for it in items if it]
        if items:
            cards.append({"section": section, "id": cid, "title": title,
                          "note": note, "items": items})

    def it(val, players=None, game=None, label=None, sub="", join=" + "):
        d = {"val": val, "sub": sub, "join": join}
        if players:
            d["players"] = players
        if game:
            d["game"] = game
        if label:
            d["label"] = label
        return d

    real = [g for g in games if g.get("level") != "forfeit"]           # has real scores
    ordered = sorted(games, key=lambda g: g["date"])
    glabel = lambda g: f"{g['date_disp']} vs {g['opponent']}"
    def glink(g):
        return {"id": g["id"], "label": glabel(g)}

    # ---- Chemistry & connections -------------------------------------------
    hook = Counter()
    for g in games:
        for e in (g.get("pbp") or []):
            if e.get("assist") and e.get("team") == "us":
                hook[(e["assist"], e["who"])] += 1
    card("Chemistry", "hookups", "Favourite link-ups", "most assists from one player to another",
         [it(str(c), players=[_fp(a), _fp(s)], join=" → ") for (a, s), c in hook.most_common(8)])

    pair = defaultdict(lambda: [0.0, 0])      # (a,b) -> [minutes, plus_minus]
    five = defaultdict(lambda: [0.0, 0])
    five_season = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for g in games:
        for l in (g.get("lineups") or []):
            ps = tuple(sorted(l["players"]))
            five[ps][0] += l["min"]; five[ps][1] += l["plus_minus"]
            five_season[g["season"]][ps][0] += l["min"]; five_season[g["season"]][ps][1] += l["plus_minus"]
            for i in range(len(ps)):
                for j in range(i + 1, len(ps)):
                    k = (ps[i], ps[j])
                    pair[k][0] += l["min"]; pair[k][1] += l["plus_minus"]
    duos = sorted([(k, v) for k, v in pair.items() if v[0] >= 25], key=lambda x: -x[1][1])
    card("Chemistry", "best-duos", "Best duos", "on-court +/- of a pair together (25+ min)",
         [it(f"{v[1]:+d}", players=[_fp(k[0]), _fp(k[1])], sub=f"{v[0]:.0f} min") for k, v in duos[:5]])

    fives = sorted([(k, v) for k, v in five.items() if v[0] >= 8 and len(k) == 5], key=lambda x: -x[1][1])
    card("Chemistry", "best-fives", "Best five-man units", "aggregated lineup +/- (8+ min, small samples)",
         [it(f"{v[1]:+d}", players=[_fp(p) for p in k], join=" · ", sub=f"{v[0]:.0f} min") for k, v in fives[:4]])
    seas_items = []
    for sk in sorted(five_season):
        fs = sorted([(k, v) for k, v in five_season[sk].items() if v[0] >= 6 and len(k) == 5], key=lambda x: -x[1][1])
        if fs:
            k, v = fs[0]
            seas_items.append(it(f"{v[1]:+d}", players=[_fp(p) for p in k], join=" · ",
                                 sub=f"{season_label(sk)} · {v[0]:.0f} min"))
    card("Chemistry", "fives-by-season", "Top lineup per season", "", seas_items)

    insep = sorted([(k, v) for k, v in pair.items()], key=lambda x: -x[1][0])
    card("Chemistry", "inseparable", "Inseparable", "the pairs who share the floor most",
         [it(f"{v[0]:.0f} min", players=[_fp(k[0]), _fp(k[1])]) for k, v in insep[:3]])

    # ---- Individual oddities ------------------------------------------------
    log_of = {p["name"]: p["log"] for p in players}

    # (Mr. Reliable — steadiest all-round line — is now a season award on the Awards page.)

    # double-doubles
    dd = Counter()
    for p in players:
        for l in p["log"]:
            if sum(1 for v in (l.get("pts"), l.get("reb"), l.get("ast")) if (v or 0) >= 10) >= 2:
                dd[p["name"]] += 1
    card("Individuals", "double-doubles", "Double doubles", "games with 10+ in two of pts / reb / ast",
         [it(str(c), players=[_fp(nm)]) for nm, c in dd.most_common(6)])

    # best single games (GmSc) and scoring explosions (pts)
    alllines = []
    for p in players:
        for l in p["log"]:
            alllines.append((p["name"], l))
    best_g = sorted([x for x in alllines if x[1].get("gmsc") is not None], key=lambda x: -x[1]["gmsc"])[:6]
    card("Individuals", "best-games", "Career-best games", "",
         [it(f"{l['gmsc']:.1f} GmSc", players=[_fp(nm)], game={"id": l["game_id"], "label": f"vs {l['opponent']}"},
             sub=f"{l['pts']} pts") for nm, l in best_g])
    explode = sorted([x for x in alllines if x[1].get("pts") is not None], key=lambda x: -x[1]["pts"])[:6]
    card("Individuals", "explosions", "Most points in a game", "",
         [it(f"{l['pts']} pts", players=[_fp(nm)], game={"id": l["game_id"], "label": f"vs {l['opponent']}"}) for nm, l in explode])

    # longest iron-man streak (consecutive games played). The sequence is the
    # contested games only — forfeits weren't played by anyone, so they don't
    # break a run. A player "appeared" if the game has their minutes OR (for a
    # not-fully-scored game, where minutes aren't tracked) their points: being in
    # the box at all means they played.
    contested = [g for g in ordered if not g.get("forfeit")]
    gi = {g["id"]: i for i, g in enumerate(contested)}
    _appeared = lambda l: (l.get("min") or 0) > 0 or l.get("pts") is not None
    _gtag = lambda g: f"R{g['round']}" if g.get("round") else (g["stage"]["label"] if g.get("stage") else g["date_disp"])
    _slabel = lambda s: f"Season {s.split('-')[-1]}" if s else ""
    def _streak_span(bs, be):
        sg, eg = contested[bs], contested[be]
        if sg.get("season") and sg["season"] == eg["season"]:
            return f"{_gtag(sg)}–{_gtag(eg)}, {_slabel(sg['season'])}"
        return f"{sg['date_disp']} → {eg['date_disp']}"
    streaks = []
    for p in players:
        idxs = sorted(gi[l["game_id"]] for l in p["log"] if _appeared(l) and l["game_id"] in gi)
        best = run = 0
        best_start = best_end = run_start = prev = None
        for x in idxs:
            if prev is not None and x == prev + 1:
                run += 1
            else:
                run = 1; run_start = x
            if run > best:
                best, best_start, best_end = run, run_start, x
            prev = x
        if best >= 3:
            streaks.append((p["name"], best, best_start, best_end))
    streaks.sort(key=lambda x: -x[1])
    card("Individuals", "ironstreak", "Longest run of consecutive games played", "",
         [it(f"{c} games", players=[_fp(nm)], sub=_streak_span(bs, be)) for nm, c, bs, be in streaks[:4]])

    # plus/minus kings (career per-game, min 6 g)
    pm = [(p, p["plus_minus_avg"]) for p in players if p["games"] >= 6 and p.get("plus_minus_avg") is not None]
    pm.sort(key=lambda x: -x[1])
    card("Individuals", "pm", "Plus/minus kings", "best on-court margin per game (6+ games)",
         [it(f"{v:+.1f}", players=[_fp(p['name'])]) for p, v in pm[:5]])

    # foul trouble
    foul = []
    for p in players:
        ls = [l for l in p["log"] if l.get("foul") is not None]
        if len(ls) >= 5:
            fouts = sum(1 for l in ls if (l.get("foul") or 0) >= 5)
            foul.append((p["name"], round(sum(l["foul"] for l in ls) / len(ls), 1), fouts))
    foul.sort(key=lambda x: -x[1])
    card("Individuals", "fouls", "Foul magnets", "fouls per game (and times fouled out)",
         [it(f"{fpg}", players=[_fp(nm)], sub=(f"{fo} foul-out{'s' if fo != 1 else ''}" if fo else "")) for nm, fpg, fo in foul[:4]])

    # floor general vs giveaway-prone (AST:TO)
    ratio = []
    for p in players:
        a = sum(l.get("ast") or 0 for l in p["log"]); t = sum(l.get("to") or 0 for l in p["log"])
        if a + t >= 15:
            ratio.append((p["name"], a, t, round(a / t, 2) if t else a))
    ratio.sort(key=lambda x: -x[3])
    card("Individuals", "floor-general", "Floor generals", "best assist-to-turnover ratio",
         [it(f"{r}", players=[_fp(nm)], sub=f"{a} ast / {t} to") for nm, a, t, r in ratio[:3]] +
         [it(f"{r}", players=[_fp(nm)], sub=f"{a} ast / {t} to") for nm, a, t, r in ratio[::-1][:2]])

    # first blood (team's opening basket scorer)
    first = Counter()
    for g in games:
        for e in (g.get("pbp") or []):
            if e.get("score") and e.get("team") == "us":
                first[e["who"]] += 1
                break
    card("Individuals", "first-blood", "First blood", "who scores the team's opening basket most",
         [it(str(c), players=[_fp(nm)]) for nm, c in first.most_common(4)])

    # second-half specialist (share of own points scored in the final half)
    sh = defaultdict(lambda: [0, 0])     # name -> [2h pts, total pts]
    for g in games:
        feed = g.get("pbp") or []
        if not feed:
            continue
        lh = max(e["half"] for e in feed)
        for e in feed:
            if e.get("score") and e.get("team") == "us" and e.get("pts"):
                sh[e["who"]][1] += e["pts"]
                if e["half"] == lh:
                    sh[e["who"]][0] += e["pts"]
    secondhalf = sorted([(nm, v[0], v[1], round(100 * v[0] / v[1])) for nm, v in sh.items() if v[1] >= 30],
                        key=lambda x: -x[3])
    card("Individuals", "second-half", "Second-half merchants", "share of personal points scored after the break (30+ pts)",
         [it(f"{pct}%", players=[_fp(nm)], sub=f"{h2}/{tot} pts") for nm, h2, tot, pct in secondhalf[:4]])

    # downtown (most threes) and the charity stripe (most FTA)
    threes = sorted([(p["name"], sum(l.get("tpm") or 0 for l in p["log"])) for p in players], key=lambda x: -x[1])
    card("Individuals", "downtown", "Downtown", "most three-pointers made (career)",
         [it(str(c), players=[_fp(nm)]) for nm, c in threes[:4] if c])
    stocks = sorted([(p["name"], round((sum(l.get('stl') or 0 for l in p['log']) + sum(l.get('blk') or 0 for l in p['log'])) / max(p['games'], 1), 1)) for p in players if p["games"] >= 6], key=lambda x: -x[1])
    card("Individuals", "stocks", "Stocks per game", "steals + blocks",
         [it(f"{v}", players=[_fp(nm)]) for nm, v in stocks[:4]])

    # the microwave: most points in a single half (from the play-by-play)
    half_pts = []
    for g in games:
        feed = g.get("pbp") or []
        if not feed:
            continue
        agg = defaultdict(int)
        for e in feed:
            if e.get("score") and e.get("team") == "us" and e.get("pts"):
                agg[(e["who"], e["half"])] += e["pts"]
        for (nm, h), pts in agg.items():
            half_pts.append((pts, nm, h, g))
    half_pts.sort(key=lambda x: -x[0])
    card("Individuals", "microwave", "The microwave", "most points in a single half",
         [it(f"{pts} in H{h}", players=[_fp(nm)], game=glink(g)) for pts, nm, h, g in half_pts[:4]])

    # go-to scorer: most shot attempts per game (tracked games)
    goto = []
    for p in players:
        fgas = [l["fga"] for l in p["log"] if l.get("fga") is not None]
        if len(fgas) >= 6:
            goto.append((p["name"], round(sum(fgas) / len(fgas), 1), sum(fgas)))
    goto.sort(key=lambda x: -x[1])
    card("Individuals", "goto", "Go-to scorer", "most shot attempts per game (6+ tracked games)",
         [it(f"{fpg}", players=[_fp(nm)], sub=f"{tot} FGA") for nm, fpg, tot in goto[:4]])

    # living at the line: most free-throw attempts
    fta = sorted([(p["name"], sum(l.get("fta") or 0 for l in p["log"])) for p in players], key=lambda x: -x[1])
    card("Individuals", "freethrows", "Living at the line", "most free-throw attempts (career)",
         [it(f"{tot} FTA", players=[_fp(nm)]) for nm, tot in fta[:4] if tot])

    # iron lungs: most minutes played in a single game
    mins = []
    for p in players:
        for l in p["log"]:
            if l.get("min") is not None:
                mins.append((l["min"], p["name"], l))
    mins.sort(key=lambda x: -x[0])
    card("Individuals", "ironlungs", "Iron lungs", "most minutes played in a single game",
         [it(f"{m:g} min", players=[_fp(nm)], game={"id": l["game_id"], "label": f"vs {l['opponent']}"}) for m, nm, l in mins[:4]])

    # stat-sheet stuffer: games with a point, rebound, assist, steal AND block
    stuffer = Counter()
    for p in players:
        for l in p["log"]:
            if all((l.get(k) or 0) >= 1 for k in ("pts", "reb", "ast", "stl", "blk")):
                stuffer[p["name"]] += 1
    card("Individuals", "stuffer", "Stat-sheet stuffer", "games with a point, rebound, assist, steal AND block",
         [it(str(c), players=[_fp(nm)]) for nm, c in stuffer.most_common(5)])

    # double-digit streak: longest run of consecutive games scoring 10+
    ddstreak = []
    for p in players:
        best = run = 0
        for l in sorted(p["log"], key=lambda x: x["date"]):
            if (l.get("pts") or 0) >= 10:
                run += 1; best = max(best, run)
            else:
                run = 0
        if best >= 2:
            ddstreak.append((p["name"], best))
    ddstreak.sort(key=lambda x: -x[1])
    card("Individuals", "ddstreak", "Double-digit streak", "longest run of consecutive games scoring 10+",
         [it(f"{c} games", players=[_fp(nm)]) for nm, c in ddstreak[:4]])

    # ---- Game shape & team --------------------------------------------------
    def margin_extremes(g):
        feed = [e for e in (g.get("pbp") or []) if e.get("score")]
        if not feed:
            return None, None
        ms = [e["us"] - e["them"] for e in feed]
        return min(ms), max(ms)

    comebacks, collapses, backforth, wire = [], [], [], []
    for g in real:
        lo, hi = margin_extremes(g)
        if lo is None:
            continue
        if g["result"] == "W" and lo < 0:
            comebacks.append((g, -lo))
        if g["result"] == "L" and hi > 0:
            collapses.append((g, hi))
        feed = [e for e in (g.get("pbp") or []) if e.get("score")]
        changes, prev = 0, 0
        for e in feed:
            s = (1 if e["us"] > e["them"] else -1 if e["us"] < e["them"] else 0)
            if s and prev and s != prev:
                changes += 1
            if s:
                prev = s
        backforth.append((g, changes))
        if g["result"] == "W" and lo >= 0:
            wire.append(g)
    comebacks.sort(key=lambda x: -x[1]); collapses.sort(key=lambda x: -x[1]); backforth.sort(key=lambda x: -x[1])
    card("Game shape", "comebacks", "Biggest comebacks", "wins after falling furthest behind",
         [it(f"down {d}", game={"id": g["id"], "label": glabel(g)}, sub=f"won {g['us']}-{g['them']}") for g, d in comebacks[:4]])
    card("Game shape", "collapses", "Blown leads", "losses after leading by the most",
         [it(f"led by {d}", game={"id": g["id"], "label": glabel(g)}, sub=f"lost {g['us']}-{g['them']}") for g, d in collapses[:4]])
    card("Game shape", "backforth", "Back-and-forth-est", "most lead changes in a game",
         [it(f"{c} lead changes", game={"id": g["id"], "label": glabel(g)}, sub=f"{g['result']} {g['us']}-{g['them']}") for g, c in backforth[:3] if c])
    card("Game shape", "wire", "Wire-to-wire wins", "won without ever trailing",
         [it(f"{g['us']}-{g['them']}", game={"id": g["id"], "label": glabel(g)}) for g in sorted(wire, key=lambda x: -(x['margin']))[:5]])

    # biggest unanswered run
    runs = sorted([g for g in games if g.get("longest_run")], key=lambda g: -g["longest_run"])
    card("Game shape", "runs", "On a heater", "longest unanswered scoring run",
         [it(f"{g['longest_run']}-0 run", game={"id": g["id"], "label": glabel(g)}, sub=f"{g['result']} {g['us']}-{g['them']}") for g in runs[:3]])

    # highest-scoring games
    high = sorted(real, key=lambda g: -g["us"])[:3]
    card("Game shape", "high-scoring", "Points flurry", "the team's highest-scoring games",
         [it(f"{g['us']} pts", game={"id": g["id"], "label": glabel(g)}, sub=f"{g['result']} vs {g['opponent']}") for g in high])

    return cards


# --- main ------------------------------------------------------------------

def build():
    warnings = []
    metas = discover_games(SCORES_DIR)
    if not metas:
        print(f"No game CSVs found in {SCORES_DIR}", file=sys.stderr)
        sys.exit(1)
    games = [build_game(m, warnings) for m in metas]
    games += [build_forfeit(f) for f in load_forfeits()]

    # order: seasons by their earliest game, games within a season by date (this
    # also slots any forfeit into its true place in the schedule).
    first_by_season = {}
    for g in games:
        k = g["season"]
        first_by_season[k] = min(first_by_season.get(k, g["date"]), g["date"])
    games.sort(key=lambda g: (first_by_season[g["season"]], g["date"]))

    # round number per game: weeks since the season's first game (+1). The league
    # plays weekly, so this gives the league round even across a bye or an
    # un-recorded week — e.g. an 18 Oct game is Round 4 even if Round 3 is missing.
    # Weeks the league held NO round (data/off-weeks.json) don't count: each one
    # before a game's week shifts that game's round down by one, so a league-wide
    # off week isn't mistaken for a bye SJB played around.
    off_weeks = load_off_weeks()
    off_idx = {}
    for sk, first in first_by_season.items():
        d0 = dt.date.fromisoformat(first)
        off_idx[sk] = sorted((dt.date.fromisoformat(od) - d0).days // 7
                             for od in off_weeks.get(sk, []))
    for g in games:
        d0 = dt.date.fromisoformat(first_by_season[g["season"]])
        week = (dt.date.fromisoformat(g["date"]) - d0).days // 7
        skipped = sum(1 for i in off_idx.get(g["season"], []) if 0 <= i < week)
        g["round"] = week + 1 - skipped

    # hand-entered extras (half scores / scoring breakdown) for incomplete exports
    extras = load_game_extras()
    for g in games:
        ex = extras.get(g["id"])
        if not ex:
            continue
        if ex.get("half_scores") and not g.get("half_scores"):
            g["half_scores"] = ex["half_scores"]
            # half splits are available after all — drop the generic PBP-missing note
            g["notes"] = [n for n in g.get("notes", []) if not n.startswith("No play-by-play")]
        if ex.get("scoring"):
            g["scoring"] = ex["scoring"]
        # finals / playoff stage: a league game that isn't part of the weekly
        # regular-season ladder (semi-final, grand final, etc.). When set, the
        # game is labelled by its stage instead of a round number everywhere.
        if ex.get("stage"):
            st = ex["stage"]
            if isinstance(st, str):
                st = {"label": st, "short": st}
            g["stage"] = {"label": st.get("label", "Finals"),
                          "short": st.get("short") or st.get("label", "Finals")}
            g["round"] = None
        # pre-game penalty points: team points on the scoreboard credited to no
        # player (e.g. league fouls/penalties before tip-off). Added on top of the
        # on-court box to make the final score and result; shooting, ratings and
        # every player stat stay on the untouched box (us_oncourt/them_oncourt).
        pen = ex.get("penalty_points")
        if pen:
            pu = int(pen.get("us", 0) or 0)
            pt = int(pen.get("them", 0) or 0)
            g["us_oncourt"], g["them_oncourt"] = g["us"], g["them"]
            g["us"] += pu
            g["them"] += pt
            g["margin"] = g["us"] - g["them"]
            g["result"] = "W" if g["us"] > g["them"] else ("L" if g["us"] < g["them"] else "D")
            g["penalty"] = {"us": pu, "them": pt, "note": pen.get("note", "")}
            # shift the play-by-play flow by the pre-game head start so the plotted
            # scoreboard starts at the penalty state and ends at the final score;
            # longest run (consecutive on-court points) is unchanged by an offset.
            if g.get("flow"):
                g["flow"] = [[i + 1, m + (pu - pt), u + pu, t + pt]
                             for (i, m, u, t) in g["flow"]]
                g["flow"].insert(0, [0, pu - pt, pu, pt])
                g["biggest_lead"] = max(f[1] for f in g["flow"])
                # the inserted head-start point shifts every flow index by one
                if g.get("flow_meta", {}).get("half_marks"):
                    g["flow_meta"]["half_marks"] = [x + 1 for x in g["flow_meta"]["half_marks"]]
            # shift the play-by-play feed + highlights by the same head start so
            # their running scores end on the final (penalty-inclusive) scoreboard
            if g.get("pbp"):
                for ev in g["pbp"]:
                    ev["us"] += pu
                    ev["them"] += pt
                g["pbp"].insert(0, {
                    "half": 1, "clock": 1200, "t": "20:00", "team": None, "kind": "penalty",
                    "pts": 0, "score": False, "who": "Pre-game penalties",
                    "label": f"scoreboard set to {pu}–{pt}", "us": pu, "them": pt})
            if g.get("highlights"):
                for h in g["highlights"]:
                    h["us"] += pu
                    h["them"] += pt
            g["notes"].insert(0, pen.get("note") or (
                f"Pre-game penalties — {pt}-{pu} to {g['opponent']} before tip-off. "
                f"Team points (SJB +{pu}, {g['opponent']} +{pt}) counted in the score "
                f"and result but not credited to any player."))

    # Player of the Game: the top SJB Game Score each game (points as a fallback
    # for a points-only game). Forfeits have no box, so they get none.
    potg_counts = {}
    for g in games:
        if g.get("level") == "forfeit" or not g.get("box_us"):
            continue
        scored = [p for p in g["box_us"] if p.get("gmsc") is not None]
        if scored:
            best = max(scored, key=lambda p: p["gmsc"])
            val, stat = round(best["gmsc"], 1), "GmSc"
        else:
            scored = [p for p in g["box_us"] if (p.get("pts") or 0) > 0]
            if not scored:
                continue
            best = max(scored, key=lambda p: p["pts"])
            val, stat = best["pts"], "pts"
        g["potg"] = {"name": best["name"], "slug": slugify(best["name"]),
                     "value": val, "stat": stat}
        potg_counts[best["name"]] = potg_counts.get(best["name"], 0) + 1

    checks = validate(games, warnings)

    players = build_players(games)
    for p in players:
        p["potg_count"] = potg_counts.get(p["name"], 0)
    leaders = build_leaders(players)
    team = build_team(games)

    # strip internal scratch fields before emitting
    for g in games:
        g.pop("_recon", None)
        g.pop("_player_pm", None)
    for p in players:
        for b in p["seasons"]:
            b.pop("_raw", None)
        p["career"].pop("_raw", None)

    schedule = [{"id": g["id"], "date": g["date"], "date_disp": g["date_disp"],
                 "round": g["round"], "stage": g.get("stage"),
                 "season": g["season"], "season_label": g["season_label"],
                 "opponent": g["opponent"], "opponent_slug": g["opponent_slug"],
                 "result": g["result"], "us": g["us"], "them": g["them"],
                 "margin": g["margin"], "tracked": g["tracked"], "level": g["level"],
                 "partial": g["partial"], "points_only": g["points_only"],
                 "box_only": g.get("box_only", False),
                 "forfeit": g.get("forfeit", False),
                 "potg": g.get("potg"),
                 "nominal_score": g.get("nominal_score", False)} for g in games]

    # running record + current win/loss streak per game (within each season, in
    # schedule order) — the BBref "Schedule & Results" texture
    seen = {}
    for s in schedule:
        st = seen.setdefault(s["season"], {"w": 0, "l": 0, "d": 0, "c": None, "n": 0})
        st["w" if s["result"] == "W" else "l" if s["result"] == "L" else "d"] += 1
        if s["result"] == st["c"]:
            st["n"] += 1
        else:
            st["c"], st["n"] = s["result"], 1
        s["rec_w"], s["rec_l"], s["rec_d"] = st["w"], st["l"], st["d"]
        s["streak"] = f"{st['c']}{st['n']}"

    # season list, oldest first, with a quick record for each
    seasons = []
    for g in games:
        s = next((x for x in seasons if x["key"] == g["season"]), None)
        if s is None:
            s = {"key": g["season"], "label": g["season_label"], "w": 0, "l": 0, "d": 0, "games": 0}
            seasons.append(s)
        s["games"] += 1
        s["w" if g["result"] == "W" else "l" if g["result"] == "L" else "d"] += 1

    # per-season (and all-time) team stats + leaderboards, for the season switcher
    scope_keys = [s["key"] for s in seasons]
    team_by_season = {"all": team}
    leaders_by_season = {"all": leaders}
    for sk in scope_keys:
        gs = [g for g in games if g["season"] == sk]
        team_by_season[sk] = build_team(gs)
        leaders_by_season[sk] = build_leaders(season_leader_entries(players, sk))

    awards, _honors = compute_awards(games, seasons)

    data = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "seasons": seasons,
        "awards": awards,
        "frivolities": compute_frivolities(games, players),
        "current_season": seasons[-1]["label"] if seasons else None,
        "current_season_key": scope_keys[-1] if scope_keys else "all",
        "team": team,
        "team_by_season": team_by_season,
        "schedule": schedule,
        "games": games,
        "players": players,
        "leaders": leaders,
        "leaders_by_season": leaders_by_season,
        "ladder": load_ladder(),
        "validation": {
            "ok": all(c["ok"] for c in checks),
            "total": len(checks),
            "passed": sum(1 for c in checks if c["ok"]),
            "failed": [c["label"] for c in checks if not c["ok"]],
            "data_notes": [n for g in games for n in g["notes"]],
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data, checks, warnings


def main():
    ap = argparse.ArgumentParser(description="Build the SJB reference site data layer")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any validation check fails")
    args = ap.parse_args()

    try:                                   # keep em-dashes legible in the Windows console
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    data, checks, warnings = build()
    passed = sum(1 for c in checks if c["ok"])
    print(f"Games:   {len(data['games'])}")
    print(f"Players: {len(data['players'])}")
    print(f"Record:  {data['team']['record']['w']}-{data['team']['record']['l']}-{data['team']['record']['d']}")
    print(f"Checks:  {passed}/{len(checks)} passed")
    for c in checks:
        if not c["ok"]:
            print(f"  FAIL  {c['label']}")
    if data["validation"]["data_notes"]:
        print("Data notes (surfaced on the site, not errors):")
        for note in data["validation"]["data_notes"]:
            print(f"  - {note}")
    print(f"Wrote {OUT}")
    if args.strict and not data["validation"]["ok"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
