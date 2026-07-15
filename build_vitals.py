#!/usr/bin/env python3
"""
MCC Vitals Dashboard renderer.

Data source: MCC Data Warehouse (see CLAUDE.md DATA ARCHITECTURE). Reads the
`observations`, `metric_registry` and `config` tabs through warehouse_reader --
the same single source of truth build_connections.py and build_dashboard.py use.
Writes:
  MCC/data/vitals.json   -- structured data (years, metrics, values, pcts, through-week)
  MCC/vitals.html        -- the leadership dashboard, numbers baked in

Each metric maps to one warehouse metric_id (see METRICS below). Prior-year
(2022-2025) values are the annual Dec-31 observations; the current year is the
year-to-date figure. The dashboard's second column (percent / YoY growth /
per-person $) is NOT stored in the warehouse -- it is COMPUTED here using the
exact denominators the legacy MCC VITALS.xlsx used (recovered from that sheet's
formulas); see `denom` on each metric.

Monthly refresh: the warehouse feeds refresh automatically (PCO cron on the 2nd,
QBO cron on the 16th, weekly attendance Apps Script). Just re-run:
    python3 build_vitals.py
"""
import json, os, datetime
import warehouse_reader as wh

BASE = os.path.dirname(os.path.abspath(__file__))
YEARS = [2022, 2023, 2024, 2025, 2026]
CUR_YEAR = YEARS[-1]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]

# Metric definitions. Warehouse mapping fields:
#   mid    -- warehouse metric_id for the displayed value
#   agg    -- how the annual value is derived from observations:
#               "annual"      = single Dec-31 / current-year row (last wins;
#                               used by metrics stored as one row per year)
#               "yearly_mean" = mean of the year's monthly rows (attendance &
#                               adults are stored as monthly averages, so the
#                               annual figure must be averaged, never read off
#                               the Dec-31 row, which is only December)
#               "ytd_sum"     = sum of each year's monthly rows (count metrics)
#   denom  -- how the 2nd column is computed (mirrors the old xlsx formulas):
#               "growth"     = YoY % change of this metric
#               "attendance" = value / avg attendance      (row 2)
#               "adults"     = value / avg adults           (row 3)
#               "unique"     = value / unique donors        (row 18)
#               "visitors"   = value / Sunday visitors      (row 8)
#               "dollar"     = per-person/week $ (stored give_per_person_week);
#                              `totals_mid` supplies the annual giving total
METRICS = [
    # Evangelism
    dict(group="evangelism",  name="Avg. attendance (in-person)", goal="Min. 5% growth",
         type="growth", goalMin=5, isAvg=True,  mid="att_avg_weekly",  agg="yearly_mean", denom="growth"),
    dict(group="evangelism",  name="Avg. adults (in-person)",     goal="Min. 5% growth",
         type="growth", goalMin=5, isAvg=True,  mid="att_adults_avg",  agg="yearly_mean", denom="growth"),
    dict(group="evangelism",  name="Avg. students (in-person)",   goal="10%–15% of attendance",
         type="range",  goalMin=10, goalMax=15, isAvg=True,  mid="att_students_avg", agg="annual", denom="adults"),
    dict(group="evangelism",  name="Avg. kids (in-person)",       goal="15%–25% of attendance",
         type="range",  goalMin=15, goalMax=25, isAvg=True,  mid="att_kids_avg",   agg="annual", denom="attendance"),
    dict(group="evangelism",  name="Avg. online attendance",      goal="25%–30% of attendance",
         type="range",  goalMin=25, goalMax=30, isAvg=True,  mid="att_online_avg", agg="annual", denom="attendance"),
    dict(group="evangelism",  name="Baptisms / POF",              goal="10% of attendance",
         type="min",    goalMin=10, isAvg=False, mid="baptisms",       agg="annual", denom="attendance"),
    dict(group="evangelism",  name="Sunday visitors",             goal="100% of attendance",
         type="min",    goalMin=100, isAvg=False, mid="guests_new",    agg="ytd_sum", denom="attendance"),
    dict(group="evangelism",  name="Connect breakfast",           goal="10% of attendance",
         type="min",    goalMin=10, isAvg=False, mid="connect_breakfast", agg="ytd_sum", denom="attendance"),
    # Discipleship
    dict(group="discipleship", name="Adults in circles",      goal="70% of adults",
         type="min",   goalMin=70, isAvg=True,  mid="adults_in_circles_avg", agg="annual", denom="adults"),
    dict(group="discipleship", name="Regular serving",        goal="50% of attendance",
         type="min",   goalMin=50, isAvg=True,  mid="serving_regular_avg", agg="annual", denom="adults"),
    dict(group="discipleship", name="Unique donors",          goal="40%–60% of attendance",
         type="range", goalMin=40, goalMax=60, isAvg=True,  mid="donors_unique", agg="annual", denom="attendance"),
    dict(group="discipleship", name="New donors",             goal="5%–10% of unique donors",
         type="range", goalMin=5, goalMax=10, isAvg=False, mid="donors_new",   agg="annual", denom="unique"),
    dict(group="discipleship", name="Giving / person / week",  goal="$25–$35 per person/week",
         type="dollar", goalMin=25, goalMax=35, isAvg=False, mid="give_per_person_week",
         totals_mid="giving_total", agg="annual", denom="dollar"),
    dict(group="discipleship", name="Starting Point",         goal="10% of guests",
         type="min",   goalMin=10, isAvg=False, mid="starting_point", agg="annual", denom="visitors"),
]

