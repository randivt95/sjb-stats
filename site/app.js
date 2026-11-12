/* Shake Jelly Balls — reference site.
   A tiny hash-routed single-page app over the static data.json the build step
   emits. No framework, no build: it mirrors the betting book's vanilla-JS stack.
   Everything links to everything (Basketball-Reference style): player names ->
   player pages, dates/opponents -> game pages, game pages -> players. */

"use strict";

const view = document.getElementById("view");
let DATA = null;

/* ---- tiny helpers ------------------------------------------------------- */
const byId = (list, id, key = "id") => list.find(x => x[key] === id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function n(v, d = 1) {
  if (v === null || v === undefined || v === "") return "—";
  const num = Number(v);
  if (!isFinite(num)) return "—";
  return Number.isInteger(num) && d === 0 ? String(num) : num.toFixed(d);
}
/* a numeric table cell carrying its raw value so the sorter can order it */
function cell(v, d = 1, cls = "") {
  const raw = (v === null || v === undefined || v === "") ? -Infinity : Number(v);
  return `<td class="num ${cls}" data-v="${isFinite(raw) ? raw : -Infinity}">${v === null || v === undefined ? "—" : n(v, d)}</td>`;
}
function intCell(v, cls = "") { return cell(v, 0, cls); }
function pmCell(v) {
  if (v === null || v === undefined) return `<td class="num muted" data-v="-Infinity">—</td>`;
  const c = v > 0 ? "pos" : v < 0 ? "neg" : "";
  const s = v > 0 ? "+" + v : String(v);
  return `<td class="num ${c}" data-v="${v}">${s}</td>`;
}
function splitCell(m, a) {
  if (m == null || a == null) return `<td class="num muted" data-v="-Infinity">—</td>`;
  const pctv = a ? (100 * m / a) : -Infinity;
  return `<td class="num" data-v="${pctv}">${m}-${a}</td>`;
}
function resultPill(r) {
  const cls = r === "W" ? "w" : r === "L" ? "l" : "d";
  return `<span class="pill ${cls}">${r}</span>`;
}
function streakTag(s) {
  if (!s) return "—";
  const cls = s[0] === "W" ? "w" : s[0] === "L" ? "l" : "d";
  return `<span class="streak ${cls}">${esc(s)}</span>`;
}
function playerLink(p) {
  const jersey = p.jersey != null ? `<span class="jersey">#${p.jersey}</span>` : "";
  return `${jersey}<a class="player-link" href="#/player/${p.slug}">${esc(p.name)}</a>`;
}
function gameLink(g, label) {
  return `<a href="#/game/${g.id}">${esc(label != null ? label : g.date_disp)}</a>`;
}
function sampleTag(p) {
  return p.small_sample ? ` <span class="tag small">1 game</span>` : "";
}
function pctSuffix(v) { return v == null ? "" : ` · ${n(v)}%`; }
function ordinal(k) { const s = ["th", "st", "nd", "rd"], v = k % 100; return k + (s[(v - 20) % 10] || s[v] || s[0]); }

/* ---- sparkline + flow chart -------------------------------------------- */
function sparkline(values, w = 92, h = 26) {
  if (!values || values.length < 2) return "";
  const max = Math.max(...values, 1), min = Math.min(...values, 0);
  const span = (max - min) || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * (w - 4) + 2;
    const y = h - 2 - ((v - min) / span) * (h - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const dots = values.map((v, i) => {
    const x = (i / (values.length - 1)) * (w - 4) + 2;
    const y = h - 2 - ((v - min) / span) * (h - 4);
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="1.7" fill="var(--accent)"/>`;
  }).join("");
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <polyline fill="none" stroke="var(--accent)" stroke-width="1.6" points="${pts.join(" ")}"/>${dots}</svg>`;
}

/* pick a round gridline step so ~2-3 lines show across the range */
function niceTick(range) {
  const steps = [1, 2, 5, 10, 15, 20, 25, 50, 100];
  for (const s of steps) if (range / s <= 3) return s;
  return Math.ceil(range / 3);
}

/* Scoring-margin chart. The line and fill are coloured per-segment: green while
   SJB leads, red while trailing, flipping exactly where the margin crosses zero.
   Each scoring play is a hoverable point rather than a full-height band. */
function flowChart(flow, opponent, meta) {
  if (!flow || flow.length < 2) return "<p class='muted'>No play-by-play flow for this game.</p>";
  const W = 680, H = 210, padL = 40, padR = 70, padT = 18, padB = 28;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const cy = padT + plotH / 2;                       // margin = 0
  const maxIdx = flow.length - 1;
  const maxAbs = Math.max(5, ...flow.map(f => Math.abs(f[1])));
  const tick = niceTick(maxAbs);
  const yMax = Math.ceil(maxAbs / tick) * tick;       // top/bottom of the y scale
  const X = i => padL + (i / maxIdx) * plotW;         // even spacing per scoring play
  const Y = m => cy - (m / yMax) * (plotH / 2);
  const GREEN = "var(--green)", RED = "var(--red)";
  const colOf = m => m >= 0 ? GREEN : RED;
  const hr = Math.max(4, Math.min(9, (plotW / maxIdx) * 0.6));    // hover radius

  const P = flow.map((f, i) => ({ x: X(i), y: Y(f[1]), m: f[1], us: f[2] ?? 0, them: f[3] ?? 0 }));

  // break into same-sign runs, inserting a point on the zero line at each crossing
  const runs = [];
  let cur = null;
  const add = (sign, p) => { if (!cur || cur.sign !== sign) { cur = { sign, pts: [] }; runs.push(cur); } cur.pts.push(p); };
  for (let k = 0; k < P.length; k++) {
    const p = P[k], s = p.m >= 0 ? 1 : -1;
    if (k > 0) {
      const q = P[k - 1], qs = q.m >= 0 ? 1 : -1;
      if (qs !== s) {
        const t = (0 - q.m) / (p.m - q.m);
        const zx = q.x + t * (p.x - q.x);
        add(qs, { x: zx, y: cy, edge: true });
        add(s, { x: zx, y: cy, edge: true });
      }
    }
    add(s, p);
  }

  let areas = "", lines = "";
  runs.forEach(r => {
    if (r.pts.length < 2) return;
    const col = r.sign >= 0 ? GREEN : RED;
    const line = r.pts.map((p, j) => `${j ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
    const f = r.pts[0], l = r.pts[r.pts.length - 1];
    areas += `<path d="M${f.x.toFixed(1)} ${cy.toFixed(1)} L${r.pts.map(p => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" L")} L${l.x.toFixed(1)} ${cy.toFixed(1)} Z" fill="${col}" fill-opacity=".13"/>`;
    lines += `<path d="${line}" fill="none" stroke="${col}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
  });

  // y gridlines + labels (dashed), bold zero line
  let grid = "", ylab = `<text x="${padL - 6}" y="${(cy + 3).toFixed(1)}" font-size="10" text-anchor="end" fill="var(--text-mute)">0</text>`;
  for (let v = tick; v <= yMax + 0.001; v += tick) {
    [v, -v].forEach(val => {
      const y = Y(val);
      grid += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="var(--border-lit)" stroke-width="1" stroke-dasharray="2 3" opacity=".55"/>`;
      ylab += `<text x="${padL - 6}" y="${(y + 3).toFixed(1)}" font-size="10" text-anchor="end" fill="var(--text-mute)">${val > 0 ? "+" : ""}${val}</text>`;
    });
  }
  const zero = `<line x1="${padL}" y1="${cy.toFixed(1)}" x2="${W - padR}" y2="${cy.toFixed(1)}" stroke="var(--border-md)" stroke-width="1.2"/>`;
  const base = `<line x1="${padL}" y1="${(padT + plotH).toFixed(1)}" x2="${W - padR}" y2="${(padT + plotH).toFixed(1)}" stroke="var(--border-md)" stroke-width="1"/>`;
  const sideLab = `<text x="${W - padR + 8}" y="${(padT + 10).toFixed(1)}" font-size="10" fill="var(--text-mute)">SJB ahead</text>
    <text x="${W - padR + 8}" y="${(padT + plotH - 4).toFixed(1)}" font-size="10" fill="var(--text-mute)">${esc(opponent)}<tspan x="${W - padR + 8}" dy="11">ahead</tspan></text>`;

  // halftime / period divider(s) at each half boundary
  const marks = (meta && meta.half_marks) || [];
  let periods = "";
  marks.forEach((mk, k) => {
    if (mk < 0 || mk > maxIdx) return;
    const x = padL + (mk / maxIdx) * plotW;
    const lab = marks.length === 1 ? "HT" : k === 0 ? "HT" : "OT" + k;
    periods += `<line x1="${x.toFixed(1)}" y1="${padT}" x2="${x.toFixed(1)}" y2="${(padT + plotH).toFixed(1)}" stroke="var(--border-md)" stroke-width="1" stroke-dasharray="4 3" opacity=".8"/>
      <text x="${(x + 3).toFixed(1)}" y="${(padT + 9).toFixed(1)}" font-size="9.5" fill="var(--text-mute)">${lab}</text>`;
  });

  let dots = "", hits = "";
  P.forEach(p => {
    const c = colOf(p.m);
    dots += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="1.8" fill="${c}"/>`;
    const tip = `SJB ${p.us}–${p.them} (${p.m > 0 ? "+" : ""}${p.m})`;
    hits += `<circle class="chart-dot" style="--dc:${c}" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${hr.toFixed(1)}" data-tip="${esc(tip)}"/>`;
  });

  return `<svg class="flow-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Scoring margin over the game">
    ${grid}${periods}${zero}${base}${areas}${lines}${dots}${ylab}${sideLab}${hits}
  </svg>`;
}

/* A responsive line chart with hoverable points. opts:
   { labels:[...], series:[{color, values:[...]}], tip:(i)=>string, w, h, yMin } */
function lineChart(opts) {
  const labels = opts.labels || [];
  const nPts = labels.length;
  if (!nPts) return `<p class="muted">No games yet.</p>`;
  const W = opts.w || 380, H = opts.h || 120;
  const padL = 24, padR = 10, padT = 10, padB = 16;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const all = opts.series.flatMap(s => s.values.filter(v => v != null));
  let max = Math.max(...all, 1), min = opts.yMin != null ? opts.yMin : Math.min(...all, 0);
  const tick = niceTick(Math.max(1, max - min));
  max = Math.ceil(max / tick) * tick;                 // round the top up to a tick
  const span = (max - min) || 1;
  const X = i => padL + (nPts === 1 ? plotW / 2 : (i / (nPts - 1)) * plotW);
  const Y = v => padT + plotH - ((v - min) / span) * plotH;
  const baseY = padT + plotH;

  // gridlines + y labels
  let grid = "", ylab = "";
  for (let v = min; v <= max + 0.001; v += tick) {
    const y = Y(v);
    grid += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="var(--border-lit)" stroke-width="1" stroke-dasharray="2 3" opacity=".5"/>`;
    ylab += `<text x="${padL - 5}" y="${(y + 3).toFixed(1)}" font-size="9.5" text-anchor="end" fill="var(--text-mute)">${Math.round(v)}</text>`;
  }
  const axis = `<line x1="${padL}" y1="${baseY.toFixed(1)}" x2="${W - padR}" y2="${baseY.toFixed(1)}" stroke="var(--border-md)" stroke-width="1"/>`;

  let body = "", dots = "", hits = "";
  opts.series.forEach(s => {
    const pts = s.values.map((v, i) => v == null ? null : `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).filter(Boolean).join(" ");
    if (pts) body += `<polyline fill="none" stroke="${s.color}" stroke-width="1.8" points="${pts}"/>`;
    s.values.forEach((v, i) => {
      if (v == null) return;
      dots += `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="2.4" fill="${s.color}"/>`;
      hits += `<circle class="chart-dot" style="--dc:${s.color}" cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="7" data-tip="${esc(opts.tip(i))}"/>`;
    });
  });
  return `<svg class="flow-chart" viewBox="0 0 ${W} ${H}" role="img">${grid}${axis}${ylab}${body}${dots}${hits}</svg>`;
}

/* a single floating tooltip, reused across all charts */
let _chartTip = null;
function enableChartHover(root) {
  if (!_chartTip) {
    _chartTip = document.createElement("div");
    _chartTip.className = "chart-tip";
    _chartTip.style.display = "none";
    document.body.appendChild(_chartTip);
  }
  const tip = _chartTip;
  const hide = () => { tip.style.display = "none"; };
  hide();
  root.querySelectorAll(".chart-dot, .chart-hit").forEach(el => {
    el.addEventListener("mouseenter", () => { tip.textContent = el.getAttribute("data-tip"); tip.style.display = "block"; });
    el.addEventListener("mousemove", e => {
      const pad = 14;
      let x = e.clientX + pad, y = e.clientY + pad;
      if (x + 170 > window.innerWidth) x = e.clientX - 170;
      tip.style.left = x + "px"; tip.style.top = y + "px";
    });
    el.addEventListener("mouseleave", hide);
  });
}

/* ---- sortable tables (DOM reorder, reads data-v) ----------------------- */
function enableSorting(root) {
  root.querySelectorAll("table.stat thead th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const table = th.closest("table");
      const tbody = table.querySelector("tbody");
      const idx = [...th.parentNode.children].indexOf(th);
      const dir = th.classList.contains("sorted-desc") ? 1 : -1;
      table.querySelectorAll("thead th").forEach(h => h.classList.remove("sorted", "sorted-desc", "sorted-asc"));
      th.classList.add("sorted", dir === -1 ? "sorted-desc" : "sorted-asc");
      const rows = [...tbody.querySelectorAll("tr:not(.total)")];
      const totals = [...tbody.querySelectorAll("tr.total")];
      rows.sort((a, b) => {
        const av = a.children[idx], bv = b.children[idx];
        const an = av && av.dataset.v !== undefined ? parseFloat(av.dataset.v) : NaN;
        const bn = bv && bv.dataset.v !== undefined ? parseFloat(bv.dataset.v) : NaN;
        if (!isNaN(an) && !isNaN(bn)) return (an - bn) * dir;
        return String(av ? av.textContent : "").localeCompare(String(bv ? bv.textContent : "")) * dir;
      });
      rows.forEach(r => tbody.appendChild(r));
      totals.forEach(r => tbody.appendChild(r));
      th.querySelectorAll(".arrow").forEach(a => a.textContent = dir === -1 ? "▼" : "▲");
    });
  });
}

function th(label, { sortable = true, cls = "", title = "" } = {}) {
  return `<th class="${sortable ? "sortable" : ""} ${cls}" ${title ? `title="${esc(title)}"` : ""}>${esc(label)}${sortable ? ' <span class="arrow"></span>' : ""}</th>`;
}

/* ---- season scope (the Home/Team/Leaders switcher) --------------------- */
let selSeason = "all";
function teamScope() { return (DATA.team_by_season && DATA.team_by_season[selSeason]) || DATA.team; }
function leadersScope() { return (DATA.leaders_by_season && DATA.leaders_by_season[selSeason]) || DATA.leaders; }
function scheduleScope() { return selSeason === "all" ? DATA.schedule : DATA.schedule.filter(g => g.season === selSeason); }
function seasonName(key) {
  if (key === "all") return "All-time";
  const s = (DATA.seasons || []).find(x => x.key === key);
  return s ? s.label : key;
}
function seasonSelect() {
  const opts = [{ k: "all", l: "All-time" }].concat((DATA.seasons || []).map(s => ({ k: s.key, l: s.label })));
  return `<div class="season-pick">Showing <select class="season-select">${opts.map(o =>
    `<option value="${o.k}"${o.k === selSeason ? " selected" : ""}>${esc(o.l)}</option>`).join("")}</select></div>`;
}

/* ---- views -------------------------------------------------------------- */

/* One-line score recap of a game for the home "Latest result" card. */
function homeRecap(g) {
  const opp = esc(g.opponent);
  if (g.forfeit) return `Shake Jelly Balls won by forfeit over ${opp}.`;
  const won = g.result === "W", draw = g.result === "D";
  const verb = won ? "beat" : draw ? "drew with" : "lost to";
  return `Shake Jelly Balls ${verb} ${opp} <strong class="recap-score result-${g.result}">${g.us}–${g.them}</strong>.`;
}

function viewHome() {
  const t = teamScope();
  const rec = `${t.record.w}-${t.record.l}${t.record.d ? "-" + t.record.d : ""}`;
  const games = scheduleScope();
  const L = leadersScope();
  const last = games.length ? byId(DATA.games, games[games.length - 1].id) : DATA.games[DATA.games.length - 1];
  const net = t.advanced.net_rtg;
  const r = t.results || {};
  const pg = t.per_game || {}, opg = t.opp_per_game || {};
  const lastRow = games.length ? games[games.length - 1] : null;
  const streak = lastRow ? lastRow.streak : null;
  const ladderData = (DATA.ladder && DATA.ladder[selSeason]) || null;
  const standing = ladderData && ladderData.teams ? ladderData.teams.find(x => x.is_sjb) : null;

  const gp = t.games_played, gs = t.games_scored != null ? t.games_scored : gp;
  const gf = t.games_forfeit || 0, gt = t.games_tracked;
  const subBits = [];
  if (gf) subBits.push(`${gf} forfeit${gf === 1 ? "" : "s"}`);
  if (gt < gs) subBits.push(`${gt} of ${gs} fully tracked`);
  const subExtra = subBits.length ? ` (${subBits.join(", ")})` : "";

  const chips = games.map(g =>
    `<a class="chip ${g.result.toLowerCase()}" href="#/game/${g.id}" title="${esc(g.opponent)} ${g.date_disp}">${g.result} ${g.us}-${g.them}</a>`).join("");

  // recent games — last five, newest first, newest row emphasised
  const recentRows = games.slice(-5).reverse().map((g, i) => `<tr${i === 0 ? ' class="total"' : ""}>
    <td class="num">${gameLink(g, g.date_disp)}</td>
    <td><a href="#/game/${g.id}">${esc(g.opponent)}</a></td>
    <td>${resultPill(g.result)}</td>
    <td class="num">${g.forfeit && !g.nominal_score ? "—" : `${g.us}–${g.them}`}</td>
    ${g.forfeit ? '<td class="num">—</td>' : pmCell(g.margin)}
  </tr>`).join("");

  // team leaders across categories
  const leadRow = (brd, lab) => { const e = brd && brd[0]; return e
    ? `<div class="leader-row"><span class="leader-rank">${lab}</span><span class="nm">${playerLink(find(e.slug))}</span><span class="val">${n(e.value)}</span></div>` : ""; };
  const leaderRows = [["PTS", L.ppg], ["REB", L.rpg], ["AST", L.apg], ["STL", L.spg], ["BLK", L.bpg], ["GmSc", L.gmsc]]
    .map(([lab, b]) => leadRow(b, lab)).join("");

  // team & opponent per game
  const tmRow = (lab, a, b, d = 1) => `<tr><td>${lab}</td>${cell(a, d)}${cell(b, d)}</tr>`;
  const perGameRows = [
    tmRow("Points", pg.pts, opg.pts), tmRow("Rebounds", pg.reb, opg.reb),
    tmRow("Assists", pg.ast, opg.ast), tmRow("Steals", pg.stl, opg.stl),
    tmRow("Blocks", pg.blk, opg.blk), tmRow("Turnovers", pg.to, opg.to),
    tmRow("FG%", t.fg_pct, t.opp_fg_pct), tmRow("3P%", t.tp_pct, t.opp_tp_pct),
  ].join("");

  // season notables
  const notes = [];
  if (r.avg_margin != null) notes.push(["Avg margin", `${r.avg_margin > 0 ? "+" : ""}${n(r.avg_margin)}`]);
  if (r.best_win) notes.push(["Best win", `<a href="#/game/${r.best_win.game_id}">+${r.best_win.margin} vs ${esc(r.best_win.opponent)}</a>`]);
  if (r.worst_loss) notes.push(["Worst loss", `<a href="#/game/${r.worst_loss.game_id}">${r.worst_loss.margin} vs ${esc(r.worst_loss.opponent)}</a>`]);
  if (r.close) notes.push(["Close games (≤5)", `${r.close.g} · ${r.close.w}-${r.close.l}${r.close.d ? "-" + r.close.d : ""}`]);
  if (r.blowout_wins != null) notes.push(["Blowout wins (15+)", r.blowout_wins]);
  if (standing) notes.push(["Ladder position", `<a href="#/ladder">${ordinal(standing.rank)} of ${ladderData.teams.length}</a>`]);
  const notableRows = notes.map(([k, v]) =>
    `<div style="display:flex;justify-content:space-between;gap:12px;padding:5px 0;border-bottom:1px solid #ededed;font-size:13px"><span class="muted">${k}</span><span style="font-weight:700">${v}</span></div>`).join("");

  // MVP race widget (uses the computed awards for the selected season)
  const awSeasonData = (DATA.awards && DATA.awards.seasons && DATA.awards.seasons[selSeason]) || null;
  const mvpAward = awSeasonData && awSeasonData.awards ? awSeasonData.awards.mvp : null;
  const mvpWidget = (mvpAward && mvpAward.candidates && mvpAward.candidates.length) ? (() => {
    const cands = mvpAward.candidates.slice(0, 5);
    const maxShare = cands[0].share || 1;
    return `<div class="card">
      <div class="award-head"><h2>MVP ${awSeasonData.is_final ? "" : "race"}</h2><span class="award-sub">${awSeasonData.is_final ? "season winner" : "value per team game · as it stands"}</span></div>
      <div class="mvp-race">${cands.map((r, i) => `<div class="mvpr-row${i === 0 ? " lead" : ""}">
        <span class="mvpr-rank">${i + 1}</span>
        <span class="mvpr-nm">${playerLink(find(r.slug))}</span>
        <span class="mvpr-bar"><span class="mvpr-fill" style="width:${Math.max(6, Math.round(r.share / maxShare * 100))}%"></span></span>
        <span class="mvpr-share">${r.share}%</span>
        <span class="mvpr-val">${r.mvp}</span>
      </div>`).join("")}</div>
      <div style="margin-top:10px"><a href="#/awards">Full awards →</a></div>
    </div>`;
  })() : "";

  return `
  <div class="page-head">
    <div class="head-row"><h1>Shake Jelly Balls</h1>${seasonSelect()}</div>
    <div class="sub">${esc(seasonName(selSeason))} · ${gp} game${gp === 1 ? "" : "s"}${subExtra}.</div>
  </div>

  <div class="tiles" style="margin-bottom:18px">
    <div class="tile hi"><div class="k">Record</div><div class="v">${rec}</div><div class="note">${t.games_played} games</div></div>
    <div class="tile"><div class="k">Streak</div><div class="v">${streak || "—"}</div><div class="note">current</div></div>
    <div class="tile"><div class="k">Points for</div><div class="v">${n(t.ppg_for)}</div><div class="note">per game</div></div>
    <div class="tile"><div class="k">Points against</div><div class="v">${n(t.ppg_against)}</div><div class="note">per game</div></div>
    <div class="tile"><div class="k">Net rating</div><div class="v">${net > 0 ? "+" : ""}${n(net)}</div><div class="note">per 100 poss</div></div>
    <div class="tile"><div class="k">TOV margin</div><div class="v">${t.tov_margin > 0 ? "+" : ""}${t.tov_margin}</div><div class="note">season</div></div>
  </div>

  ${last ? `<div class="card">
    <h2>Latest result</h2>
    <div class="grid cols-2" style="align-items:start">
      <div>
        <div class="scoreboard result-${last.result}">
          <div class="sb-team ${last.result === "W" ? "win" : ""}"><div class="name">Shake Jelly Balls</div><div class="score">${last.forfeit && !last.nominal_score ? "—" : last.us}</div></div>
          <div class="sb-sep">${last.stage ? `${esc(last.stage.label)}<br>` : last.round ? `Round ${last.round}<br>` : ""}${resultPill(last.result)}<br>${esc(last.date_disp)}</div>
          <div class="sb-team ${last.result === "L" ? "win" : ""}"><div class="name">${esc(last.opponent)}</div><div class="score">${last.forfeit && !last.nominal_score ? "—" : last.them}</div></div>
        </div>
        <p style="margin:14px 0 10px;font-size:14px;line-height:1.55">${homeRecap(last)}</p>
        <a href="#/game/${last.id}">Full recap &amp; box score →</a>
      </div>
      <div>
        ${potgBadge(last)}
        ${(last.highlights && last.highlights.length) ? `<ul class="key-moments" style="margin-top:12px">${kmItems(last.highlights.slice(-4), last.opponent)}</ul>` : ""}
      </div>
    </div>
  </div>` : ""}

  ${mvpWidget}

  <div class="grid cols-2">
    <div class="card"><h2>Recent games</h2>
      <div class="table-scroll"><table class="stat">
        <thead><tr>${["Date", "Opponent", "Result", "Score", "Margin"].map(h => th(h, { sortable: false })).join("")}</tr></thead>
        <tbody>${recentRows || `<tr><td class="muted" colspan="5">No games yet.</td></tr>`}</tbody>
      </table></div>
      <div style="margin-top:10px"><a href="#/schedule">Full schedule →</a></div>
    </div>

    <div class="card"><h2>Team leaders</h2>
      ${leaderRows || `<p class="muted">No games yet.</p>`}
      <div style="margin-top:10px"><a href="#/leaders">All leaderboards →</a></div>
    </div>
  </div>

  <div class="grid cols-2">
    <div class="card"><h2>Team &amp; opponent per game</h2>
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("", { sortable: false })}${th("SJB", { sortable: false })}${th("Opp", { sortable: false })}</tr></thead>
        <tbody>${perGameRows}</tbody>
      </table></div>
    </div>

    <div class="card"><h2>Season notables</h2>
      ${notableRows || `<p class="muted">No games yet.</p>`}
      <div style="margin-top:10px"><a href="#/team">Team page →</a></div>
    </div>
  </div>

  <div class="card">
    <h2>Results</h2>
    <div class="recent"><div class="chip-row">${chips}</div></div>
  </div>

  ${footer()}`;
}

function viewSchedule() {
  const multiSeason = (DATA.seasons || []).length > 1;
  const recOf = key => { const s = (DATA.seasons || []).find(x => x.key === key); return s ? `${s.w}-${s.l}${s.d ? "-" + s.d : ""}` : ""; };
  const gameRow = g => `<tr>
    <td class="num" data-v="${g.round ?? 999}">${g.stage ? `<span class="tag stage" title="${esc(g.stage.label)}">${esc(g.stage.short)}</span>` : g.round}</td>
    <td class="num" data-v="${g.date.replace(/-/g, "")}">${gameLink(g, g.date_disp)}</td>
    <td><a href="#/game/${g.id}">${esc(g.opponent)}</a></td>
    <td data-v="${g.result === "W" ? 2 : g.result === "D" ? 1 : 0}">${resultPill(g.result)}</td>
    <td class="num" data-v="${g.us}">${g.forfeit && !g.nominal_score ? "—" : `${g.us}–${g.them}`}</td>
    ${g.forfeit ? '<td class="num">—</td>' : pmCell(g.margin)}
    <td class="num" data-v="${(g.rec_w ?? 0) * 100 - (g.rec_l ?? 0)}">${g.rec_w ?? 0}-${g.rec_l ?? 0}${g.rec_d ? "-" + g.rec_d : ""}</td>
    <td data-v="${g.streak && g.streak[0] === "W" ? 1 : g.streak && g.streak[0] === "L" ? -1 : 0}">${streakTag(g.streak)}</td>
    <td>${g.forfeit ? '<span class="tag warn">forfeit</span>' : g.points_only ? '<span class="tag warn">points only</span>' : g.box_only ? '<span class="tag warn">box only</span>' : g.partial ? '<span class="tag warn">points + flow</span>' : '<span class="tag">tracked</span>'}</td>
  </tr>`;
  let rows = "", lastSeason = null;
  for (const g of DATA.schedule) {
    if (multiSeason && g.season !== lastSeason) {
      rows += `<tr class="season-sep"><td colspan="9">${esc(g.season_label)} <span class="muted">· ${recOf(g.season)}</span></td></tr>`;
      lastSeason = g.season;
    }
    rows += gameRow(g);
  }
  return `
  <div class="page-head"><h1>Schedule &amp; Results</h1></div>
  <div class="card"><div class="table-scroll"><table class="stat sched">
    <thead><tr>${["Rd", "Date", "Opponent", "Result", "Score", "Margin", "Record", "Streak", "Tracking"].map(h => th(h, { sortable: !multiSeason })).join("")}</tr></thead>
    <tbody>${rows}</tbody>
  </table></div></div>
  ${footer()}`;
}

function boxTable(players, { team, opp, opponent }) {
  const head = `<thead><tr>
    ${th("Player", { sortable: true })}${th("MIN")}${th("PTS")}${th("FG")}${th("3P")}${th("FT")}
    ${th("OR")}${th("DR")}${th("REB")}${th("AST")}${th("STL")}${th("BLK")}${th("TO")}${th("PF")}
    ${th("+/-", { title: "On-court plus/minus (reconstructed from play-by-play, matches the box)" })}
    ${th("GmSc", { title: "Hollinger Game Score" })}${th("FP", { title: "ESPN fantasy points" })}
  </tr></thead>`;
  const row = p => `<tr>
    <td>${playerLink(p)}</td>
    ${cell(p.min, 0)}${intCell(p.pts)}
    ${splitCell(p.fgm, p.fga)}${splitCell(p.tpm, p.tpa)}${splitCell(p.ftm, p.fta)}
    ${intCell(p.oreb)}${intCell(p.dreb)}${intCell(p.reb)}${intCell(p.ast)}${intCell(p.stl)}${intCell(p.blk)}${intCell(p.to)}${intCell(p.foul)}
    ${pmCell(p.plus_minus)}${cell(p.gmsc)}${cell(p.fp)}
  </tr>`;
  const totalRow = (l, label) => `<tr class="total">
    <td>${esc(label)}</td>${cell(null, 0)}${intCell(l.pts)}
    ${splitCell(l.fgm, l.fga)}${splitCell(l.tpm, l.tpa)}${splitCell(l.ftm, l.fta)}
    ${intCell(l.oreb)}${intCell(l.dreb)}${intCell(l.reb)}${intCell(l.ast)}${intCell(l.stl)}${intCell(l.blk)}${intCell(l.to)}${intCell(l.foul)}
    ${cell(null)}${cell(null)}${cell(null)}
  </tr>`;
  return `<div class="table-scroll"><table class="stat">${head}<tbody>
    ${players.map(row).join("")}
    ${totalRow(team, "Shake Jelly Balls")}
  </tbody></table></div>`;
}

/* a game that wasn't video-recorded: final score, per-player points and the
   scoring flow, but no shooting / box detail / advanced stats */
function viewPartialGame(g, won) {
  const notes = (g.notes || []).map(x => `<div class="banner">${esc(x)}</div>`).join("");
  const sc = g.scoring || null;
  const hasScoring = sc && Object.keys(sc).length > 0;
  const hasReb = g.box_us.some(p => p.reb != null);
  const hasAst = g.box_us.some(p => p.ast != null);
  const hasFoul = g.box_us.some(p => p.foul != null);
  const tl = g.team_line || {};
  let tTwo = 0, tThree = 0, tFt = 0;
  if (hasScoring) for (const k in sc) { tTwo += sc[k].two || 0; tThree += sc[k].three || 0; tFt += sc[k].ft || 0; }
  const extraCells = p => `${hasScoring ? `${intCell((sc[p.name] || {}).two)}${intCell((sc[p.name] || {}).three)}${intCell((sc[p.name] || {}).ft)}` : ""}${hasReb ? intCell(p.reb) : ""}${hasAst ? intCell(p.ast) : ""}${hasFoul ? intCell(p.foul) : ""}`;
  const scorers = g.box_us.map(p => `<tr><td>${playerLink(p)}</td>${intCell(p.pts)}${extraCells(p)}</tr>`).join("");
  const boxTitle = (hasReb || hasAst) ? "Box score" : "Scoring";
  const boxHint = (hasReb || hasAst) ? "points, rebounds, assists &amp; fouls — no shooting splits or steals/blocks recorded"
    : hasScoring ? "points &amp; made shots only — no attempts, rebounds or defence recorded"
    : "points only — no box score recorded";
  const fromPbp = g.flow && g.flow.length > 1;
  const halves = (g.half_scores || []).map(h =>
    `<tr><td>Half ${h.half}</td>${intCell(h.us)}${intCell(h.them)}${pmCell(h.us - h.them)}</tr>`).join("");
  return `
  <div class="crumbs"><a href="#/schedule">Schedule</a> › ${esc(g.opponent)} <span class="tag warn">not fully tracked</span></div>
  <div class="card">
    <div class="scoreboard result-${g.result}">
      <div class="sb-team ${won ? "win" : ""}"><div class="name">Shake Jelly Balls</div><div class="score">${g.us}</div></div>
      <div class="sb-sep">${g.stage ? `${esc(g.stage.label)}<br>` : g.round ? `Round ${g.round}<br>` : ""}${resultPill(g.result)}<br>${esc(g.date_disp)}</div>
      <div class="sb-team ${!won && g.result === "L" ? "win" : ""}"><div class="name">${esc(g.opponent)}</div><div class="score">${g.them}</div></div>
    </div>
  </div>
  ${notes}
  <div class="tiles" style="margin-bottom:18px">
    <div class="tile"><div class="k">Margin</div><div class="v">${g.margin > 0 ? "+" : ""}${g.margin}</div></div>
    <div class="tile"><div class="k">Biggest lead</div><div class="v">${g.biggest_lead != null ? "+" + g.biggest_lead : "—"}</div></div>
    <div class="tile"><div class="k">Longest run</div><div class="v">${g.longest_run != null ? g.longest_run : "—"}</div><div class="note">unanswered</div></div>
  </div>

  ${potgBadge(g)}

  <div class="grid cols-2">
    <div class="card"><h2>${boxTitle} <span class="hint">${boxHint}</span></h2>
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("Player")}${th("PTS")}${hasScoring ? `${th("2PM", { title: "Made two-pointers (attempts not recorded)" })}${th("3PM", { title: "Made three-pointers (attempts not recorded)" })}${th("FTM", { title: "Made free throws (attempts not recorded)" })}` : ""}${hasReb ? th("REB") : ""}${hasAst ? th("AST") : ""}${hasFoul ? th("PF") : ""}</tr></thead>
        <tbody>${scorers}
          <tr class="total"><td>Shake Jelly Balls</td>${intCell(g.us)}${hasScoring ? `${intCell(tTwo)}${intCell(tThree)}${intCell(tFt)}` : ""}${hasReb ? intCell(tl.reb) : ""}${hasAst ? intCell(tl.ast) : ""}${hasFoul ? intCell(tl.foul) : ""}</tr>
        </tbody>
      </table></div>
    </div>
    <div class="card"><h2>By half <span class="hint">${fromPbp ? "from the scoring play-by-play" : "team scores by half"}</span></h2>
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("", { sortable: false })}${th("SJB", { sortable: false })}${th(g.opponent, { sortable: false })}${th("Margin", { sortable: false })}</tr></thead>
        <tbody>${halves || `<tr><td class="muted" colspan="4">No play-by-play.</td></tr>`}</tbody>
      </table></div>
    </div>
  </div>

  ${(g.flow && g.flow.length > 1) ? `<div class="card"><h2>Game flow</h2>${flowChart(g.flow, g.opponent, g.flow_meta)}</div>` : ""}
  ${footer()}`;
}

/* a forfeit (or any no-box result): counts in the record, shows a nominal
   score for the standings, but has no box score, play-by-play or stats */
function viewForfeitGame(g, won) {
  const notes = (g.notes || []).map(x => `<div class="banner">${esc(x)}</div>`).join("");
  const score = g.nominal_score
    ? `<div class="sb-team ${won ? "win" : ""}"><div class="name">Shake Jelly Balls</div><div class="score">${g.us}</div></div>
       <div class="sb-sep">${g.stage ? `${esc(g.stage.label)}<br>` : g.round ? `Round ${g.round}<br>` : ""}${resultPill(g.result)}<br>${esc(g.date_disp)}</div>
       <div class="sb-team ${!won && g.result === "L" ? "win" : ""}"><div class="name">${esc(g.opponent)}</div><div class="score">${g.them}</div></div>`
    : `<div class="sb-team ${won ? "win" : ""}"><div class="name">Shake Jelly Balls</div><div class="score">—</div></div>
       <div class="sb-sep">${g.stage ? `${esc(g.stage.label)}<br>` : g.round ? `Round ${g.round}<br>` : ""}${resultPill(g.result)}<br>${esc(g.date_disp)}</div>
       <div class="sb-team"><div class="name">${esc(g.opponent)}</div><div class="score">—</div></div>`;
  return `
  <div class="crumbs"><a href="#/schedule">Schedule</a> › ${esc(g.opponent)} <span class="tag warn">forfeit</span></div>
  <div class="card">
    <div class="scoreboard result-${g.result}">${score}</div>
  </div>
  ${notes}
  <div class="card"><p class="muted">No box score, play-by-play or player stats for this game — it's a forfeit. It counts toward the win/loss record${g.nominal_score ? ` and the nominal <strong>${g.us}–${g.them}</strong> is shown for the record` : ""}, but is excluded from scoring, averages and ratings.</p></div>
  ${footer()}`;
}

function potgBadge(g) {
  if (!g.potg) return "";
  const v = g.potg.stat === "GmSc" ? `${n(g.potg.value)} GmSc` : `${g.potg.value} pts`;
  return `<div class="potg">
    <span class="potg-star">★</span>
    <span class="potg-lbl">Player of the Game</span>
    <a class="potg-name" href="#/player/${g.potg.slug}">${esc(g.potg.name)}</a>
    <span class="potg-stat">${v}</span>
  </div>`;
}

// --- play-by-play & key moments (game page) --------------------------------
const HL_ICON = { run: "🔥", tie: "=", lead: "⇄", "lead-max": "★", final: "🏁", penalty: "⚑" };
function halfName(h) { return h === 1 ? "1st half" : h === 2 ? "2nd half" : `Half ${h}`; }
function halfTag(h) { return `H${h}`; }

function pbpWho(who, team) {
  if (team !== "us") return esc(who);        // opponent or neutral: plain text
  const p = findByName(who);
  return p ? playerLink(p) : esc(who);
}

/* Key-moments rendering, shared by the game page and the home "Latest result" card.
   Each row: a plain time marker (1st/2nd + clock), the event, and a labelled score
   line with the leading side emphasised — no cryptic icons or bare scores. */
function kmHalf(h) { return h === 1 ? "1st" : h === 2 ? "2nd" : "H" + h; }
function kmScore(h, opponent) {
  // Bold the side (name + score) the moment is about: an SJB run bolds "SJB <us>",
  // an opponent run bolds "<opp> <them>". Ties/neutral moments bold neither.
  return `<span class="km-sjb${h.team === "us" ? " on" : ""}">SJB ${h.us}</span>`
    + `<span class="km-vs">–</span>`
    + `<span class="km-opp${h.team === "them" ? " on" : ""}">${esc(opponent)} ${h.them}</span>`;
}
function kmItems(highlights, opponent) {
  return highlights.map(h => `<li class="km-item km-${h.team || "neutral"}">
    <div class="km-when"><span class="km-half">${kmHalf(h.half)}</span><span class="km-time">${h.t}</span></div>
    <div class="km-main">
      <div class="km-text">${esc(h.text)}</div>
      <div class="km-score">${kmScore(h, opponent)}</div>
    </div>
  </li>`).join("");
}
function keyMomentsCard(g) {
  if (!g.highlights || !g.highlights.length) return "";
  return `<div class="card"><h2>Key moments</h2>
    <ul class="key-moments">${kmItems(g.highlights, g.opponent)}</ul></div>`;
}

function pbpRow(e) {
  if (e.kind === "penalty") {
    return `<div class="pbp-row pbp-pen"><span class="pbp-t">${esc(e.t)}</span>
      <span class="pbp-desc"><strong>${esc(e.who)}</strong> — ${esc(e.label)}</span>
      <span class="pbp-sc">${e.us}–${e.them}</span></div>`;
  }
  const assist = e.assist ? ` <span class="pbp-ast">(assist: ${esc(e.assist)})</span>` : "";
  return `<div class="pbp-row team-${e.team}${e.score ? " is-score" : ""}">
    <span class="pbp-t">${esc(e.t)}</span>
    <span class="pbp-desc">${pbpWho(e.who, e.team)} ${esc(e.label)}${assist}</span>
    <span class="pbp-sc">${e.score ? `${e.us}–${e.them}` : ""}</span>
  </div>`;
}

function pbpCard(g) {
  if (!g.pbp || !g.pbp.length) return "";
  const halves = [...new Set(g.pbp.map(e => e.half))].sort((a, b) => a - b);
  const body = halves.map(h =>
    `<div class="pbp-half">${halfName(h)}</div>` +
    g.pbp.filter(e => e.half === h).map(pbpRow).join("")
  ).join("");
  return `<div class="card"><h2>Play-by-play</h2>
    <label class="pbp-filter"><input type="checkbox" class="pbp-scoring-only"> Scoring plays only</label>
    <div class="pbp-feed">${body}</div>
  </div>`;
}

function viewGame(id) {
  const g = byId(DATA.games, id);
  if (!g) return notFound("game");
  const won = g.result === "W";

  if (g.forfeit) return viewForfeitGame(g, won);
  if (g.partial) return viewPartialGame(g, won);

  const ff = g.four_factors, off = g.opp_four_factors;

  const notes = (g.notes || []).map(x => `<div class="banner">${esc(x)}</div>`).join("");

  const ffRows = [
    ["Effective FG%", ff.efg, off.efg, "%"],
    ["Turnover %", ff.tov_pct, off.tov_pct, "%"],
    ["Off. rebound %", ff.oreb_pct, off.oreb_pct, "%"],
    ["FT rate", ff.ft_rate, off.ft_rate, ""],
  ].map(([k, a, b, u]) => `<tr><td>${k}</td>${cell(a, u === "%" ? 1 : 3)}${cell(b, u === "%" ? 1 : 3)}</tr>`).join("");

  const pregameRow = g.penalty
    ? `<tr><td>Pre-game</td>${intCell(g.penalty.us)}${intCell(g.penalty.them)}${pmCell(g.penalty.us - g.penalty.them)}</tr>`
    : "";
  const halves = pregameRow + (g.half_scores || []).map(h =>
    `<tr><td>Half ${h.half}</td>${intCell(h.us)}${intCell(h.them)}${pmCell(h.us - h.them)}</tr>`).join("");

  const lineups = (g.lineups || []).map(l => `<tr>
    <td>${l.players.map(nm => { const p = findByName(nm); return p ? playerLink(p) : esc(nm); }).join(", ")}</td>
    ${cell(l.min)}${intCell(l.for)}${intCell(l.against)}${pmCell(l.plus_minus)}
  </tr>`).join("");

  return `
  <div class="crumbs"><a href="#/schedule">Schedule</a> › ${esc(g.opponent)}</div>
  <div class="card">
    <div class="scoreboard result-${g.result}">
      <div class="sb-team ${won ? "win" : ""}"><div class="name">Shake Jelly Balls</div><div class="score">${g.us}</div></div>
      <div class="sb-sep">${g.stage ? `${esc(g.stage.label)}<br>` : g.round ? `Round ${g.round}<br>` : ""}${resultPill(g.result)}<br>${esc(g.date_disp)}</div>
      <div class="sb-team ${!won && g.result === "L" ? "win" : ""}"><div class="name">${esc(g.opponent)}</div><div class="score">${g.them}</div></div>
    </div>
  </div>
  ${notes}
  <div class="tiles" style="margin-bottom:18px">
    <div class="tile"><div class="k">Margin</div><div class="v">${g.margin > 0 ? "+" : ""}${g.margin}</div></div>
    <div class="tile"><div class="k">Off / Def rtg</div><div class="v" style="font-size:19px">${n(g.ratings.off)}<small> / ${n(g.ratings.def)}</small></div><div class="note">per 100 poss</div></div>
    <div class="tile"><div class="k">TOV margin</div><div class="v">${g.tov_margin > 0 ? "+" : ""}${g.tov_margin}</div></div>
    <div class="tile"><div class="k">Biggest lead</div><div class="v">${g.biggest_lead != null ? "+" + g.biggest_lead : "—"}</div></div>
    <div class="tile"><div class="k">Longest run</div><div class="v">${g.longest_run != null ? g.longest_run : "—"}</div><div class="note">unanswered</div></div>
  </div>

  ${potgBadge(g)}

  <div class="card"><h2>Box score</h2>
    ${boxTable(g.box_us, { team: g.team_line, opponent: g.opponent })}
  </div>

  <div class="grid cols-2">
    <div class="card"><h2>Team totals${g.penalty ? ` <span class="hint">on-court scoring — excludes the pre-game penalty points</span>` : ""}</h2>
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("", { sortable: false })}${th("PTS", { sortable: false })}${th("FG", { sortable: false })}${th("3P", { sortable: false })}${th("FT", { sortable: false })}${th("REB", { sortable: false })}${th("AST", { sortable: false })}${th("STL", { sortable: false })}${th("TO", { sortable: false })}${th("PF", { sortable: false })}</tr></thead>
        <tbody>
          <tr><td>SJB</td>${intCell(g.team_line.pts)}${splitCell(g.team_line.fgm, g.team_line.fga)}${splitCell(g.team_line.tpm, g.team_line.tpa)}${splitCell(g.team_line.ftm, g.team_line.fta)}${intCell(g.team_line.reb)}${intCell(g.team_line.ast)}${intCell(g.team_line.stl)}${intCell(g.team_line.to)}${intCell(g.team_line.foul)}</tr>
          <tr><td>${esc(g.opponent)}</td>${intCell(g.opp_line.pts)}${splitCell(g.opp_line.fgm, g.opp_line.fga)}${splitCell(g.opp_line.tpm, g.opp_line.tpa)}${splitCell(g.opp_line.ftm, g.opp_line.fta)}${intCell(g.opp_line.reb)}${intCell(g.opp_line.ast)}${intCell(g.opp_line.stl)}${intCell(g.opp_line.to)}${intCell(g.opp_line.foul)}</tr>
        </tbody>
      </table></div>
    </div>
    <div class="card"><h2>Four factors</h2>
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("", { sortable: false })}${th("SJB", { sortable: false })}${th(g.opponent, { sortable: false })}</tr></thead>
        <tbody>${ffRows}</tbody>
      </table></div>
    </div>
  </div>

  <div class="grid cols-2">
    <div class="card"><h2>By half${g.penalty ? ` <span class="hint">incl. pre-game penalty points</span>` : ""}</h2>
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("", { sortable: false })}${th("SJB", { sortable: false })}${th(g.opponent, { sortable: false })}${th("Margin", { sortable: false })}</tr></thead>
        <tbody>${halves || `<tr><td class="muted" colspan="4">No play-by-play.</td></tr>`}</tbody>
      </table></div>
    </div>
    <div class="card"><h2>Game flow</h2>${flowChart(g.flow, g.opponent, g.flow_meta)}</div>
  </div>

  ${keyMomentsCard(g)}

  <div class="card"><h2>Five-man lineups</h2>
    <div class="table-scroll"><table class="stat">
      <thead><tr>${th("Lineup", { sortable: false })}${th("MIN")}${th("For")}${th("Agst")}${th("+/-")}</tr></thead>
      <tbody>${lineups || `<tr><td class="muted" colspan="5">No play-by-play.</td></tr>`}</tbody>
    </table></div>
  </div>

  ${pbpCard(g)}
  ${footer()}`;
}

function viewPlayers() {
  // default order: most games played first (ties broken by scoring average)
  const players = DATA.players.slice().sort((a, b) =>
    (b.games - a.games) || (b.averages.pts - a.averages.pts));
  const rows = players.map(p => `<tr>
    <td>${playerLink(p)}${sampleTag(p)}</td>
    ${intCell(p.games)}${cell(p.mp_avg, 0)}
    ${cell(p.averages.pts)}${cell(p.averages.reb)}${cell(p.averages.ast)}${cell(p.averages.stl)}${cell(p.averages.blk)}
    ${cell(p.fg_pct)}${cell(p.tp_pct)}${cell(p.efg)}
    ${cell(p.gmsc_avg)}${cell(p.fp_avg)}${pmCell(p.plus_minus_avg)}
  </tr>`).join("");
  return `
  <div class="page-head"><h1>Players</h1></div>
  <div class="card"><div class="table-scroll"><table class="stat">
    <thead><tr>${th("Player")}${th("GP")}${th("MPG")}${th("PPG")}${th("RPG")}${th("APG")}${th("SPG")}${th("BPG")}${th("FG%")}${th("3P%")}${th("eFG%")}${th("GmSc")}${th("FP")}${th("+/-")}</tr></thead>
    <tbody>${rows}</tbody>
  </table></div>
  <p class="muted" style="font-size:12px;margin-top:10px">eFG% weights threes; GmSc is Hollinger Game Score; FP is ESPN fantasy. One-game players are flagged small-sample. See the <a href="#/glossary">glossary</a>.</p>
  </div>
  ${footer()}`;
}

/* avatar: real photo if site/img/players/<slug>.jpg exists, else initials */
/* Avatar loader: a failed photo load shouldn't permanently show initials on the
   first hiccup. Walk a short list of candidate filenames (covers a transient drop
   — the next attempt usually hits the browser cache — and alternate extensions /
   casing on case-sensitive hosts), and only fall back to the initials box once
   every candidate has genuinely failed. */
function avatarError(img) {
  const list = (img.dataset.list || "").split("|").filter(Boolean);
  const i = (+img.dataset.i || 0) + 1;
  if (i < list.length) {
    img.dataset.i = i;
    img.src = "img/players/" + list[i];
  } else {
    img.onerror = null;
    img.style.display = "none";
    const ini = img.nextElementSibling;
    if (ini) ini.style.display = "flex";
  }
}
function playerAvatar(p) {
  const initials = esc(p.name.replace(/[^A-Za-z. ]/g, "").split(/[.\s]+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase() || "?");
  const slug = esc(p.slug);
  // .jpg, then one retry of .jpg (shrugs off a transient drop — usually a cache hit),
  // then .png in case a photo was saved as PNG. Then the initials box.
  const list = [slug + ".jpg", slug + ".jpg", slug + ".png"].join("|");
  return `<div class="pp-photo">
    <img src="img/players/${slug}.jpg" alt="${esc(p.full_name)}" loading="lazy"
         data-i="0" data-list="${list}" onerror="avatarError(this)">
    <div class="pp-initials" style="display:none">${initials}</div>
  </div>`;
}

/* one row of the Per Game / Totals season tables, from a stat block */
function seasonCell(b, career, showTeam) {
  const label = career ? "Career" : esc(b.season_label);
  const team = (showTeam && !career && b.team) ? `<br><span class="muted" style="font-size:10.5px">${esc(b.team)}</span>` : "";
  return `<td>${label}${team}</td>`;
}
/* one row of the bbref-style SUMMARY table in the player header */
function sumRow(b, label, isCareer) {
  const a = b.averages;
  return `<tr class="${isCareer ? "total" : ""}">
    <td>${label}</td>
    ${intCell(b.games)}${cell(a.pts)}${cell(a.reb)}${cell(a.ast)}
    ${cell(b.fg_pct)}${cell(b.tp_pct)}${cell(b.ft_pct)}${cell(b.efg)}${cell(b.ts)}${cell(b.gmsc_avg)}
  </tr>`;
}
function perGameRow(b, { career = false, showTeam = false } = {}) {
  const a = b.averages;
  return `<tr class="${career ? "total" : ""}">
    ${seasonCell(b, career, showTeam)}
    ${intCell(b.games)}${cell(b.mp_avg, 0)}
    ${cell(a.fgm)}${cell(a.fga)}${cell(b.fg_pct)}
    ${cell(a.tpm)}${cell(a.tpa)}${cell(b.tp_pct)}
    ${cell(a.ftm)}${cell(a.fta)}${cell(b.ft_pct)}
    ${cell(a.oreb)}${cell(a.dreb)}${cell(a.reb)}${cell(a.ast)}${cell(a.stl)}${cell(a.blk)}${cell(a.to)}${cell(a.foul)}
    ${cell(a.pts)}${cell(b.gmsc_avg)}${cell(b.fp_avg)}${pmCell(b.plus_minus_avg)}
  </tr>`;
}
function totalsRow(b, { career = false, showTeam = false } = {}) {
  const t = b.totals;
  return `<tr class="${career ? "total" : ""}">
    ${seasonCell(b, career, showTeam)}
    ${intCell(b.games)}${intCell(b.mp_total)}
    ${intCell(t.fgm)}${intCell(t.fga)}${cell(b.fg_pct)}
    ${intCell(t.tpm)}${intCell(t.tpa)}${cell(b.tp_pct)}
    ${intCell(t.ftm)}${intCell(t.fta)}${cell(b.ft_pct)}
    ${intCell(t.oreb)}${intCell(t.dreb)}${intCell(t.reb)}${intCell(t.ast)}${intCell(t.stl)}${intCell(t.blk)}${intCell(t.to)}${intCell(t.foul)}
    ${intCell(t.pts)}${cell(b.gmsc_total)}${cell(b.fp_total)}
  </tr>`;
}

/* ---- player page: advanced / per-36 / shooting / highs / splits -------- */
function advRow(b, { career = false, showTeam = false } = {}) {
  return `<tr class="${career ? "total" : ""}">
    ${seasonCell(b, career, showTeam)}
    ${intCell(b.games)}${cell(b.mp_avg, 0)}
    ${cell(b.ts)}${cell(b.efg)}${cell(b.usg)}
    ${cell(b.gmsc_avg)}${cell(b.fp_avg)}${pmCell(b.plus_minus_avg)}
  </tr>`;
}
function per36Row(b, { career = false, showTeam = false } = {}) {
  const x = b.per36 || {};
  return `<tr class="${career ? "total" : ""}">
    ${seasonCell(b, career, showTeam)}
    ${intCell(b.games)}${intCell(b.mp_total)}
    ${cell(x.pts)}${cell(x.reb)}${cell(x.ast)}${cell(x.stl)}${cell(x.blk)}${cell(x.to)}${cell(x.fgm)}${cell(x.tpm)}${cell(x.ftm)}
  </tr>`;
}
function shootRow(b, { career = false, showTeam = false } = {}) {
  const s = b.shot || {};
  return `<tr class="${career ? "total" : ""}">
    ${seasonCell(b, career, showTeam)}
    ${intCell(b.games)}
    ${cell(b.fg_pct)}${cell(s.fg2_pct)}${cell(b.tp_pct)}${cell(b.ft_pct)}
    ${cell(b.efg)}${cell(b.ts)}
    ${cell(s.pct_pts_2)}${cell(s.pct_pts_3)}${cell(s.pct_pts_ft)}${cell(s.fg3a_rate, 3)}
  </tr>`;
}
const HIGH_LABELS = { pts: "Points", reb: "Rebounds", ast: "Assists", stl: "Steals",
  blk: "Blocks", tpm: "3-pointers", fp: "Fantasy pts", gmsc: "Game Score" };
function highsCard(highs) {
  if (!highs) return "";
  const order = ["pts", "reb", "ast", "stl", "blk", "tpm", "fp", "gmsc"];
  const rows = order.filter(k => highs[k]).map(k => {
    const h = highs[k];
    const multi = (h.count || 1) > 1 && h.value > 1;
    const mult = multi ? ` <span class="hi-mult" title="Reached in ${h.count} games">×${h.count}</span>` : "";
    return `<dt>${HIGH_LABELS[k]}</dt><dd><span class="hi-val"><strong>${n(h.value, Number.isInteger(h.value) ? 0 : 1)}</strong>${mult}</span>
      <a class="muted hi-game" href="#/game/${h.game_id}">${multi ? "first " : ""}vs ${esc(h.opponent)}, ${esc(h.date_disp)}</a></dd>`;
  }).join("");
  if (!rows) return "";
  return `<div class="card"><h2>Career highs</h2>
    <dl class="kv kv-highs">${rows}</dl></div>`;
}
function splitTable(title, rows, { record = true, games = true } = {}) {
  if (!rows || !rows.length) return "";
  const body = rows.map(s => `<tr>
    <td>${esc(s.label)}</td>
    ${record ? `<td class="num">${s.w}-${s.l}${s.d ? "-" + s.d : ""}</td>` : ""}
    ${games ? intCell(s.g) : ""}${cell(s.pts)}${cell(s.reb)}${cell(s.ast)}${cell(s.gmsc)}
  </tr>`).join("");
  return `<div class="split-block"><h3>${esc(title)}</h3>
    <div class="table-scroll"><table class="stat">
      <thead><tr>${th("", { sortable: false })}${record ? th("W-L", { sortable: false }) : ""}${games ? th("G", { sortable: false }) : ""}${th("PTS", { sortable: false })}${th("TRB", { sortable: false })}${th("AST", { sortable: false })}${th("GmSc", { sortable: false })}</tr></thead>
      <tbody>${body}</tbody></table></div></div>`;
}
function splitsCard(sp) {
  if (!sp) return "";
  const parts = [
    splitTable("By opponent", sp.by_opponent, { record: true, games: false }),
    splitTable("By result", sp.by_result, { record: false, games: true }),
    splitTable("Regular season / playoffs", sp.by_phase, { record: true, games: true }),
    splitTable("By month", sp.by_month),
  ].join("");
  if (!parts) return "";
  return `<div class="card"><h2>Splits</h2>
    <div class="splits-grid">${parts}</div></div>`;
}

function viewPlayer(slug) {
  const p = find(slug);
  if (!p || !p.career) return notFound("player");
  const c = p.career, a = c.averages, tt = c.totals;
  const multi = (p.seasons || []).length > 1;
  const showTeam = !!p.multi_team;

  const pgHead = `<thead><tr>
    ${th("Season", { sortable: false })}${th("G", { sortable: false })}${th("MP", { sortable: false })}
    ${th("FG", { sortable: false })}${th("FGA", { sortable: false })}${th("FG%", { sortable: false })}
    ${th("3P", { sortable: false })}${th("3PA", { sortable: false })}${th("3P%", { sortable: false })}
    ${th("FT", { sortable: false })}${th("FTA", { sortable: false })}${th("FT%", { sortable: false })}
    ${th("ORB", { sortable: false })}${th("DRB", { sortable: false })}${th("TRB", { sortable: false })}${th("AST", { sortable: false })}${th("STL", { sortable: false })}${th("BLK", { sortable: false })}${th("TOV", { sortable: false })}${th("PF", { sortable: false })}
    ${th("PTS", { sortable: false })}${th("GmSc", { sortable: false })}${th("FP", { sortable: false })}${th("+/-", { sortable: false })}
  </tr></thead>`;
  const totHead = `<thead><tr>
    ${th("Season", { sortable: false })}${th("G", { sortable: false })}${th("MP", { sortable: false })}
    ${th("FG", { sortable: false })}${th("FGA", { sortable: false })}${th("FG%", { sortable: false })}
    ${th("3P", { sortable: false })}${th("3PA", { sortable: false })}${th("3P%", { sortable: false })}
    ${th("FT", { sortable: false })}${th("FTA", { sortable: false })}${th("FT%", { sortable: false })}
    ${th("ORB", { sortable: false })}${th("DRB", { sortable: false })}${th("TRB", { sortable: false })}${th("AST", { sortable: false })}${th("STL", { sortable: false })}${th("BLK", { sortable: false })}${th("TOV", { sortable: false })}${th("PF", { sortable: false })}
    ${th("PTS", { sortable: false })}${th("GmSc", { sortable: false })}${th("FP", { sortable: false })}
  </tr></thead>`;

  const seasonPG = (p.seasons || []).map(s => perGameRow(s, { showTeam })).join("");
  const seasonTOT = (p.seasons || []).map(s => totalsRow(s, { showTeam })).join("");
  const seasonADV = (p.seasons || []).map(s => advRow(s, { showTeam })).join("");
  const seasonP36 = (p.seasons || []).map(s => per36Row(s, { showTeam })).join("");
  const seasonSH = (p.seasons || []).map(s => shootRow(s, { showTeam })).join("");

  const logRows = p.log.map(l => `<tr>
    <td class="num" data-v="${l.round ?? 999}">${l.stage ? `<span class="tag stage" title="${esc(l.stage.label)}">${esc(l.stage.short)}</span>` : (l.round ?? "—")}</td>
    <td class="num" data-v="${l.date.replace(/-/g, "")}">${gameLink({ id: l.game_id, date_disp: l.date_disp }, l.date_disp)}</td>
    <td class="muted" style="font-size:11px">${esc(l.season_label)}</td>
    <td><a href="#/game/${l.game_id}">${esc(l.opponent)}</a></td>
    <td data-v="${l.result === "W" ? 2 : l.result === "D" ? 1 : 0}">${resultPill(l.result)} <span class="muted num">${l.us}-${l.them}</span></td>
    ${cell(l.min, 0)}${intCell(l.pts)}${splitCell(l.fgm, l.fga)}${splitCell(l.tpm, l.tpa)}${splitCell(l.ftm, l.fta)}
    ${intCell(l.oreb ?? "")}${intCell(l.reb)}${intCell(l.ast)}${intCell(l.stl)}${intCell(l.blk)}${intCell(l.to)}${intCell(l.foul)}
    ${pmCell(l.plus_minus)}${cell(l.gmsc)}${cell(l.fp)}
  </tr>`).join("");

  const bg = p.best_game;

  return `
  <div class="crumbs"><a href="#/players">Players</a> › ${esc(p.name)}</div>

  <div class="pp-head">
    ${playerAvatar(p)}
    <div class="pp-meta">
      <h1>${esc(p.full_name)}</h1>
      ${p.nickname ? `<p class="pp-nick">(${esc(p.nickname)})</p>` : ""}
      <p class="pp-bio">${p.number != null ? `<strong>No.</strong> ${p.number} <span class="pp-sep">▪</span> ` : ""}<strong>Position:</strong> ${p.position ? esc(p.position) : "—"} <span class="pp-sep">▪</span> <strong>Role:</strong> ${p.core ? "Regular" : "Fill-in"}</p>
      <p class="pp-bio"><strong>Seasons:</strong> ${p.num_seasons} <span class="pp-sep">▪</span> <strong>Games:</strong> ${c.games}${p.small_sample ? ` <span class="pp-sep">▪</span> <span class="tag small">small sample</span>` : ""}</p>
      <p class="pp-bio pp-foot">Best ${showTeam ? "SJB " : ""}game: ${bg.pts} pts, ${n(bg.gmsc)} GmSc vs ${esc(bg.opponent)} (<a href="#/game/${bg.game_id}">${esc(bg.date_disp)}</a>)${p.potg_count ? ` <span class="pp-sep">▪</span> <strong>Player of the Game:</strong> ${p.potg_count}×` : ""}</p>
    </div>
    <div class="pp-summary">
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("Summary", { sortable: false })}${["G", "PTS", "TRB", "AST", "FG%", "3P%", "FT%", "eFG%", "TS%", "GmSc"].map(h => th(h, { sortable: false })).join("")}</tr></thead>
        <tbody>
          ${multi ? sumRow(p.seasons[p.seasons.length - 1], esc(p.seasons[p.seasons.length - 1].season_label), false) : ""}
          ${sumRow(c, multi ? "Career" : esc((p.seasons[0] || {}).season_label || "Season"), multi)}
        </tbody>
      </table></div>
    </div>
  </div>

  <div class="card"><h2>Per Game</h2>
    <div class="table-scroll"><table class="stat">${pgHead}<tbody>
      ${seasonPG}
      ${multi ? perGameRow(c, { career: true, showTeam }) : ""}
    </tbody></table></div>
    ${c.games_detail < c.games ? `<p class="muted" style="font-size:12px;margin-top:8px">Rebounds, assists, shooting and advanced stats are from ${c.games_detail} of ${c.games} games — the rest weren't fully recorded. Points count for every game.</p>` : ""}
  </div>

  <div class="card"><h2>Totals</h2>
    <div class="table-scroll"><table class="stat">${totHead}<tbody>
      ${seasonTOT}
      ${multi ? totalsRow(c, { career: true, showTeam }) : ""}
    </tbody></table></div>
  </div>

  <div class="card"><h2>Advanced</h2>
    <div class="table-scroll"><table class="stat">
      <thead><tr>
        ${th("Season", { sortable: false })}${th("G", { sortable: false })}${th("MP", { sortable: false })}
        ${th("TS%", { sortable: false, title: "True shooting %" })}${th("eFG%", { sortable: false })}${th("USG%", { sortable: false, title: "Usage rate — share of team possessions used while on court" })}
        ${th("GmSc", { sortable: false })}${th("FP", { sortable: false })}${th("+/-", { sortable: false })}
      </tr></thead>
      <tbody>${seasonADV}${multi ? advRow(c, { career: true, showTeam }) : ""}</tbody>
    </table></div>
  </div>

  <div class="card"><h2>Per 36 Minutes <span class="hint">scaled to 36 minutes</span></h2>
    <div class="table-scroll"><table class="stat">
      <thead><tr>
        ${th("Season", { sortable: false })}${th("G", { sortable: false })}${th("MP", { sortable: false })}
        ${th("PTS", { sortable: false })}${th("TRB", { sortable: false })}${th("AST", { sortable: false })}${th("STL", { sortable: false })}${th("BLK", { sortable: false })}${th("TOV", { sortable: false })}${th("FG", { sortable: false })}${th("3P", { sortable: false })}${th("FT", { sortable: false })}
      </tr></thead>
      <tbody>${seasonP36}${multi ? per36Row(c, { career: true, showTeam }) : ""}</tbody>
    </table></div>
  </div>

  <div class="card"><h2>Shooting</h2>
    <div class="table-scroll"><table class="stat">
      <thead><tr>
        ${th("Season", { sortable: false })}${th("G", { sortable: false })}
        ${th("FG%", { sortable: false })}${th("2P%", { sortable: false })}${th("3P%", { sortable: false })}${th("FT%", { sortable: false })}
        ${th("eFG%", { sortable: false })}${th("TS%", { sortable: false })}
        ${th("%Pts 2P", { sortable: false, title: "Share of points from two-pointers" })}${th("%Pts 3P", { sortable: false })}${th("%Pts FT", { sortable: false })}${th("3PAr", { sortable: false, title: "Share of field-goal attempts that are threes" })}
      </tr></thead>
      <tbody>${seasonSH}${multi ? shootRow(c, { career: true, showTeam }) : ""}</tbody>
    </table></div>
  </div>

  <div class="grid cols-2">
    ${highsCard(p.career_highs)}
    <div class="card"><h2>Scoring trend</h2>
      ${lineChart({
        labels: p.log.map(l => l.opponent),
        series: [{ color: "var(--accent)", values: p.log.map(l => l.pts) }],
        tip: i => `${p.log[i].date_disp} vs ${p.log[i].opponent}: ${p.log[i].pts} pts`,
        w: 380, h: 96, yMin: 0,
      })}
      <dl class="kv" style="margin-top:8px">
        <dt>Game Score / game</dt><dd>${n(c.gmsc_avg)}</dd>
        <dt>Fantasy / game</dt><dd>${n(c.fp_avg)}</dd>
        <dt>Plus/minus / game</dt><dd>${c.plus_minus_avg == null ? "—" : (c.plus_minus_avg > 0 ? "+" : "") + n(c.plus_minus_avg)}</dd>
      </dl>
    </div>
  </div>

  ${splitsCard(p.splits)}

  <div class="card"><h2>Game Log${showTeam ? ` <span class="hint">Shake Jelly Balls games</span>` : ""}</h2>
    <div class="table-scroll"><table class="stat">
      <thead><tr>${th("Rd")}${th("Date")}${th("Szn", { sortable: false })}${th("Opp")}${th("Result")}${th("MP")}${th("PTS")}${th("FG")}${th("3P")}${th("FT")}${th("ORB")}${th("TRB")}${th("AST")}${th("STL")}${th("BLK")}${th("TOV")}${th("PF")}${th("+/-")}${th("GmSc")}${th("FP")}</tr></thead>
      <tbody>${logRows}</tbody>
    </table></div>
  </div>
  ${footer()}`;
}

function viewLeaders() {
  const boards = [
    ["Points per game", "ppg", 1, "PPG"],
    ["Rebounds per game", "rpg", 1, "RPG"],
    ["Assists per game", "apg", 1, "APG"],
    ["Steals per game", "spg", 1, "SPG"],
    ["Blocks per game", "bpg", 1, "BPG"],
    ["Fantasy per game", "fp", 1, "FP"],
    ["Game Score per game", "gmsc", 1, "GmSc"],
    ["Plus/minus per game", "plus_minus", 1, "+/-"],
  ];
  const L = leadersScope();
  const cards = boards.map(([title, key, d, unit]) => {
    const rows = (L[key] || []).map((x, i) => `<div class="leader-row ${i === 0 ? "top" : ""}">
      <span class="leader-rank">${i + 1}</span>
      <span class="nm">${playerLink(find(x.slug))}${x.small_sample ? ' <span class="tag small">1g</span>' : ""}</span>
      <span class="val">${x.value > 0 && key === "plus_minus" ? "+" : ""}${n(x.value, d)}</span>
    </div>`).join("") || `<div class="muted" style="font-size:12px">—</div>`;
    return `<div class="card leader-card"><h3>${title} <span class="muted" style="font-weight:400">(${unit})</span></h3>${rows}</div>`;
  }).join("");
  return `
  <div class="page-head"><div class="head-row"><h1>Leaders</h1>${seasonSelect()}</div><div class="sub">${esc(seasonName(selSeason))}</div></div>
  <div class="leader-grid">${cards}</div>
  ${footer()}`;
}

function viewTeam() {
  const t = teamScope(), adv = t.advanced, ff = t.four_factors, off = t.opp_four_factors;
  const rec = `${t.record.w}-${t.record.l}${t.record.d ? "-" + t.record.d : ""}`;
  const shoot = [
    ["Field goals", t.totals, t.opp_totals, "fgm", "fga", t.fg_pct, t.opp_fg_pct],
    ["Three-point", t.totals, t.opp_totals, "tpm", "tpa", t.tp_pct, t.opp_tp_pct],
    ["Free throws", t.totals, t.opp_totals, "ftm", "fta", t.ft_pct, null],
  ].map(([k, us, op, m, aa, up, opp]) => `<tr><td>${k}</td>
    <td class="num">${us[m]}-${us[aa]}${up != null ? ` · ${n(up)}%` : ""}</td>
    <td class="num">${op[m]}-${op[aa]}${opp != null ? ` · ${n(opp)}%` : ""}</td></tr>`).join("");

  const defRows = t.defense_rows.map(r => `<tr>
    <td><a href="#/game/${r.game_id}">${esc(r.opponent)}</a></td>
    <td class="num" data-v="${(r.date || "").replace(/-/g, "")}">${esc(r.date_disp)}</td>
    ${intCell(r.opp_pts)}${cell(r.def_rtg)}${cell(r.opp_poss)}${intCell(r.tov_forced)}${pmCell(r.tov_margin)}
    <td>${r.partial ? '<span class="tag warn">not tracked</span>' : r.reliable ? "" : '<span class="tag warn">partial</span>'}</td>
  </tr>`).join("");

  const lineups = t.lineups.map(l => `<tr>
    <td>${l.players.map(nm => { const p = findByName(nm); return p ? playerLink(p) : esc(nm); }).join(", ")}</td>
    ${cell(l.min)}${intCell(l.for)}${intCell(l.against)}${pmCell(l.plus_minus)}
  </tr>`).join("");

  const h2hRows = (t.head_to_head || []).map(h => `<tr>
    <td><a href="#/game/${h.last_id}">${esc(h.opponent)}</a></td>
    ${intCell(h.g)}
    <td class="num" data-v="${h.w * 100 - h.l}">${h.w}-${h.l}${h.d ? "-" + h.d : ""}</td>
    ${cell(h.ppg_for)}${cell(h.ppg_against)}${pmCell(h.margin)}
  </tr>`).join("");

  const ffRows = [
    ["Effective FG%", ff.efg, off.efg],
    ["Turnover %", ff.tov_pct, off.tov_pct],
    ["Off. rebound %", ff.oreb_pct, off.oreb_pct],
    ["FT rate", ff.ft_rate, off.ft_rate],
  ].map(([k, a, b]) => `<tr><td>${k}</td>${cell(a, k === "FT rate" ? 3 : 1)}${cell(b, k === "FT rate" ? 3 : 1)}</tr>`).join("");

  return `
  <div class="page-head"><div class="head-row"><h1>Team — Shake Jelly Balls</h1>${seasonSelect()}</div><div class="sub">${esc(seasonName(selSeason))} · ${rec} · ${n(t.ppg_for)} for, ${n(t.ppg_against)} against · net ${adv.net_rtg > 0 ? "+" : ""}${n(adv.net_rtg)} per 100</div></div>

  <div class="tiles" style="margin-bottom:18px">
    <div class="tile hi"><div class="k">Off rating</div><div class="v">${n(adv.off_rtg)}</div><div class="note">per 100 poss</div></div>
    <div class="tile hi"><div class="k">Def rating</div><div class="v">${n(adv.def_rtg)}</div><div class="note">per 100 poss</div></div>
    <div class="tile"><div class="k">Net rating</div><div class="v">${adv.net_rtg > 0 ? "+" : ""}${n(adv.net_rtg)}</div></div>
    <div class="tile"><div class="k">Pace</div><div class="v">${n(adv.pace)}</div><div class="note">poss / game</div></div>
    <div class="tile"><div class="k">% pts from 3</div><div class="v">${n(adv.pct_pts_from_3)}<small>%</small></div></div>
  </div>

  ${(() => {
    const sbh = t.scoring_by_half, r = t.results;
    const sched = scheduleScope();
    const form = sched.slice(-5).map(g =>
      `<a href="#/game/${g.id}" class="chip ${g.result === "W" ? "w" : g.result === "L" ? "l" : "d"}" title="vs ${esc(g.opponent)}, ${esc(g.date_disp)}">${g.result}</a>`).join("");
    const halfTable = sbh ? `
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("", { sortable: false })}${th("SJB", { sortable: false })}${th("Opp", { sortable: false })}${th("Margin", { sortable: false })}</tr></thead>
        <tbody>
          <tr><td>First half</td>${cell(sbh.h1.us)}${cell(sbh.h1.them)}${pmCell(Math.round((sbh.h1.us - sbh.h1.them) * 10) / 10)}</tr>
          <tr><td>Second half</td>${cell(sbh.h2.us)}${cell(sbh.h2.them)}${pmCell(Math.round((sbh.h2.us - sbh.h2.them) * 10) / 10)}</tr>
        </tbody>
      </table></div>
      <p class="muted" style="font-size:12px;margin-top:8px">Average points per half over ${sbh.games} fully-tracked game${sbh.games === 1 ? "" : "s"}.</p>`
      : `<p class="muted">No half-by-half data yet.</p>`;
    const refLink = g => g ? `${g.margin > 0 ? "+" : ""}${g.margin} vs <a href="#/game/${g.game_id}">${esc(g.opponent)}</a>` : "—";
    return `
    <div class="grid cols-2">
      <div class="card"><h2>Scoring by half</h2>
        ${halfTable}
      </div>
      <div class="card"><h2>Margins &amp; results</h2>
        <dl class="kv">
          <dt>Average margin</dt><dd>${r.avg_margin == null ? "—" : (r.avg_margin > 0 ? "+" : "") + n(r.avg_margin)}</dd>
          <dt>Close games (≤5 pts)</dt><dd>${r.close.w}-${r.close.l}${r.close.d ? "-" + r.close.d : ""} <span class="muted">(${r.close.g})</span></dd>
          <dt>Wins by 15+</dt><dd>${r.blowout_wins}</dd>
          <dt>Biggest win</dt><dd>${refLink(r.best_win)}</dd>
          <dt>Heaviest loss</dt><dd>${refLink(r.worst_loss)}</dd>
        </dl>
        <div style="margin-top:10px"><div class="section-title" style="margin-bottom:5px">Recent form</div><div class="chip-row">${form || '<span class="muted">—</span>'}</div></div>
      </div>
    </div>`;
  })()}

  <div class="grid cols-2">
    <div class="card"><h2>Shooting — team vs opponents</h2>
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("", { sortable: false })}${th("Shake Jelly Balls", { sortable: false })}${th("Opponents", { sortable: false })}</tr></thead>
        <tbody>${shoot}</tbody>
      </table></div>
    </div>
    <div class="card"><h2>Four factors</h2>
      <div class="table-scroll"><table class="stat">
        <thead><tr>${th("", { sortable: false })}${th("SJB", { sortable: false })}${th("Opp", { sortable: false })}</tr></thead>
        <tbody>${ffRows}</tbody>
      </table></div>
    </div>
  </div>

  <div class="card"><h2>Head-to-head</h2>
    <div class="table-scroll"><table class="stat">
      <thead><tr>${th("Opponent")}${th("G")}${th("Record", { sortable: false })}${th("PPG for")}${th("PPG agst")}${th("Margin")}</tr></thead>
      <tbody>${h2hRows || `<tr><td class="muted" colspan="6">No games yet.</td></tr>`}</tbody>
    </table></div>
    <p class="muted" style="font-size:12px;margin-top:10px">Record includes forfeits; the scoring averages use played games only.</p>
  </div>

  <div class="card"><h2>Five-man lineups</h2>
    <div class="table-scroll"><table class="stat">
      <thead><tr>${th("Lineup", { sortable: false })}${th("MIN")}${th("For")}${th("Agst")}${th("+/-")}</tr></thead>
      <tbody>${lineups}</tbody>
    </table></div>
  </div>

  <div class="card"><h2>Defence &amp; opponent tracking <span class="hint">${t.reliable_count}/${t.games_tracked} games with complete opponent turnovers</span></h2>
    <div class="table-scroll"><table class="stat">
      <thead><tr>${th("Opponent")}${th("Date")}${th("Opp PTS")}${th("Def rtg")}${th("Opp poss")}${th("TOV forced")}${th("TOV margin")}${th("", { sortable: false })}</tr></thead>
      <tbody>${defRows}
        <tr class="total"><td>Season</td><td></td>${intCell(t.pts_against)}${cell(adv.def_rtg)}${cell(null)}${intCell(t.opp_totals.to)}${pmCell(t.tov_margin)}<td></td></tr>
      </tbody>
    </table></div>
  </div>
  ${footer()}`;
}

function viewGlossary() {
  return `
  <div class="page-head"><h1>Glossary &amp; about</h1></div>

  <div class="card"><h2>Metrics</h2>
    <dl class="glossary">
      <dt>Game Score (GmSc)</dt><dd>Hollinger's single-number summary of a game: <code>PTS + 0.4·FGM − 0.7·FGA − 0.4·(FTA−FTM) + 0.7·OREB + 0.3·DREB + STL + 0.7·AST + 0.7·BLK − 0.4·PF − TOV</code>. Roughly, 10 is a solid game and 20+ is excellent.</dd>
      <dt>Fantasy points (FP)</dt><dd>ESPN's default scoring: <code>PTS + 2·FGM − FGA + 3PM + FTM − FTA + REB + 2·AST + 4·STL + 4·BLK − 2·TOV</code>.</dd>
      <dt>Possessions</dt><dd><code>FGA − OREB + TOV + 0.44·FTA</code> — an estimate of how many times a team had the ball.</dd>
      <dt>Offensive / Defensive rating</dt><dd>Points scored (allowed) per 100 possessions. Net rating is offence minus defence.</dd>
      <dt>Pace</dt><dd>Possessions per game (averaged across both teams).</dd>
      <dt>Four factors</dt><dd><strong>eFG%</strong> = <code>(FGM + 0.5·3PM)/FGA</code> (shooting, crediting the extra point on a three); <strong>TOV%</strong> = turnovers per possession; <strong>OREB%</strong> = share of available offensive boards grabbed; <strong>FT rate</strong> = <code>FTA/FGA</code> (how often you get to the line).</dd>
      <dt>Turnover margin</dt><dd>Opponent turnovers minus ours. Positive is good.</dd>
      <dt>Plus/minus (+/-)</dt><dd>Team points scored minus allowed while a player was on the floor. Reconstructed from the play-by-play lineups and checked against the recorded box figure.</dd>
      <dt>True shooting (TS%)</dt><dd>Scoring efficiency counting twos, threes and free throws together: <code>PTS / (2·(FGA + 0.44·FTA))</code>. 55%+ is strong.</dd>
      <dt>Usage rate (USG%)</dt><dd>The share of the team's scoring possessions a player used (shots, trips to the line and turnovers) while on the floor, adjusted for minutes. ~20% is an average load; a go-to scorer runs higher.</dd>
      <dt>Per 36 minutes</dt><dd>A player's counting stats scaled to 36 minutes of play, so part-time and full-time players can be compared on a level field. Totals ÷ minutes × 36.</dd>
      <dt>Shooting profile</dt><dd><strong>2P% / 3P% / FT%</strong> are efficiency on each shot type; <strong>%Pts</strong> columns show how a player's points are split across twos, threes and free throws; <strong>3PAr</strong> is the share of field-goal attempts taken from three.</dd>
    </dl>
  </div>
  ${footer()}`;
}

/* ---- lookups + chrome --------------------------------------------------- */
function find(slug) { return byId(DATA.players, slug, "slug") || { slug, name: slug, jersey: null }; }
function findByName(name) { return DATA.players.find(p => p.name === name); }
function notFound(what) {
  return `<div class="page-head"><h1>Not found</h1><div class="sub">No ${esc(what)} by that name.</div></div>
    <div class="card"><a href="#/">← Back to home</a></div>`;
}
function footer() {
  return `<div class="footer">
    Shake Jelly Balls · built from box-score &amp; play-by-play exports · ${DATA.games.length} games<br>
    <a href="#/glossary">Glossary &amp; data notes</a> · generated ${esc((DATA.generated_at || "").slice(0, 10))}
  </div>`;
}

/* ---- league ladder ------------------------------------------------------ */
let ladderSeason = null;   // the ladder page has its own season state (own picker)
function viewLadder() {
  const ladders = DATA.ladder || {};
  const seasonKeys = (DATA.seasons || []).map(s => s.key);
  const hasTeams = k => ladders[k] && ladders[k].teams && ladders[k].teams.length;
  // default to the current season if it has a ladder, else the latest one that does
  if (ladderSeason === null || !ladders[ladderSeason]) {
    ladderSeason = hasTeams(DATA.current_season_key) ? DATA.current_season_key
      : ([...seasonKeys].reverse().find(hasTeams) || DATA.current_season_key || seasonKeys[seasonKeys.length - 1]);
  }
  const key = ladderSeason;
  const L = ladders[key];
  const statusLabel = L && L.status === "final" ? "final standings" : L && L.status === "in_progress" ? "in progress" : "";
  // the ladder is per-season only (no "All-time"), with its own picker
  const ladderSelect = `<div class="season-pick">Season <select class="ladder-season-select">${
    (DATA.seasons || []).map(s => `<option value="${s.key}"${s.key === key ? " selected" : ""}>${esc(s.label)}</option>`).join("")
  }</select></div>`;
  const header = `<div class="page-head"><div class="head-row"><h1>League ladder</h1>${ladderSelect}</div>
    <div class="sub">${esc(seasonName(key))}${statusLabel ? ` · ${statusLabel}` : ""}${L && L.updated ? ` · updated ${esc(L.updated)}` : ""}</div></div>`;

  if (!L || !L.teams || !L.teams.length) {
    return header + `<div class="card"><p class="muted">The ladder for ${esc(seasonName(key))} hasn't been entered yet.</p></div>${footer()}`;
  }

  const sjb = L.teams.find(t => t.is_sjb);
  const verb = L.status === "final" ? "finished" : "sit";
  const callout = sjb ? `<div class="ladder-pos">
    <span class="lp-rank">${ordinal(sjb.rank)}</span>
    <span class="lp-text">Shake Jelly Balls ${verb} <strong>${ordinal(sjb.rank)}</strong> of ${L.teams.length} — ${sjb.w}-${sjb.l}${sjb.d ? "-" + sjb.d : ""}, ${n(sjb.pts_avg, 2)} points average</span>
  </div>` : "";

  const rows = L.teams.map(t => `<tr class="${t.is_sjb ? "ladder-sjb" : ""}">
    <td class="num" data-v="${t.rank}">${t.rank}</td>
    <td>${t.is_sjb ? `<strong>${esc(t.team)}</strong>` : esc(t.team)}</td>
    ${intCell(t.p)}${cell(t.pts_avg, 2)}${intCell(t.pts)}${cell(t.pct, 2)}
    ${intCell(t.w)}${intCell(t.l)}${intCell(t.d)}${intCell(t.bye)}
    ${intCell(t.f)}${intCell(t.a)}${intCell(t.forf)}${intCell(t.disq)}${intCell(t.adj)}
  </tr>`).join("");

  return `
  ${header}
  ${callout}
  <div class="card"><div class="table-scroll"><table class="stat ladder-table">
    <thead><tr>
      ${th("#")}${th("Team")}${th("P", { title: "Games played" })}${th("PTS AVG", { title: "Points average — competition points ÷ games played (the ranking metric)" })}${th("PTS", { title: "Competition points" })}${th("%", { title: "Percentage — points for ÷ points against × 100" })}
      ${th("W")}${th("L")}${th("D")}${th("BYE")}${th("F", { title: "Points for" })}${th("A", { title: "Points against" })}
      ${th("FORF", { title: "Forfeits" })}${th("DISQ", { title: "Disqualifications" })}${th("ADJ", { title: "Adjustments" })}
    </tr></thead>
    <tbody>${rows}</tbody>
  </table></div>
  <p class="muted" style="font-size:12px;margin-top:10px">${L.ranked_by ? `<strong>Ranked by:</strong> ${esc(L.ranked_by)}. ` : ""}${L.note ? esc(L.note) : ""}</p>
  <p class="muted" style="font-size:12px;margin-top:6px"><strong>PTS AVG</strong> = points ÷ games (the ranking metric); <strong>%</strong> = points for ÷ against × 100; <strong>F/A</strong> = points for / against; <strong>FORF / DISQ / ADJ</strong> = forfeits, disqualifications, adjustments. Click a column to sort.</p>
  </div>
  ${footer()}`;
}

