"""Pull live league ladders from PlayHQ into data/ladder.json.

PlayHQ serves each grade's ladder from a public GraphQL endpoint — no login and no
API key, just a `tenant` header and browser-like request headers (its WAF rejects
bare clients). The grade id is the hex id in the public ladder URL, e.g.

    https://www.playhq.com/.../sunday-men-c-grade-2/f7e657dc/ladder
                                                     ^^^^^^^^  gradeID

How it's wired: a season block in data/ladder.json may carry
    "source": { "playhq_grade_id": "f7e657dc", "tenant": "basketball-victoria" }
For every season that has one, this script fetches the current standings and
rewrites that season's "teams" (kept in the official ranked order the feed returns)
and "updated". Seasons without a source (e.g. a finished season kept as history)
are left untouched, as are any hand-kept fields (status, ranked_by, note). Run it
before build_site.py — build.bat does. A failed fetch is non-fatal: the file is
left exactly as-is, so the build still uses the last-saved ladder, and you can
always hand-edit teams as a fallback.

    python server/fetch_ladder.py            # update every season that has a source
    python server/fetch_ladder.py season-2   # just one season
"""

import datetime as dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LADDER = ROOT / "data" / "ladder.json"
ENDPOINT = "https://api.playhq.com/graphql"

QUERY = (
    "query gradeLadder($gradeID: ID!){ discoverGrade(gradeID:$gradeID){ id name "
    "ladder{ standings{ team{ name } played won lost drawn byes pointsFor "
    "pointsAgainst forfeits disqualifications adjustments percentage "
    "competitionPoints pointsAverage } } } }"
)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def fetch_standings(grade_id, tenant):
    payload = json.dumps({"operationName": "gradeLadder", "query": QUERY,
                          "variables": {"gradeID": grade_id}}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=payload, method="POST", headers={
        "content-type": "application/json",
        "tenant": tenant,
        "accept": "*/*",
        "accept-language": "en-AU,en;q=0.9",
        "origin": "https://www.playhq.com",
        "referer": "https://www.playhq.com/",
        "user-agent": _UA,
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("errors"):
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    grade = (data.get("data") or {}).get("discoverGrade")
    if not grade or not grade.get("ladder"):
        raise RuntimeError("no ladder in response (grade id wrong, or ladder not published yet)")
    pools = grade["ladder"]
    # single-pool grades (the normal case) have one entry; concatenate defensively.
    standings = []
    for pool in pools:
        standings.extend(pool.get("standings") or [])
    if not standings:
        raise RuntimeError("ladder has no standings yet")
    return standings


def to_row(s):
    """Map one PlayHQ standing to this site's ladder.json schema."""
    pa = s.get("pointsAverage")
    return {
        "team": s["team"]["name"],
        "p": s.get("played"),
        "pts_avg": round(pa, 2) if pa is not None else None,
        "pts": s.get("competitionPoints"),
        "pct": s.get("percentage"),
        "w": s.get("won"), "l": s.get("lost"), "d": s.get("drawn"),
        "bye": s.get("byes"),
        "f": s.get("pointsFor"), "a": s.get("pointsAgainst"),
        "forf": s.get("forfeits"), "disq": s.get("disqualifications"),
        "adj": s.get("adjustments"),
    }


def dumps_ladder(doc):
    """Serialize ladder.json keeping each team row on its own single line, so the
    file stays as readable as the hand-entered version instead of exploding into
    one field per line."""
    out = ["{"]
    keys = list(doc.keys())
    for ki, key in enumerate(keys):
        tail = "," if ki < len(keys) - 1 else ""
        val = doc[key]
        if not isinstance(val, dict) or key.startswith("_"):
            out.append(f"  {json.dumps(key)}: {json.dumps(val, ensure_ascii=False)}{tail}")
            continue
        out.append(f"  {json.dumps(key)}: {{")
        bkeys = list(val.keys())
        for bi, bk in enumerate(bkeys):
            btail = "," if bi < len(bkeys) - 1 else ""
            if bk == "teams" and isinstance(val[bk], list):
                teams = val[bk]
                if not teams:
                    out.append(f'    "teams": []{btail}')
                    continue
                out.append('    "teams": [')
                for ti, t in enumerate(teams):
                    ttail = "," if ti < len(teams) - 1 else ""
                    out.append(f"      {json.dumps(t, ensure_ascii=False)}{ttail}")
                out.append(f"    ]{btail}")
            else:
                out.append(f"    {json.dumps(bk)}: {json.dumps(val[bk], ensure_ascii=False)}{btail}")
        out.append(f"  }}{tail}")
    out.append("}")
    return "\n".join(out) + "\n"


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    doc = json.loads(LADDER.read_text(encoding="utf-8"))
    changed = False
    saw_source = False
    for season, blk in doc.items():
        if season.startswith("_") or not isinstance(blk, dict):
            continue
        if only and season != only:
            continue
        src = blk.get("source") or {}
        gid = src.get("playhq_grade_id")
        if not gid:
            continue
        saw_source = True
        tenant = src.get("tenant", "basketball-victoria")
        try:
            standings = fetch_standings(gid, tenant)
        except Exception as e:
            print(f"  {season}: fetch failed ({e}); keeping existing ladder")
            continue
        blk["teams"] = [to_row(s) for s in standings]
        blk["updated"] = dt.date.today().isoformat()
        changed = True
        print(f"  {season}: {len(blk['teams'])} teams updated from PlayHQ grade {gid}")

    if changed:
        LADDER.write_text(dumps_ladder(doc), encoding="utf-8")
        print(f"Wrote {LADDER}")
    elif not saw_source:
        print("No seasons have a PlayHQ 'source'; nothing to fetch. "
              "(Add \"source\": {\"playhq_grade_id\": \"...\"} to a season block.)")
    else:
        print("No ladder changes written.")


if __name__ == "__main__":
    main()