def _yearly_mean(mid, y):
    """True annual average = mean of that year's monthly observations. For
    att_avg_weekly / att_adults_avg the warehouse stores month-end monthly
    averages (the Dec-31 row is DECEMBER's average, not the year's), so the
    annual figure must be averaged across the year, never read off one row.
    Years stored as a single annual row (e.g. adults 2022-2024) mean-of-one =
    that value. Returns None if the year has no data."""
    vals = [v for v in wh.monthly(mid, y).values() if v is not None]
    return (sum(vals) / len(vals)) if vals else None

def _same_period_growth(mid, y):
    """YoY growth for a partial (current) year, compared apples-to-apples:
    mean of the months recorded this year vs the SAME months last year."""
    cur, prev = wh.monthly(mid, y), wh.monthly(mid, y - 1)
    common = [m for m in cur if cur[m] is not None and prev.get(m) is not None]
    if not common:
        return None
    cm = sum(cur[m] for m in common) / len(common)
    pm = sum(prev[m] for m in common) / len(common)
    return round((cm / pm - 1) * 100) if pm else None

def _val_series(m):
    """Return {year: raw value} for YEARS, per the metric's `agg` rule."""
    mid, agg = m["mid"], m["agg"]
    if agg == "ytd_sum":                        # count metrics: sum the year's months
        out = {}
        for y in YEARS:
            vals = [v for v in wh.monthly(mid, y).values() if v is not None]
            out[y] = sum(vals) if vals else None
        return out
    if agg == "yearly_mean":                    # attendance/adults: average the year
        return {y: _yearly_mean(mid, y) for y in YEARS}
    ann = wh.annual(mid)                        # {year: Dec-31 / current-year row}
    return {y: ann.get(y) for y in YEARS}

def _round(v):
    return None if v is None else round(v)

def _pct(n, d):
    return None if (n is None or not d) else round(n / d * 100)

def extract():
    # Raw (unrounded) value series per metric, keyed by display name.
    raw = {m["name"]: _val_series(m) for m in METRICS}
    ATT  = raw["Avg. attendance (in-person)"]   # denominators use raw values,
    ADU  = raw["Avg. adults (in-person)"]       # exactly as the old xlsx did
    UNIQ = raw["Unique donors"]
    VIS  = raw["Sunday visitors"]
    denom_series = {"attendance": ATT, "adults": ADU, "unique": UNIQ, "visitors": VIS}

    # Prior-year anchors for the two growth rows (2022 needs 2021 — averaged).
    growth_prior = {m["name"]: _yearly_mean(m["mid"], YEARS[0] - 1)
                    for m in METRICS if m["denom"] == "growth"}

    out = []
    for m in METRICS:
        vser = raw[m["name"]]
        values = [_round(vser.get(y)) for y in YEARS]
        totals = None
        if m["denom"] == "dollar":
            pcts = None
            tser = wh.annual(m["totals_mid"])
            totals = [_round(tser.get(y)) for y in YEARS]
        elif m["denom"] == "growth":
            # Full years: YoY of annual averages. Current (partial) year:
            # same-period comparison so it's not distorted by the summer dip.
            prev = dict(vser); prev[YEARS[0] - 1] = growth_prior[m["name"]]
            pcts = []
            for y in YEARS:
                if y == CUR_YEAR:
                    pcts.append(_same_period_growth(m["mid"], y))
                else:
                    cv, pv = vser.get(y), prev.get(y - 1)
                    pcts.append(round((cv / pv - 1) * 100) if (cv and pv) else None)
        else:
            dser = denom_series[m["denom"]]
            pcts = [_pct(vser.get(y), dser.get(y)) for y in YEARS]
        rec = dict(name=m["name"], goal=m["goal"], group=m["group"], type=m["type"],
                   goalMin=m["goalMin"], isAvg=m["isAvg"], values=values, pcts=pcts)
        if "goalMax" in m: rec["goalMax"] = m["goalMax"]
        if totals is not None: rec["totals"] = totals
        out.append(rec)

    # Reporting window: last complete month = latest monthly attendance row;
    # through-week = Sundays recorded on/before that month's end.
    att_months = wh.monthly("att_avg_weekly", CUR_YEAR)
    last_month = max(att_months) if att_months else None
    month = MONTH_NAMES[last_month - 1] if last_month else None
    weekly = wh.weekly("att_weekly_total", CUR_YEAR)
    through_week = (sum(1 for d, _ in weekly if int(d[5:7]) <= last_month)
                    if last_month else None) or None

    # Chart data: monthly weekly-attendance average by year (Jan..Dec, None =
    # not yet recorded). Powers the seasonality curve + 12-month rolling avg.
    # Kept to the dashboard's standard window (2022+) so every view is
    # consistent; the rolling average's first full point is therefore Dec 2022.
    att_monthly = {str(y): [_round(wh.monthly("att_avg_weekly", y).get(mo))
                            for mo in range(1, 13)]
                   for y in range(YEARS[0], CUR_YEAR + 1)}
    charts = {
        "att_monthly": att_monthly,
        "cur_year": CUR_YEAR,
        "ytd_month_index": last_month,           # months of the current year in view
        "ytd_label": ("Jan–%s" % month) if month else None,
    }
    return out, through_week, month, charts