/* ---- awards ------------------------------------------------------------- */
let awardSeason = null;   // awards page has its own season picker, like the ladder

function awPct(r) { return r.avail != null ? Math.round(r.avail * 100) + "%" : "—"; }
function awSigned(v) { return (v > 0 ? "+" : "") + v; }

function awCands(cands, cols) {
  const head = `<thead><tr>${th("Player", { sortable: false })}${cols.map(c =>
    th(c.h, { sortable: false, title: c.title || "" })).join("")}</tr></thead>`;
  const body = cands.map((r, i) => `<tr class="${i === 0 ? "total" : ""}">
    <td>${playerLink(find(r.slug))}</td>
    ${cols.map(c => `<td class="num">${c.fmt ? c.fmt(r) : (r[c.key] == null ? "—" : r[c.key])}</td>`).join("")}
  </tr>`).join("");
  return `<div class="table-scroll"><table class="stat">${head}<tbody>${body}</tbody></table></div>`;
}

const SHARE_COL = { h: "Share", fmt: r => (r.share == null ? "—" : r.share + "%"), title: "This candidate's score as a share of the whole race" };
function awCard(title, sub, award, live, headline, cols) {
  if (!award || !award.winner) return "";
  const w = award.winner;
  const share = w.share != null ? ` <span class="aw-share">${w.share}% share</span>` : "";
  return `<div class="card award">
    <div class="award-head"><h2>${title}</h2><span class="award-sub">${sub}</span></div>
    <div class="award-winner">
      <span class="aw-tag${live ? " live" : ""}">${live ? "Leading" : "Winner"}</span>
      <span class="aw-name">${playerLink(find(w.slug))}</span>
      <span class="aw-val">${headline(w)}${share}</span>
    </div>
    ${awCands(award.candidates, cols)}
  </div>`;
}