def get(metrics, name):
    for m in metrics:
        if m["name"] == name: return m
    return None

def cur(m):  # current-year (2026) value
    return m["values"][-1]
def curpct(m):
    return m["pcts"][-1] if m.get("pcts") else None

def build_insights(metrics):
    att   = get(metrics, "Avg. attendance (in-person)")
    circ  = get(metrics, "Adults in circles")
    serv  = get(metrics, "Regular serving")
    stu   = get(metrics, "Avg. students (in-person)")
    kid   = get(metrics, "Avg. kids (in-person)")
    don   = get(metrics, "Unique donors")
    bullets = []
    # 1. Attendance
    prev_max = max(v for v in att["values"][:-1] if v is not None)
    hi = cur(att) >= prev_max
    g = curpct(att)
    lead = "the highest on record" if hi else "steady"
    # Phrase the YoY move by sign, and describe it relative to the 5% goal.
    move = (f"up {g}% over 2025" if g > 0
            else "flat versus 2025" if g == 0
            else f"down {abs(g)}% from 2025")
    tail = ("comfortably above the 5% growth goal." if g >= 5
            else "positive but under the 5% growth goal." if g > 0
            else "essentially flat against the 5% growth goal." if g == 0
            else "a decline against the 5% growth goal.")
    bullets.append(("green" if g >= 5 else "amber",
        f"Weekend attendance is {lead} — <strong>{cur(att):,} average</strong> through the "
        f"reporting window, {move}. Growth is {tail}"))
    # 2. Circles
    bullets.append(("green" if curpct(circ) >= circ["goalMin"] else "green",
        f"Adults in circles continues to climb — <strong>{cur(circ):,} adults ({curpct(circ)}%)</strong> "
        f"are in a circle, the strongest on record. The 70% goal is within reach."))
    # 3. Watch areas (below-goal averages)
    watch = []
    if curpct(att) < 5:  watch.append(f"attendance growth ({curpct(att)}%)")
    if curpct(serv) < serv["goalMin"]: watch.append(f"regular serving ({curpct(serv)}%)")
    if curpct(don) < don["goalMin"]:   watch.append(f"unique donors ({curpct(don)}%)")
    if watch:
        joined = ", ".join(watch[:-1]) + (f", and {watch[-1]}" if len(watch) > 1 else watch[0])
        if len(watch) == 1: joined = watch[0]
        bullets.append(("amber",
            f"The key watch areas are {joined} — each sits below its 2026 goal and is worth "
            f"deliberate leadership attention this half of the year."))
    # 4. Students (worst trend)
    s24, s26 = stu["values"][2], stu["values"][-1]
    p24, p26 = stu["pcts"][2], stu["pcts"][-1]
    bullets.append(("red",
        f"Student ministry is the most concerning trend — average students has fallen from "
        f"<strong>{s24} in 2024 to {s26} in 2026</strong> ({p24}% → {p26}% of attendance), "
        f"consistently under the 10–15% goal and still declining."))
    # 5. Kids
    kv, kp = cur(kid), curpct(kid)
    kpeak = max(v for v in kid["values"] if v is not None)
    in_goal = kp is not None and kid["goalMin"] <= kp <= kid["goalMax"]
    low_edge = in_goal and kp <= kid["goalMin"] + 3
    kcolor = "green" if in_goal else "amber"
    edge_note = (" — near the lower edge of the 15–25% goal" if low_edge
                 else " — comfortably inside the 15–25% goal" if in_goal
                 else " — outside the 15–25% goal")
    bullets.append((kcolor,
        f"Kids attendance is holding steady{edge_note}. <strong>{kv:,} average "
        f"({kp}% of attendance)</strong> in 2026, after peaking at {kpeak}; the trend has "
        f"leveled off, giving children's ministry a stable base to build on."))
    # 6. Donors
    d22 = don["pcts"][0]
    bullets.append(("amber",
        f"Unique donors ({cur(don):,}, {curpct(don)}%) remain well below the 40–60% goal and have "
        f"contracted from {d22}% of attendance in 2022. Track this alongside the finance dashboard "
        f"as a long-term giving-health signal."))
    # 7. Methodology note
    bullets.append(("blue",
        "Count-based metrics (visitors, baptisms, Connect Breakfast, giving) are year-to-date and "
        "should not be compared directly to prior full-year totals. Averages (attendance, serving, "
        "circles) are fully comparable."))
    return bullets