function viewAwards() {
  const A = DATA.awards;
  if (!A || !A.order || !A.order.length)
    return `<div class="page-head"><h1>Awards</h1></div><div class="card"><p class="muted">No awards yet — they appear once games are logged.</p></div>${footer()}`;
  if (awardSeason === null || !A.seasons[awardSeason]) awardSeason = A.order[A.order.length - 1];
  const S = A.seasons[awardSeason];
  const aw = S.awards, live = !S.is_final;
  const sel = `<div class="season-pick">Season <select class="award-season-select">${A.order.map(k =>
    `<option value="${k}"${k === awardSeason ? " selected" : ""}>${esc(A.seasons[k].label)}</option>`).join("")}</select></div>`;
  const header = `<div class="page-head"><div class="head-row"><h1>Awards</h1>${sel}</div>
    <div class="sub">${esc(S.label)} · ${live ? "race as it stands" : "final"} · regular season only · computed, not voted</div></div>
    <div class="banner"><strong>Share %</strong> is a Basketball-Reference-style award share: each candidate's score as a percentage of the whole field's total for that award.</div>`;

  const mvp = awCard("Most Valuable Player", "value per team game", aw.mvp, live,
    w => w.mvp, [
      { h: "Rating", key: "mvp", title: "Game Score per team game — rewards being both excellent and available" },
      SHARE_COL,
      { h: "GmSc", key: "gmsc_avg" }, { h: "Avail", fmt: awPct, title: "Share of the team's tracked games played" },
      { h: "PTS", key: "pts" }, { h: "TS%", key: "ts" }]);

  const mipArrow = (a, b) => `${a}&nbsp;→&nbsp;${b}`;
  const mip = awCard("Most Improved", "biggest all-round jump in Game Score vs last season", aw.mip, live,
    w => awSigned(w.mip_score), [
      { h: "Score", fmt: r => awSigned(r.mip_score), title: "Change in Game Score per game — one number that weighs scoring, shooting efficiency, rebounds, assists, steals, blocks and turnovers, so a jump in any facet counts. Level candidates break on change in games-played share, so playing more never wins on its own" },
      SHARE_COL,
      { h: "GmSc", fmt: r => mipArrow(r.prev_gmsc, r.gmsc_avg), title: "Game Score per game: last season → this season" },
      { h: "PPG", fmt: r => mipArrow(r.prev_ppg, r.pts), title: "Points per game: last season → this season" }]);

  const dpoy = awCard("Defensive Player", "steals + blocks per game", aw.dpoy, live,
    w => w.def, [{ h: "STL+BLK", key: "def" }, SHARE_COL, { h: "STL", key: "stl" }, { h: "BLK", key: "blk" }, { h: "GmSc", key: "gmsc_avg" }]);

  const clutch = awCard("Most Clutch", "points in the last 5 min, margin ≤ 5", aw.clutch, live,
    w => w.clutch + " pts", [{ h: "Clutch", key: "clutch", title: "Points scored in the last 5:00 of the final half with the score within 5" }, SHARE_COL, { h: "PTS", key: "pts" }, { h: "GmSc", key: "gmsc_avg" }]);

  const ironman = awCard("Durability", "most minutes played", aw.ironman, live,
    w => w.min_total + " min", [{ h: "Min", key: "min_total" }, SHARE_COL, { h: "Games", key: "g" }, { h: "MPG", key: "mpg" }]);

  const reliable = awCard("Mr. Reliable", "steadiest all-round — lowest game-to-game swing", aw.reliable, live,
    w => w.rel_swing + "% swing", [
      { h: "Swing", fmt: r => r.rel_swing + "%", title: "Game-to-game swing in points, rebounds and assists, each weighed against its typical size, then averaged — lower is steadier" },
      SHARE_COL,
      { h: "pts / reb / ast", fmt: r => `±${r.sw_pts} / ±${r.sw_reb} / ±${r.sw_ast}`, title: "Game-to-game swing (standard deviation) in each category" },
      { h: "G", fmt: r => r.rel_g, title: "Games used — every regular-season game with points, rebounds and assists recorded, including box-only games" }]);

  const t = aw.titles || {};
  const titleRow = (lab, w, unit) => w
    ? `<div class="aw-title"><span class="aw-title-lbl">${lab}</span><span class="aw-title-nm">${playerLink(find(w.slug))}</span><span class="aw-title-val">${w[unit.key] == null ? "—" : w[unit.key]}${unit.suf || ""}</span></div>` : "";
  const titles = `<div class="card">
    <div class="award-head"><h2>Statistical titles</h2><span class="award-sub">${esc(S.label)} leaders</span></div>
    <div class="aw-titles">
      ${titleRow("Scoring", t.scoring, { key: "pts", suf: " pts" })}
      ${titleRow("Rebounding", t.rebounding, { key: "reb", suf: " reb" })}
      ${titleRow("Playmaking", t.playmaking, { key: "ast", suf: " ast" })}
      ${titleRow("Efficiency", t.efficiency, { key: "ts", suf: "% TS" })}
    </div></div>`;

  // all-time / career (not season-scoped)
  const AT = A.all_time || {};
  const miniList = (rows, fmt) => rows && rows.length
    ? rows.map((r, i) => `<div class="leader-row"><span class="leader-rank">${i + 1}</span><span class="nm">${playerLink(find(r.slug))}</span><span class="val">${fmt(r)}</span></div>`).join("")
    : `<p class="muted">—</p>`;
  const cl = AT.career_leaders || {};
  const careerCards = `<div class="grid cols-3">
    <div class="card"><h2>Career MVP rating</h2>${miniList(cl.mvp, r => r.mvp)}<p class="muted" style="font-size:11px;margin-top:8px">Game Score per team game, all seasons.</p></div>
    <div class="card"><h2>Career clutch points</h2>${miniList(cl.clutch, r => r.clutch)}</div>
    <div class="card"><h2>Career defence</h2>${miniList(cl.defense, r => r.stlblk)}<p class="muted" style="font-size:11px;margin-top:8px">Total steals + blocks.</p></div>
  </div>`;

  const wins = AT.winners || [];
  const honoursTable = wins.length ? `<div class="card"><h2>Roll of honours</h2>
    <div class="table-scroll"><table class="stat">
      <thead><tr>${["Season", "MVP", "Most Improved", "Defensive", "Clutch", "Durability", "Reliable"].map(h => th(h, { sortable: false })).join("")}</tr></thead>
      <tbody>${wins.map(r => `<tr>
        <td>${esc(r.label)}</td>
        ${["mvp", "mip", "dpoy", "clutch", "ironman", "reliable"].map(k => `<td>${r[k] ? playerLink(find(r[k].slug)) : "—"}</td>`).join("")}
      </tr>`).join("")}</tbody>
    </table></div>
    <p class="muted" style="font-size:12px;margin-top:8px">Only concluded seasons are crowned; the current season is a live race above.</p></div>` : "";

  // secondary award cards, two per row
  const secondary = [mip, dpoy, clutch, ironman, reliable].filter(Boolean);
  let secHtml = "";
  for (let i = 0; i < secondary.length; i += 2)
    secHtml += `<div class="grid cols-2">${secondary[i]}${secondary[i + 1] || ""}</div>`;

  return `${header}
    ${mvp}
    ${secHtml}
    ${titles}
    <h2 class="aw-section">All-time</h2>
    ${honoursTable}
    ${careerCards}
    ${footer()}`;
}

/* ---- frivolities -------------------------------------------------------- */
function frivLabel(it) {
  const parts = [];
  if (it.players) parts.push(it.players.map(p => playerLink(find(p.slug))).join(`<span class="friv-join">${esc(it.join || " + ")}</span>`));
  if (it.game) parts.push(gameLink({ id: it.game.id, date_disp: it.game.label }, it.game.label));
  if (!parts.length && it.label) parts.push(esc(it.label));
  return parts.join(`<span class="friv-join">·</span>`);
}
function viewFrivolities() {
  const F = DATA.frivolities || [];
  if (!F.length)
    return `<div class="page-head"><h1>Frivolities</h1></div><div class="card"><p class="muted">Nothing here yet.</p></div>${footer()}`;
  const order = [], bySec = {};
  for (const c of F) { if (!bySec[c.section]) { bySec[c.section] = []; order.push(c.section); } bySec[c.section].push(c); }
  const cardHtml = c => `<div class="card friv">
    <div class="award-head"><h2>${esc(c.title)}</h2>${c.note ? `<span class="award-sub">${esc(c.note)}</span>` : ""}</div>
    <ul class="friv-list">${c.items.map(it => `<li class="friv-row">
      <span class="friv-main">${frivLabel(it)}${it.sub ? ` <span class="friv-sub">${esc(it.sub)}</span>` : ""}</span>
      <span class="friv-val">${esc(it.val)}</span>
    </li>`).join("")}</ul>
  </div>`;
  const body = order.map(sec => `<h2 class="aw-section">${esc(sec)}</h2>
    <div class="grid cols-2">${bySec[sec].map(cardHtml).join("")}</div>`).join("");
  return `<div class="page-head"><h1>Frivolities</h1></div>
    ${body}${footer()}`;
}