# ── HTML template ──────────────────────────────────────────────────────────
TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>MCC Vitals Dashboard</title>
<link rel="icon" type="image/png" href="favicon.png">
<link rel="apple-touch-icon" href="favicon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap" rel="stylesheet">
<style>
  :root {
    --slate: #343A44; --bg: #F2F2F2; --card: #ffffff; --ink: #23272e; --muted: #6b7280;
    --line: #e3e5ea; --red: #DC2626; --green: #2F8F5B; --amber: #C8842A; --chart: #4C5564;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Lato', system-ui, -apple-system, Arial, sans-serif; background: var(--bg); color: var(--ink); font-size: 15px; line-height: 1.6; }
  .mcc-header { position: relative; overflow: hidden; background: var(--slate); color: #fff; }
  .mcc-header-inner { position: relative; max-width: 1180px; margin: 0 auto; padding: 26px 30px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px; }
  .mcc-header::before { content: ""; position: absolute; inset: 0; background: url('https://storage1.snappages.site/VCFHFT/assets/images/21064405_1024x1024_2500.png'); background-size: 620px; opacity: .065; pointer-events: none; }
  .mcc-header .brand { display: flex; align-items: center; gap: 20px; position: relative; }
  .mcc-header .logo { height: 42px; width: auto; display: block; }
  .mcc-header .back { color: #aeb6c2; font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; text-decoration: none; display: inline-block; margin-bottom: 5px; }
  .mcc-header .back:hover { color: #fff; }
  .mcc-header h1 { font-size: 27px; font-weight: 900; text-transform: uppercase; letter-spacing: -.02em; line-height: 1; }
  .mcc-header .sub { font-size: 11.5px; font-weight: 400; letter-spacing: .05em; text-transform: uppercase; opacity: .72; margin-top: 6px; }
  .mcc-header .right { position: relative; font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; opacity: .8; text-align: right; line-height: 1.7; }
  .page { max-width: 1180px; margin: 0 auto; padding: 28px 30px 60px; }
  .section-label { font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin-bottom: 12px; margin-top: 32px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 4px; }
  .card { background: var(--card); border-radius: 10px; padding: 18px 20px; border: 1px solid var(--line); box-shadow: 0 1px 4px rgba(20,30,60,.05); }
  .card .label { font-size: 11px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 6px; }
  .card .value { font-size: 26px; font-weight: 900; color: var(--slate); letter-spacing: -0.5px; }
  .card .sub   { font-size: 12px; margin-top: 4px; }
  .card .sub.green  { color: var(--green); } .card .sub.yellow { color: var(--amber); } .card .sub.red { color: var(--red); }
  .card.top-green  { border-top: 4px solid var(--green); } .card.top-yellow { border-top: 4px solid var(--amber); }
  .card.top-red    { border-top: 4px solid var(--red); }  .card.top-blue   { border-top: 4px solid var(--slate); }
  .insights { background: #F4F5F7; border: 1px solid var(--line); border-radius: 10px; padding: 20px 24px; margin-top: 6px; }
  .insights h2 { font-size: 13px; font-weight: 900; text-transform: uppercase; letter-spacing: .08em; color: var(--slate); margin-bottom: 12px; }
  .insights ul { list-style: none; }
  .insights ul li { padding: 8px 0; border-bottom: 1px solid var(--line); font-size: 13px; color: var(--ink); display: flex; align-items: flex-start; gap: 10px; line-height: 1.55; }
  .insights ul li:last-child { border-bottom: none; }
  .dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
  .dot-green { background: var(--green); } .dot-red { background: var(--red); } .dot-amber { background: var(--amber); } .dot-blue { background: var(--slate); }
  .funnel-wrap { display: flex; align-items: stretch; gap: 0; }
  .funnel-step { flex: 1; display: flex; flex-direction: column; align-items: center; text-align: center; position: relative; }
  .funnel-step:not(:last-child)::after { content: '→'; position: absolute; right: -12px; top: 50%; transform: translateY(-50%); font-size: 20px; color: var(--line); z-index: 1; }
  .funnel-box { width: 100%; background: #F4F5F7; border: 1px solid var(--line); border-radius: 10px; padding: 16px 10px; }
  .funnel-step:nth-child(2) .funnel-box { background: #F0FBF5; border-color: #B6DCCA; }
  .funnel-step:nth-child(3) .funnel-box { background: #FDF5EC; border-color: #E8C99A; }
  .funnel-step:nth-child(4) .funnel-box { background: #F4F5F7; border-color: var(--line); }
  .funnel-num { font-size: 26px; font-weight: 900; color: var(--slate); letter-spacing: -0.5px; }
  .funnel-label { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: var(--ink); margin-top: 4px; }
  .funnel-conv { font-size: 11px; color: var(--muted); margin-top: 6px; line-height: 1.4; }
  .funnel-conv strong { color: var(--ink); }
  @media (max-width: 600px) { .funnel-wrap { flex-direction: column; gap: 8px; }
    .funnel-step:not(:last-child)::after { content: '↓'; right: auto; top: auto; bottom: -16px; left: 50%; transform: translateX(-50%); } }
  .chart-card { background: var(--card); border-radius: 10px; padding: 22px 22px 18px; border: 1px solid var(--line); margin-bottom: 14px; box-shadow: 0 1px 4px rgba(20,30,60,.05); }
  .chart-card h2 { font-size: 15px; font-weight: 900; text-transform: uppercase; letter-spacing: -.01em; color: var(--slate); margin-bottom: 4px; }
  .chart-card .chart-sub { font-size: 13px; color: var(--muted); margin-bottom: 16px; }
  .chart-wrap { position: relative; width: 100%; }
  .legend { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 14px; }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); font-weight: 700; }
  .legend-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
  .metrics-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .metrics-table th { background: #F9FAFB; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; font-size: 11px; color: var(--muted); padding: 9px 12px; text-align: right; border-bottom: 2px solid var(--line); white-space: nowrap; }
  .metrics-table th:first-child { text-align: left; width: 200px; }
  .metrics-table th.goal-col { text-align: left; font-weight: 500; }
  .metrics-table td { padding: 9px 12px; border-bottom: 1px solid #F3F4F6; text-align: right; color: var(--ink); vertical-align: middle; }
  .metrics-table td:first-child { text-align: left; font-weight: 700; color: var(--slate); }
  .metrics-table td.goal-cell { text-align: left; font-size: 11px; color: #9CA3AF; white-space: nowrap; }
  .metrics-table tr:hover td { background: #FAFAFA; }
  .cur-val { font-weight: 900; color: var(--slate); }
  .status { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; padding: 3px 8px; border-radius: 12px; white-space: nowrap; }
  .status-green { background: #DCFCE7; color: #15803D; } .status-yellow { background: #FEF9C3; color: #A16207; }
  .status-red { background: #FEE2E2; color: var(--red); } .status-gray { background: #F3F4F6; color: var(--muted); }
  .section-divider { margin: 32px 0 20px; padding-bottom: 10px; border-bottom: 2px solid var(--slate); display: flex; align-items: center; gap: 10px; }
  .section-divider h2 { font-size: 15px; font-weight: 900; text-transform: uppercase; letter-spacing: -.01em; color: var(--slate); }
  .section-divider .badge { font-size: 11px; font-weight: 700; color: var(--muted); background: #F0F2F5; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: .06em; }
  .ytd-note { background: #FEF9C3; border: 1px solid #FDE68A; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #92400E; margin-bottom: 14px; }
  .mcc-footer { color: var(--muted); font-size: 11.5px; margin-top: 44px; line-height: 1.8; text-align: center; }
</style>
</head>
<body>
<script>
// ══════════════════════════════════════════════════════════════
//  DATA — generated by build_vitals.py from the MCC Data Warehouse. Do not hand-edit.
// ══════════════════════════════════════════════════════════════
const VITALS = __DATA__;
const LAST_UPDATED = "__LAST_UPDATED__";
const YEARS = VITALS.years;
const evangelism   = VITALS.metrics.filter(m => m.group === "evangelism");
const discipleship = VITALS.metrics.filter(m => m.group === "discipleship");
</script>

<header class="mcc-header">
  <div class="mcc-header-inner">
  <div class="brand">
    <img class="logo" src="https://storage1.snappages.site/VCFHFT/assets/images/22645050_962x358_500.png" alt="Maple City Chapel">
    <div>
      <a class="back" href="index.html">← Leadership Portal</a>
      <h1>MCC Vitals</h1>
      <div class="sub">Attendance, Engagement &amp; Discipleship Indicators</div>
    </div>
  </div>
  <div class="right">Data through<br>__DATA_THROUGH__</div>
  </div>
</header>

<div class="page">
  <div class="section-label">2026 at a glance</div>
  <div class="cards" id="snapshot-cards"></div>

  <div class="section-label">Key takeaways</div>
  <div class="insights">
    <h2>What this data is telling us</h2>
    <ul id="insights-list">__INSIGHTS__</ul>
  </div>

  <div class="section-label">Attendance trends</div>
  <div class="chart-card">
    <h2>Average weekly attendance — 2022 to 2026</h2>
    <p class="chart-sub">Full-year averages for 2022&ndash;2025; 2026 is the year-to-date average through __THROUGH_SHORT__. The growth % for 2026 compares __YTD_LABEL__ 2026 with the same months of 2025 (same-period, apples-to-apples) — not against the full prior year.</p>
    <div class="legend">
      <span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>In-person (total)</span>
      <span class="legend-item"><span class="legend-dot" style="background:#8899AA;"></span>Online</span>
    </div>
    <div class="chart-wrap" style="height:220px;"><canvas id="attendanceChart" role="img" aria-label="Weekly attendance trend 2022 to 2026"></canvas></div>
  </div>

  <div class="chart-card">
    <h2>Seasonality — monthly attendance by year</h2>
    <p class="chart-sub">Average weekly attendance in each month, one line per year. The overlay reveals the seasonal shape (spring peak, summer dip, fall recovery) and shows at a glance whether 2026 is tracking above or below recent years.</p>
    <div class="chart-wrap" style="height:270px;"><canvas id="seasonalityChart" role="img" aria-label="Monthly attendance by year"></canvas></div>
  </div>

  <div class="chart-card">
    <h2>Underlying trajectory — 12-month rolling average</h2>
    <p class="chart-sub">Each point is the trailing 12-month average weekly attendance. Averaging a full year at every step cancels out seasonality and one-off weeks, leaving the true direction of travel.</p>
    <div class="chart-wrap" style="height:220px;"><canvas id="rollingChart" role="img" aria-label="Trailing 12-month rolling average attendance"></canvas></div>
  </div>

  <div class="chart-card">
    <h2>In-person composition by group</h2>
    <p class="chart-sub">Average weekly adults, students, kids, and online — each group's contribution to total reach over time, so you can see where attendance is coming from.</p>
    <div class="legend">
      <span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>Adults</span>
      <span class="legend-item"><span class="legend-dot" style="background:#2F8F5B;"></span>Kids</span>
      <span class="legend-item"><span class="legend-dot" style="background:#DC2626;"></span>Students</span>
      <span class="legend-item"><span class="legend-dot" style="background:#8899AA;"></span>Online</span>
    </div>
    <div class="chart-wrap" style="height:220px;"><canvas id="breakdownChart" role="img" aria-label="In-person composition adults students kids online 2022 to 2026"></canvas></div>
  </div>

  <div class="section-divider"><h2>Evangelism vitals</h2><span class="badge">Outreach &amp; growth</span></div>
  <div class="ytd-note">⚠️ <strong>Note:</strong> Metrics marked † are cumulative counts (not averages). Their 2026 figures reflect year-to-date through __THROUGH_SHORT__ and should not be compared directly to prior full-year totals.</div>
  <div class="chart-card" style="padding: 0; overflow: hidden;"><table class="metrics-table" id="evangelismTable"></table></div>

  <div class="section-divider" style="margin-top: 36px;"><h2>Discipleship vitals</h2><span class="badge">Engagement &amp; generosity</span></div>
  <div class="ytd-note">⚠️ <strong>Note:</strong> New donors, giving, and Starting Point figures (†) are YTD through __THROUGH_SHORT__. Per-person weekly giving reflects the YTD average and rises as the year progresses.</div>
  <div class="chart-card" style="padding: 0; overflow: hidden;"><table class="metrics-table" id="discipleshipTable"></table></div>

  <div class="section-label" style="margin-top: 28px;">Discipleship trends</div>
  <div class="chart-card">
    <h2>Adults in circles and regular serving — % of adults/attendance</h2>
    <p class="chart-sub">Tracking progress toward the 70% circles goal and 50% serving goal.</p>
    <div class="legend">
      <span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>Adults in circles %</span>
      <span class="legend-item"><span class="legend-dot" style="background:#2F8F5B;"></span>Regular serving %</span>
      <span class="legend-item" style="margin-left:8px; border-left: 1px solid var(--line); padding-left: 12px;"><span style="width:20px; height:2px; background:#343A44; display:inline-block; margin-right:4px; border-top: 2px dashed #343A44; vertical-align: middle;"></span>Circles goal (70%)</span>
      <span class="legend-item"><span style="width:20px; height:2px; background:#2F8F5B; display:inline-block; margin-right:4px; border-top: 2px dashed #2F8F5B; vertical-align: middle;"></span>Serving goal (50%)</span>
    </div>
    <div class="chart-wrap" style="height:220px;"><canvas id="discipleshipChart" role="img" aria-label="Adults in circles and regular serving percentage trend"></canvas></div>
  </div>

  <div class="section-label" style="margin-top: 28px;">Next steps funnel — 2026 YTD</div>
  <div class="chart-card">
    <h2>How people move from visitor to engaged disciple</h2>
    <p class="chart-sub">Each stage shows the YTD count for 2026 and the conversion rate from the previous step. Count metrics are through __THROUGH_SHORT__.</p>
    <div class="funnel-wrap" id="funnel-wrap"></div>
    <p style="font-size:11px; color:var(--muted); margin-top:16px;">† YTD counts through __THROUGH_SHORT__. Adults in circles is a point-in-time average, not a cumulative count — conversion shown vs. Starting Point completers is directional only.</p>
  </div>

  <div class="mcc-footer">
    <p>Maple City Chapel &nbsp;·&nbsp; MCC Vitals Dashboard &nbsp;·&nbsp; Data through __DATA_THROUGH_PLAIN__</p>
    <p style="margin-top:2px;">Source: Planning Center / internal tracking. Updated by the Operations team.</p>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const CUR = YEARS.length - 1;   // index of current year (2026)
function statusFor(m) {
  const pct = m.pcts ? m.pcts[CUR] : null, val = m.values[CUR];
  if (val === null || val === undefined) return 'gray';
  if (m.type === 'growth') { if (pct >= m.goalMin) return 'green'; if (pct >= m.goalMin - 2) return 'yellow'; return 'red'; }
  if (m.type === 'range')  { if (pct >= m.goalMin && pct <= m.goalMax) return 'green'; if (pct >= m.goalMin - 4) return 'yellow'; return 'red'; }
  if (m.type === 'min')    { if (pct >= m.goalMin) return 'green'; if (pct >= m.goalMin * 0.85) return 'yellow'; return 'red'; }
  if (m.type === 'dollar') { if (val >= m.goalMin && val <= m.goalMax) return 'green'; if (val >= m.goalMin * 0.7) return 'yellow'; return 'red'; }
  return 'gray';
}
const statusLabel = s => ({green:'On target', yellow:'Near target', red:'Below target', gray:'—'}[s]);
function fmtVal(m, i) { const v = m.values[i]; if (v === null || v === undefined) return '—'; if (m.type === 'dollar') return '$' + v; return v.toLocaleString('en-US'); }
function fmtPct(m, i) { if (!m.pcts) return ''; const p = m.pcts[i]; if (p === null || p === undefined) return ''; const s = (m.type === 'growth' ? '+' : '') + p + '%'; return '<span style="font-size:11px;color:#6b7280;">' + s + '</span>'; }

// Snapshot cards
const find = n => VITALS.metrics.find(m => m.name === n);
const snap = [
  { m: find('Avg. attendance (in-person)'), label: 'Avg. weekly attendance', extra: 'Goal: 5% growth' },
  { m: find('Adults in circles'),           label: 'Adults in circles',      extra: 'Goal: 70%' },
  { m: find('Regular serving'),             label: 'Regular serving',        extra: 'Goal: 50%' },
  { m: find('Avg. students (in-person)'),   label: 'Avg. students',          extra: 'Goal: 10–15% of attendance' },
  { m: find('Avg. kids (in-person)'),       label: 'Avg. kids',              extra: 'Goal: 15–25% of attendance' },
];
document.getElementById('snapshot-cards').innerHTML = snap.map(({m,label,extra}) => {
  const s = statusFor(m), pct = m.pcts ? m.pcts[CUR] : null;
  const sub = pct !== null ? (m.type === 'growth' ? '+'+pct+'% YoY · '+extra : pct+'% · '+extra) : extra;
  return `<div class="card top-${s}"><div class="label">${label}</div><div class="value">${fmtVal(m,CUR)}</div><div class="sub ${s}">${sub}</div></div>`;
}).join('');

// Metrics tables
function buildTable(metrics, id) {
  let html = `<thead><tr><th>Metric</th><th class="goal-col">Goal</th>` +
    YEARS.slice(0,-1).map(y => `<th>${y}</th>`).join('') +
    `<th style="color:#343A44;">${YEARS[CUR]}</th><th>Status</th></tr></thead><tbody>`;
  metrics.forEach(m => {
    const s = statusFor(m), dag = !m.isAvg ? '<span style="color:#9CA3AF;"> †</span>' : '';
    html += `<tr><td>${m.name}${dag}</td><td class="goal-cell">${m.goal}</td>` +
      YEARS.slice(0,-1).map((y,i) => `<td>${fmtVal(m,i)} ${fmtPct(m,i)}</td>`).join('') +
      `<td><span class="cur-val">${fmtVal(m,CUR)}</span> ${fmtPct(m,CUR)}</td>` +
      `<td><span class="status status-${s}">${statusLabel(s)}</span></td></tr>`;
  });
  document.getElementById(id).innerHTML = html + '</tbody>';
}
buildTable(evangelism, 'evangelismTable');
buildTable(discipleship, 'discipleshipTable');

// Funnel
(function() {
  const v = n => find(n).values[CUR];
  const visitors = v('Sunday visitors'), cb = v('Connect breakfast'), sp = v('Starting Point'), ic = v('Adults in circles');
  const c1 = Math.round(cb / visitors * 100), c2 = Math.round(sp / cb * 100);
  const steps = [
    { num: visitors, label: 'Sunday Visitors', conv: 'Starting point — guests who attended a service', color: '#343A44' },
    { num: cb, label: 'Connect Breakfast', conv: `<strong>${c1}%</strong> of visitors attended Connect Breakfast`, color: '#2F8F5B' },
    { num: sp, label: 'Starting Point', conv: `<strong>${c2}%</strong> of Connect Breakfast attendees completed Starting Point`, color: '#C8842A' },
    { num: ic, label: 'Adults in Circles', conv: `<strong>${ic.toLocaleString()}</strong> adults currently in a circle (avg) — the ultimate discipleship goal`, color: '#4C5564' }
  ];
  document.getElementById('funnel-wrap').innerHTML = steps.map(s =>
    `<div class="funnel-step"><div class="funnel-box"><div class="funnel-num" style="color:${s.color}">${s.num.toLocaleString()}</div><div class="funnel-label">${s.label}</div><div class="funnel-conv">${s.conv}</div></div></div>`).join('');
})();

// Charts
Chart.defaults.font.family = "'Lato', system-ui, Arial, sans-serif";
Chart.defaults.font.size = 12; Chart.defaults.color = '#6b7280';
const gc = 'rgba(0,0,0,0.06)', labels = YEARS.map(String);
const vals = n => find(n).values, pctsOf = n => find(n).pcts;

new Chart(document.getElementById('attendanceChart'), {
  type: 'bar',
  data: { labels, datasets: [
    { label: 'In-person', data: vals('Avg. attendance (in-person)'), backgroundColor: '#343A44', borderRadius: 4 },
    { label: 'Online',    data: vals('Avg. online attendance'),      backgroundColor: '#8899AA', borderRadius: 4 } ] },
  options: { responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ' ' + ctx.dataset.label + ': ' + ctx.raw } } },
    scales: { x: { grid: { display: false }, ticks: { color: '#9CA3AF' } }, y: { grid: { color: gc }, ticks: { color: '#9CA3AF' }, min: 0 } } }
});
new Chart(document.getElementById('breakdownChart'), {
  type: 'bar',
  data: { labels, datasets: [
    { label: 'Adults',   data: vals('Avg. adults (in-person)'),   backgroundColor: '#343A44' },
    { label: 'Kids',     data: vals('Avg. kids (in-person)'),     backgroundColor: '#2F8F5B' },
    { label: 'Students', data: vals('Avg. students (in-person)'), backgroundColor: '#DC2626' },
    { label: 'Online',   data: vals('Avg. online attendance'),    backgroundColor: '#8899AA', borderRadius: 4 } ] },
  options: { responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { mode: 'index' } },
    scales: { x: { stacked: true, grid: { display: false }, ticks: { color: '#9CA3AF' } }, y: { stacked: true, grid: { color: gc }, ticks: { color: '#9CA3AF' }, min: 0 } } }
});

// Seasonality — monthly average weekly attendance, one line per recent year.
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const attMonthly = (VITALS.charts && VITALS.charts.att_monthly) || {};
const allYears = Object.keys(attMonthly).map(Number).sort((a,b) => a - b);
const curYear = (VITALS.charts && VITALS.charts.cur_year) || YEARS[YEARS.length - 1];
const seasonYears = allYears.filter(y => y >= YEARS[0]);   // 2022-on, consistent with the rest of the dashboard
const seasonShades = ['#D3D8DF','#AEB6C1','#7C8595','#5B6472','#454C58'];  // older → newer (non-current)
const seasonDatasets = seasonYears.map((y, i) => {
  const isCur = (y === curYear);
  return { label: String(y), data: attMonthly[String(y)],
    borderColor: isCur ? '#2F8F5B' : (seasonShades[i] || '#9AA3B0'),
    backgroundColor: 'transparent', borderWidth: isCur ? 3 : 2,
    pointRadius: isCur ? 3 : 0, tension: 0.35, spanGaps: true };
});
new Chart(document.getElementById('seasonalityChart'), {
  type: 'line',
  data: { labels: MON, datasets: seasonDatasets },
  options: { responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 12, usePointStyle: true, color: '#6b7280' } },
      tooltip: { callbacks: { label: ctx => ' ' + ctx.dataset.label + ': ' + (ctx.raw == null ? '—' : ctx.raw) } } },
    scales: { x: { grid: { display: false }, ticks: { color: '#9CA3AF' } },
      y: { grid: { color: gc }, ticks: { color: '#9CA3AF' } } } }
});

// 12-month rolling average — trailing-12 mean over the full monthly timeline.
(function () {
  const flat = [];
  allYears.forEach(y => (attMonthly[String(y)] || []).forEach((v, mi) => {
    flat.push({ label: MON[mi] + " '" + String(y).slice(2), v: v });
  }));
  const pts = [], lbls = [];
  for (let i = 11; i < flat.length; i++) {
    const win = flat.slice(i - 11, i + 1);
    if (win.every(p => p.v !== null && p.v !== undefined)) {
      pts.push(Math.round(win.reduce((s, p) => s + p.v, 0) / 12));
      lbls.push(flat[i].label);
    }
  }
  new Chart(document.getElementById('rollingChart'), {
    type: 'line',
    data: { labels: lbls, datasets: [{ label: '12-mo rolling avg', data: pts,
      borderColor: '#343A44', backgroundColor: 'rgba(52,58,68,0.06)', borderWidth: 2.5,
      pointRadius: 0, tension: 0.3, fill: true }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ' ' + ctx.raw } } },
      scales: { x: { grid: { display: false }, ticks: { color: '#9CA3AF', maxTicksLimit: 8, autoSkip: true } },
        y: { grid: { color: gc }, ticks: { color: '#9CA3AF' } } } }
  });
})();
new Chart(document.getElementById('discipleshipChart'), {
  type: 'line',
  data: { labels, datasets: [
    { label: 'Adults in circles %', data: pctsOf('Adults in circles'), borderColor: '#343A44', backgroundColor: 'rgba(52,58,68,0.08)', borderWidth: 2.5, pointRadius: 4, tension: 0.3, fill: true },
    { label: 'Regular serving %',   data: pctsOf('Regular serving'),   borderColor: '#2F8F5B', backgroundColor: 'rgba(47,143,91,0.07)', borderWidth: 2.5, pointRadius: 4, tension: 0.3, fill: true },
    { label: 'Circles goal', data: YEARS.map(() => 70), borderColor: '#343A44', borderDash: [5,4], borderWidth: 1.5, pointRadius: 0, fill: false },
    { label: 'Serving goal', data: YEARS.map(() => 50), borderColor: '#2F8F5B', borderDash: [5,4], borderWidth: 1.5, pointRadius: 0, fill: false } ] },
  options: { responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ' ' + ctx.dataset.label + ': ' + ctx.raw + '%' } } },
    scales: { x: { grid: { display: false }, ticks: { color: '#9CA3AF' } }, y: { grid: { color: gc }, ticks: { callback: v => v + '%', color: '#9CA3AF' }, min: 0, max: 100 } } }
});
</script>
</body>
</html>
"""

def render(metrics, through_week, month, charts=None):
    data = {"years": YEARS, "through_week": through_week, "month": month,
            "generated": datetime.date.today().isoformat(), "metrics": metrics,
            "charts": charts or {}}
    through_short = f"Week {through_week}" if through_week else month
    data_through = f"Week {through_week} · {month} 2026" if through_week else f"{month} 2026"
    last_updated = f"Week {through_week} ({month} 2026)" if through_week else f"{month} 2026"
    ytd_label = (charts or {}).get("ytd_label") or f"Jan–{month}"
    insights = build_insights(metrics)
    ins_html = "".join(
        f'<li><span class="dot dot-{c}"></span><span>{t}</span></li>' for c, t in insights)
    html = (TEMPLATE
        .replace("__DATA__", json.dumps(data))
        .replace("__LAST_UPDATED__", last_updated)
        .replace("__DATA_THROUGH_PLAIN__", data_through.replace(" · ", ", "))
        .replace("__DATA_THROUGH__", data_through)
        .replace("__THROUGH_SHORT__", through_short)
        .replace("__YTD_LABEL__", ytd_label)
        .replace("__INSIGHTS__", ins_html))
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    with open(os.path.join(BASE, "data", "vitals.json"), "w") as f:
        json.dump(data, f, indent=2)
    with open(os.path.join(BASE, "vitals.html"), "w") as f:
        f.write(html)
    return data_through

def main():
    # Current-year values come straight from the warehouse (its PCO/QBO/weekly
    # feeds refresh automatically), so no legacy monthly overlay is applied.
    metrics, tw, month, charts = extract()
    dt = render(metrics, tw, month, charts)
    print(f"Built vitals.html + data/vitals.json — data through {dt}")
    print(f"  {len(metrics)} metrics, through week {tw}, close of {month}")

if __name__ == "__main__":
    main()