/* ---- router ------------------------------------------------------------- */
function route() {
  const hash = location.hash.replace(/^#\/?/, "");
  const parts = hash.split("/");
  const seg = parts[0], arg = parts[1];
  let html;
  switch (seg) {
    case "": html = viewHome(); break;
    case "schedule": html = viewSchedule(); break;
    case "game": html = viewGame(decodeURIComponent(arg || "")); break;
    case "players": html = viewPlayers(); break;
    case "player": html = viewPlayer(decodeURIComponent(arg || "")); break;
    case "leaders": html = viewLeaders(); break;
    case "team": html = viewTeam(); break;
    case "ladder": html = viewLadder(); break;
    case "awards": html = viewAwards(); break;
    case "frivolities": html = viewFrivolities(); break;
    case "glossary": html = viewGlossary(); break;
    default: html = viewHome();
  }
  view.innerHTML = html;
  enableSorting(view);
  enableChartHover(view);
  // ladder page has its own season picker
  view.querySelectorAll(".ladder-season-select").forEach(sel => sel.addEventListener("change", e => {
    ladderSeason = e.target.value;
    route();
  }));
  // awards page season picker
  view.querySelectorAll(".award-season-select").forEach(sel => sel.addEventListener("change", e => {
    awardSeason = e.target.value;
    route();
  }));
  // season switcher (Home / Team / Leaders) — re-render the current view on change
  view.querySelectorAll(".season-select").forEach(sel => sel.addEventListener("change", e => {
    selSeason = e.target.value;
    route();
  }));
  // play-by-play "scoring plays only" filter (game page) — toggle a class, no re-route
  view.querySelectorAll(".pbp-scoring-only").forEach(cb => cb.addEventListener("change", e => {
    const feed = e.target.closest(".card").querySelector(".pbp-feed");
    if (feed) feed.classList.toggle("scoring-only", e.target.checked);
  }));
  // nav active state
  document.querySelectorAll("#nav a").forEach(a => {
    const target = a.getAttribute("href").replace(/^#\/?/, "");
    a.classList.toggle("active", target === seg || (target === "" && seg === ""));
  });
  window.scrollTo(0, 0);
}

async function boot() {
  try {
    const res = await fetch("data.json", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    DATA = await res.json();
    selSeason = DATA.current_season_key || "all";
  } catch (e) {
    view.innerHTML = `<div class="card"><h2>Couldn't load the season data</h2>
      <p class="muted">Run <code>python server/build_site.py</code> to generate <code>data.json</code>, then reload.</p></div>`;
    return;
  }
  window.addEventListener("hashchange", route);
  route();
}

// mobile nav: toggle the menu, and collapse it after a link is tapped
(function navMenu() {
  const btn = document.getElementById("navToggle");
  const nav = document.getElementById("nav");
  if (!btn || !nav) return;
  const close = () => { nav.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); };
  btn.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  });
  nav.addEventListener("click", e => { if (e.target.closest("a")) close(); });
})();

boot();
