#!/usr/bin/env python3
"""
MCC Financials (Leadership) Dashboard renderer.

Data source: MCC Data Warehouse (see CLAUDE.md DATA ARCHITECTURE). Reads the
`observations` and `config` tabs through warehouse_reader -- the same single
source of truth build_vitals.py / build_connections.py use. NO numbers are
hand-edited in financials.html anymore; re-run this after the monthly QBO pull:

    python3 build_financials.py

Writes:
  MCC/data/financials.json  -- structured data (annual + YTD income/expense, budgets)
  MCC/financials.html       -- the leadership financial-health dashboard, numbers baked in

── Where each number comes from ─────────────────────────────────────────────
  * Monthly income / expense (all years) ... warehouse metric_ids op_income /
        op_expense  (QBO cron writes the current year on the 16th; 2022-2025 were
        backfilled 2026-07-05 from the legacy static.json history arrays).
  * Personnel run-rate (payroll-spike note) ... warehouse metric_id
        personnel_expense.
  * 2026 annual giving budget ................ warehouse config key `annual_budget`.
  * Cash on hand ............................. live.json `bank` minus config
        `restricted_offset` (bank balance is still a live-pull value, not a
        registry metric yet -- see WAREHOUSE-RUNBOOK "Still read at build time").
  * Historical annual budget GOALS 2022-2025 . frozen reference constants below.
        These are closed-year targets that never change (they are goals, not
        observations). Mirrors how build_vitals.py keeps its goal thresholds in
        code. Move them into the config tab if you prefer strict single-source.

The script is warehouse-first with a safety net: if a prior year has no monthly
op_income/op_expense rows in the warehouse (i.e. the monthly backfill didn't
land), it falls back to the frozen FALLBACK_* arrays and prints a loud WARNING
telling you to backfill those months. When the warehouse has the data (the
expected state) the fallback is never touched.
"""
import json, os, datetime, statistics
import warehouse_reader as wh

BASE = os.path.dirname(os.path.abspath(__file__))
YEARS = [2022, 2023, 2024, 2025, 2026]
CUR_YEAR = YEARS[-1]
MONTHS12 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_FULL = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]

INCOME_MID = "op_income"       # QBO "Total Revenue" (4xxx). Displayed as "giving received".
EXPENSE_MID = "op_expense"     # QBO "Total Expenditures" (5xxx+6xxx, excl 8xxx).
PERSONNEL_MID = "personnel_expense"

# Frozen closed-year budget GOALS (targets set at the start of each year; never
# change once the year closes). 2026 comes from the warehouse config tab.
BUDGET_INCOME_HISTORY = {2022: 1203775, 2023: 1220300, 2024: 1482025, 2025: 1604875}

DATA_NOTE = ("2022–2023 actuals include General Fund + Missions Fund "
             "(excl. Pit Road). 2024–2026: General Fund only. "
             "Source: PowerChurch (2022–2025), QuickBooks Online (2026).")

# ── Safety-net fallback: frozen monthly history for closed years (from the
#    legacy static.json this warehouse was backfilled from). Used ONLY if the
#    warehouse has no monthly rows for a given prior year. ──────────────────────
FALLBACK_INCOME = {
    2022: [87163, 95988, 109900, 150004, 113555, 110814, 95557, 87095, 118557, 104098, 107596, 225857],
    2023: [64824, 89895, 119128, 130114, 90236, 125297, 138285, 105685, 167928, 128029, 112626, 243665],
    2024: [76299, 86725, 138867, 114826, 97422, 121975, 111852, 101834, 129043, 97945, 99601, 242301],
    2025: [65693, 97362, 161385, 130448, 132355, 132973, 100146, 145551, 117019, 123389, 123635, 223569],
}
FALLBACK_EXPENSE = {
    2022: [94382, 100727, 141604, 97031, 111113, 157223, 94621, 108767, 128289, 96490, 139379, 104951],
    2023: [100898, 112560, 110885, 112667, 145223, 94965, 122961, 99505, 103231, 104863, 137802, 103735],
    2024: [102264, 118014, 91828, 96847, 134588, 121862, 96511, 100754, 102729, 147714, 104708, 171347],
    2025: [121234, 119485, 120650, 142802, 124219, 149949, 112898, 128108, 120214, 160439, 129052, 145528],
}

_warnings = []


def _monthly_list(mid, year, fallback):
    """Return a 12-slot list (Jan..Dec) of monthly values for `mid`/`year`,
    using warehouse observations; falling back to the frozen array (closed years
    only) if the warehouse has nothing for that year."""
    m = wh.monthly(mid, year)  # {month_index: value}
    if m:
        return [m.get(i + 1) for i in range(12)]
    if fallback and year in fallback:
        _warnings.append(
            "WARNING: no monthly '%s' rows in the warehouse for %d -- used frozen "
            "fallback. Backfill via POST /warehouse/append (source "
            "'backfill:static.json') so the warehouse is complete." % (mid, year))
        return list(fallback[year])
    return [None] * 12


def _sum(vals, upto=None):
    xs = [v for v in (vals[:upto] if upto else vals) if v is not None]
    return round(sum(xs), 2) if xs else None


def extract():
    inc = {y: _monthly_list(INCOME_MID, y, FALLBACK_INCOME) for y in YEARS}
    exp = {y: _monthly_list(EXPENSE_MID, y, FALLBACK_EXPENSE) for y in YEARS}
    per = {y: _monthly_list(PERSONNEL_MID, y, None) for y in YEARS}

    # Reporting month = the last month with a current-year income observation.
    present = [i + 1 for i, v in enumerate(inc[CUR_YEAR]) if v is not None]
    if not present:
        raise SystemExit(
            "ERROR: the warehouse has no %s rows for %d yet. Run the QBO pull "
            "(POST /warehouse/pull {job:'qbo', month:'%d-MM'}) first." %
            (INCOME_MID, CUR_YEAR, CUR_YEAR))
    rm = max(present)                      # 1-based reporting month index
    months_lbl = MONTHS12[:rm]

    # Full-year actuals for closed (prior) years; YTD sum for the current year.
    annual_income = {y: _sum(inc[y]) for y in YEARS[:-1]}
    annual_expense = {y: _sum(exp[y]) for y in YEARS[:-1]}

    # Period-matched Jan..reporting-month totals across all five years.
    jan_income = {y: _sum(inc[y], upto=rm) for y in YEARS}
    jan_expense = {y: _sum(exp[y], upto=rm) for y in YEARS}

    ytd_income = [inc[CUR_YEAR][i] for i in range(rm)]
    ytd_expense = [exp[CUR_YEAR][i] for i in range(rm)]

    # Budgets: current year from config, closed years from frozen goals.
    cfg = wh.config()
    budget_2026 = cfg.get("annual_budget")
    if budget_2026 is None:
        _warnings.append("WARNING: config key 'annual_budget' missing -- 2026 "
                         "budget card/table will show a gap.")
    budget_income = dict(BUDGET_INCOME_HISTORY)
    if budget_2026 is not None:
        budget_income[CUR_YEAR] = round(budget_2026)

    # Cash on hand = live bank balance minus restricted offset (both still live
    # values per the runbook; restricted_offset lives in config).
    cash = None
    try:
        with open(os.path.join(BASE, "data", "live.json")) as f:
            live = json.load(f)
        bank = live.get("bank")
        restr = cfg.get("restricted_offset")
        if bank is not None and restr is not None:
            cash = round(bank - restr, 2)
        elif bank is not None:
            cash = round(bank, 2)
            _warnings.append("WARNING: config 'restricted_offset' missing -- cash "
                             "on hand shows the TOTAL bank balance, not unrestricted.")
    except (OSError, ValueError):
        _warnings.append("WARNING: data/live.json unreadable -- cash-on-hand card omitted.")

    # Payroll-spike note (the recurring 3rd-paycheck month on a bi-weekly cycle),
    # detected from personnel_expense instead of hard-coding "April".
    payroll_note = _payroll_note(per[CUR_YEAR], rm)

    return dict(
        reporting_month=rm, months=months_lbl,
        annual_income=annual_income, annual_expense=annual_expense,
        jan_income=jan_income, jan_expense=jan_expense,
        ytd_income=ytd_income, ytd_expense=ytd_expense,
        budget_income=budget_income, cash_on_hand=cash,
        payroll_note=payroll_note,
        last_updated="%s %d" % (MONTH_FULL[rm - 1], CUR_YEAR),
        generated=datetime.date.today().isoformat(),
    )


def _payroll_note(personnel, rm):
    vals = [v for v in personnel[:rm] if v is not None]
    if len(vals) < 3:
        return ("Personnel is the largest single cost each month; watch the "
                "monthly run-rate as the main lever on total spending.")
    med = statistics.median(vals)
    spikes = [i for i, v in enumerate(personnel[:rm])
              if v is not None and v > med * 1.2]
    normal = [v for i, v in enumerate(personnel[:rm])
              if v is not None and i not in spikes]
    lo, hi = (min(normal), max(normal)) if normal else (med, med)
    rng = "%s–%s" % (_k(lo), _k(hi))
    if spikes:
        names = [MONTH_FULL[i] for i in spikes]
        joined = names[0] if len(names) == 1 else (
            " and ".join(names) if len(names) == 2 else
            ", ".join(names[:-1]) + ", and " + names[-1])
        verb = "was" if len(names) == 1 else "were"
        return ("%s's higher cost total %s driven by a <strong>third payroll in "
                "the month</strong> — a calendar artifact that occurs 2–3 "
                "times a year on a bi-weekly pay schedule, not a new permanent "
                "cost level. The normal monthly personnel run rate is about "
                "<strong>%s per month</strong>." % (joined, verb, rng))
    return ("Personnel is the biggest monthly cost; the run rate has held steady "
            "at about <strong>%s per month</strong> so far this year." % rng)


def _k(v):
    return "$%s" % format(int(round(v / 1000.0) * 1000), ",")


# ── HTML template (structure/CSS/chart JS identical to the hand-built
#    financials.html; only the DATA constants and the payroll insight are now
#    generated). Placeholders: __DATA_BLOCK__, __PAYROLL_NOTE__. ───────────────
TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>MCC Financials Dashboard</title>
<link rel="icon" type="image/png" href="favicon.png">
<link rel="apple-touch-icon" href="favicon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap" rel="stylesheet">
<style>
  :root {
    --slate: #343A44;
    --bg: #F2F2F2;
    --card: #ffffff;
    --ink: #23272e;
    --muted: #6b7280;
    --line: #e3e5ea;
    --red: #DC2626;
    --green: #2F8F5B;
    --amber: #C8842A;
    --chart: #4C5564;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Lato', system-ui, -apple-system, Arial, sans-serif; background: var(--bg); color: var(--ink); font-size: 15px; line-height: 1.6; }

  /* -- MCC Header -- */
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
  .mcc-header .right strong { display: block; font-size: 15px; font-weight: 900; letter-spacing: -.01em; opacity: 1; }

  /* -- Layout -- */
  .page { max-width: 1180px; margin: 0 auto; padding: 28px 30px 60px; }
  .section-label { font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin-bottom: 12px; margin-top: 32px; }

  /* -- Snapshot cards -- */
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 4px; }
  .card { background: var(--card); border-radius: 10px; padding: 18px 20px; border: 1px solid var(--line); box-shadow: 0 1px 4px rgba(20,30,60,.05); }
  .card .label { font-size: 12px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
  .card .value { font-size: 24px; font-weight: 900; color: var(--slate); letter-spacing: -0.5px; }
  .card .sub   { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .card .sub.up      { color: var(--green); }
  .card .sub.down    { color: var(--red); }
  .card .sub.neutral { color: var(--muted); }
  .card.accent-green { border-top: 4px solid var(--green); }
  .card.accent-red   { border-top: 4px solid var(--red); }
  .card.accent-blue  { border-top: 4px solid var(--slate); }
  .card.accent-amber { border-top: 4px solid var(--amber); }

  /* -- Chart cards -- */
  .chart-card { background: var(--card); border-radius: 10px; padding: 22px 22px 18px; border: 1px solid var(--line); margin-bottom: 14px; box-shadow: 0 1px 4px rgba(20,30,60,.05); }
  .chart-card h2 { font-size: 15px; font-weight: 900; text-transform: uppercase; letter-spacing: -.01em; color: var(--slate); margin-bottom: 4px; }
  .chart-card .chart-sub { font-size: 13px; color: var(--muted); margin-bottom: 16px; }
  .chart-wrap { position: relative; width: 100%; }

  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 680px) { .grid-2 { grid-template-columns: 1fr; } }

  .legend { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 14px; }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); font-weight: 700; }
  .legend-dot  { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }

  /* -- Insights -- */
  .insights { background: #F4F5F7; border: 1px solid var(--line); border-radius: 10px; padding: 20px 24px; margin-top: 6px; }
  .insights h2 { font-size: 13px; font-weight: 900; text-transform: uppercase; letter-spacing: .08em; color: var(--slate); margin-bottom: 12px; }
  .insights ul { list-style: none; }
  .insights ul li { padding: 8px 0; border-bottom: 1px solid var(--line); font-size: 13px; color: var(--ink); display: flex; align-items: flex-start; gap: 10px; line-height: 1.55; }
  .insights ul li:last-child { border-bottom: none; }
  .dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
  .dot-green  { background: var(--green); }
  .dot-red    { background: var(--red); }
  .dot-amber  { background: var(--amber); }
  .dot-blue   { background: var(--slate); }

  /* -- Data table -- */
  .data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .data-table th { background: #F9FAFB; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; font-size: 11px; color: var(--muted); padding: 9px 12px; text-align: right; border-bottom: 1px solid var(--line); }
  .data-table th:first-child { text-align: left; }
  .data-table td { padding: 9px 12px; border-bottom: 1px solid #F3F4F6; text-align: right; color: var(--ink); }
  .data-table td:first-child { text-align: left; font-weight: 700; color: var(--slate); }
  .data-table tr:last-child td { border-bottom: none; font-weight: 700; background: #F9FAFB; }
  .pos { color: var(--green); font-weight: 700; }
  .neg { color: var(--red); font-weight: 700; }
  .ytd-col { color: var(--slate); font-weight: 700; }

  /* -- Footer -- */
  .mcc-footer { color: var(--muted); font-size: 11.5px; margin-top: 44px; line-height: 1.8; text-align: center; }
</style>
</head>
<body>

<script>
// ==============================================================
//  DATA -- generated by build_financials.py from the MCC Data Warehouse.
//  Do NOT hand-edit. Re-run:  python3 build_financials.py
// ==============================================================
__DATA_BLOCK__
</script>

<header class="mcc-header">
  <div class="mcc-header-inner">
  <div class="brand">
    <img class="logo" src="https://storage1.snappages.site/VCFHFT/assets/images/22645050_962x358_500.png" alt="Maple City Chapel">
    <div>
      <a class="back" href="index.html">&larr; Leadership Portal</a>
      <h1>MCC Financials</h1>
      <div class="sub">Financial Health Dashboard &nbsp;&middot;&nbsp; General Fund</div>
    </div>
  </div>
  <div class="right">Data through<strong id="hdr-date"></strong></div>
  </div>
</header>

<div class="page">

  <div class="section-label">2026 Year-to-Date Snapshot (January &ndash; <span class="hdr-month"></span>)</div>
  <div class="cards" id="snapshot-cards"></div>

  <div class="section-label">Key takeaways</div>
  <div class="insights"><h2>What this data is telling us</h2><ul id="insights-list"></ul></div>

  <div class="section-label">Annual giving &mdash; are we growing?</div>
  <div class="chart-card">
    <h2>Total giving received each year</h2>
    <p class="chart-sub">Full-year totals for 2022&ndash;2025. The 2026 bar shows giving received so far (January through <span class="hdr-month"></span>).</p>
    <div class="legend"><span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>Prior years (full year)</span><span class="legend-item"><span class="legend-dot" style="background:#8899AA;"></span>2026 year-to-date</span></div>
    <div class="chart-wrap" style="height:210px;"><canvas id="givingChart" role="img" aria-label="Annual giving 2022 through 2026 YTD"></canvas></div>
  </div>

  <div class="section-label">Is giving covering our costs?</div>
  <div class="chart-card">
    <h2>Annual giving vs operating costs</h2>
    <p class="chart-sub">When the slate bar is taller, we finished the year with a surplus. When amber is taller, we ran a deficit.</p>
    <div class="legend"><span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>Giving received</span><span class="legend-item"><span class="legend-dot" style="background:#C8842A;"></span>Operating costs</span></div>
    <div class="chart-wrap" style="height:230px;"><canvas id="incExpChart" role="img" aria-label="Giving vs operating costs 2022 through 2026 YTD"></canvas></div>
  </div>

  <div class="section-label">2026 monthly detail</div>
  <div class="grid-2">
    <div class="chart-card">
      <h2>2026 month-by-month</h2>
      <p class="chart-sub">Giving vs costs for each month so far in 2026.</p>
      <div class="legend"><span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>Giving</span><span class="legend-item"><span class="legend-dot" style="background:#C8842A;"></span>Costs</span></div>
      <div class="chart-wrap" style="height:190px;"><canvas id="monthlyChart" role="img" aria-label="2026 monthly giving vs costs"></canvas></div>
    </div>
    <div class="chart-card">
      <h2>Jan&ndash;<span class="hdr-month"></span> net: 5-year view</h2>
      <p class="chart-sub">Surplus or deficit in the same window across all five years.</p>
      <div class="legend"><span class="legend-item"><span class="legend-dot" style="background:#2F8F5B;"></span>Surplus</span><span class="legend-item"><span class="legend-dot" style="background:#DC2626;"></span>Deficit</span></div>
      <div class="chart-wrap" style="height:190px;"><canvas id="netChart" role="img" aria-label="Jan through reporting month net by year 2022 to 2026"></canvas></div>
    </div>
  </div>

  <div class="section-label">How are we tracking against our budgets?</div>
  <div class="chart-card">
    <h2>Giving budget vs actual &mdash; year by year</h2>
    <p class="chart-sub">Budget is the target set at the start of each year. Variance shows whether we came in above or below the goal.</p>
    <table class="data-table" id="budgetTable"></table>
  </div>

  <div class="section-label">Full summary</div>
  <div class="chart-card">
    <h2>General Fund &mdash; year-by-year totals</h2>
    <p class="chart-sub">All figures are full-year actuals except 2026, which reflects January through <span class="hdr-month"></span> only.</p>
    <table class="data-table" id="summaryTable"></table>
  </div>

  <div class="mcc-footer">
    <p>Maple City Chapel &nbsp;&middot;&nbsp; Financials Dashboard &nbsp;&middot;&nbsp; Updated through <span id="ftr-date"></span></p>
    <p id="ftr-note" style="margin-top:2px;"></p>
  </div>

</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
function fmt(v) {
  if (v === null || v === undefined) return '—';
  const abs = Math.abs(v);
  const s = abs >= 1000000 ? '$' + (abs/1000000).toFixed(2) + 'M' : '$' + abs.toLocaleString('en-US');
  return v < 0 ? '(' + s + ')' : s;
}

const lastMonth = ytd2026Months[ytd2026Months.length - 1];
document.getElementById('hdr-date').textContent = lastMonth + ' ' + LAST_UPDATED.split(' ')[1];
document.getElementById('ftr-date').textContent = LAST_UPDATED;
document.getElementById('ftr-note').textContent = DATA_NOTE;
document.querySelectorAll('.hdr-month').forEach(el => el.textContent = lastMonth);

const ytdInc = ytd2026Income.reduce((a,b)=>a+b,0);
const ytdExp = ytd2026Expense.reduce((a,b)=>a+b,0);
const ytdNet = ytdInc - ytdExp;
const avgMonthlyExp = ytdExp / ytd2026Months.length;
const monthsCash = CASH_ON_HAND === null ? null : (CASH_ON_HAND / avgMonthlyExp).toFixed(1);
const cashCls = monthsCash === null ? 'neutral' : monthsCash >= 3 ? 'up' : monthsCash >= 1.5 ? 'neutral' : 'down';
const cashAccent = monthsCash === null ? 'accent-blue' : monthsCash >= 3 ? 'accent-green' : monthsCash >= 1.5 ? 'accent-amber' : 'accent-red';
const incChg = ((ytdInc-janAprIncome[2025])/janAprIncome[2025]*100).toFixed(1);
const expChg = ((ytdExp-janAprExpense[2025])/janAprExpense[2025]*100).toFixed(1);
const budget2026 = annualBudgetIncome[2026] || null;

const cards = [
  { label:'Giving received (Jan–'+lastMonth+')', value:fmt(ytdInc), sub:(incChg>=0?'▲ ':'▼ ')+Math.abs(incChg)+'% vs same period last year', cls:incChg>=0?'up':'down', accent:'accent-blue' },
  { label:'Operating costs (Jan–'+lastMonth+')', value:fmt(ytdExp), sub:(expChg>=0?'▲ ':'▼ ')+Math.abs(expChg)+'% vs same period last year', cls:Number(expChg)<=3?'up':'down', accent:'accent-amber' },
  { label:'Net (surplus or deficit)', value:fmt(ytdNet), sub:ytdNet>=0?'Surplus — giving is covering costs':'Deficit — costs exceeding giving', cls:ytdNet>=0?'up':'down', accent:ytdNet>=0?'accent-green':'accent-red' }
];
if (budget2026) cards.push({ label:'2026 annual budget', value:fmt(budget2026), sub:'Received '+Math.round(ytdInc/budget2026*100)+'% of full-year goal so far', cls:'neutral', accent:'accent-blue' });
if (monthsCash !== null) cards.push({ label:'Months of cash on hand', value:monthsCash + ' mo.', sub: monthsCash >= 3 ? 'Healthy — target is 3–6 months' : monthsCash >= 1.5 ? 'Caution — below the 3-month target' : 'Low — under 1.5 months of runway', cls:cashCls, accent:cashAccent });
document.getElementById('snapshot-cards').innerHTML = cards.map(c=>`<div class="card ${c.accent}"><div class="label">${c.label}</div><div class="value">${c.value}</div><div class="sub ${c.cls}">${c.sub}</div></div>`).join('');

const netVsLastYear = fmt(janAprIncome[2025]-janAprExpense[2025]);
const priorNets = [2022,2023,2024,2025].map(y=>janAprIncome[y]-janAprExpense[y]);
const worstPrior = Math.min(...priorNets);
const deficitLead = ytdNet <= worstPrior
  ? `The January–${lastMonth} deficit of <strong>${fmt(ytdNet)}</strong> is the largest in five years`
  : `The January–${lastMonth} net of <strong>${fmt(ytdNet)}</strong> sits within the five-year range`;
const insights = [
  { dot: ytdInc >= Math.max(...[2022,2023,2024,2025].map(y=>janAprIncome[y])) ? 'dot-green' : 'dot-blue',
    text:`Giving in the January–${lastMonth} window is <strong>${fmt(ytdInc)}</strong>, ${incChg>=0?'up':'down'} ${Math.abs(incChg)}% from the same period in 2025. ${ytdInc >= Math.max(...[2022,2023,2024,2025].map(y=>janAprIncome[y])) ? 'That is the strongest start on record.' : 'Momentum is tracking with recent years.'}` },
  { dot: Number(expChg) > Number(incChg) ? 'dot-red' : 'dot-green',
    text:`Operating costs are ${expChg>=0?'up':'down'} <strong>${Math.abs(expChg)}%</strong> year-over-year vs ${incChg}% giving growth. For every dollar received in 2026, we are spending <strong>$${(ytdExp/ytdInc).toFixed(2)}</strong>.${Number(expChg) > Number(incChg) ? ' Costs outpacing giving is the key financial challenge right now.' : ''}` },
  { dot: ytdNet >= 0 ? 'dot-green' : 'dot-amber',
    text:`${deficitLead}${ytdNet < 0 && ytdNet <= worstPrior ? `, more than the deficit in the same period of 2025 (${netVsLastYear})` : ''}. This warrants monitoring as seasonal giving patterns play out.` },
  { dot:'dot-blue', text: PAYROLL_NOTE }
];
if (budget2026) insights.push({ dot:'dot-blue', text:`We have received <strong>${Math.round(ytdInc/budget2026*100)}%</strong> of our full-year budget of ${fmt(budget2026)} through ${lastMonth}. Historically, strong giving in the fall and December is essential to finishing the year on track.` });
if (monthsCash !== null) insights.push({ dot: monthsCash >= 3 ? 'dot-green' : monthsCash >= 1.5 ? 'dot-amber' : 'dot-red', text:`We currently have <strong>${monthsCash} months of cash on hand</strong> (${fmt(CASH_ON_HAND)} in reserves ÷ ${fmt(Math.round(avgMonthlyExp))} avg monthly costs). The healthy target for a church is <strong>3–6 months</strong>. ${monthsCash >= 3 ? 'We are within that range.' : 'Building reserves toward the 3-month floor should be a priority.'}` });
document.getElementById('insights-list').innerHTML = insights.map(i=>`<li><span class="dot ${i.dot}"></span><span>${i.text}</span></li>`).join('');

Chart.defaults.font.family = "'Lato', system-ui, Arial, sans-serif";
Chart.defaults.font.size = 12;
Chart.defaults.color = '#6b7280';
const gc = 'rgba(0,0,0,0.06)';
const yT = { callback: v => '$' + Math.round(Math.abs(v)/1000) + 'K', color: '#9CA3AF' };
const yN = { callback: v => (v<0?'-$':'$') + Math.round(Math.abs(v)/1000) + 'K', color: '#9CA3AF' };
const priorYears = [2022,2023,2024,2025];

new Chart(document.getElementById('givingChart'),{type:'bar',data:{labels:[...priorYears.map(String),'2026 YTD'],datasets:[{data:[...priorYears.map(y=>annualIncome[y]),ytdInc],backgroundColor:[...priorYears.map(()=>'#343A44'),'#8899AA'],borderRadius:5}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>' '+fmt(ctx.raw)}}},scales:{x:{grid:{display:false},ticks:{color:'#9CA3AF'}},y:{grid:{color:gc},ticks:yT,min:0}}}});

new Chart(document.getElementById('incExpChart'),{type:'bar',data:{labels:[...priorYears.map(String),'2026 YTD'],datasets:[{label:'Giving received',data:[...priorYears.map(y=>annualIncome[y]),ytdInc],backgroundColor:'#343A44',borderRadius:4},{label:'Operating costs',data:[...priorYears.map(y=>annualExpense[y]),ytdExp],backgroundColor:'#C8842A',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>' '+ctx.dataset.label+': '+fmt(ctx.raw)}}},scales:{x:{grid:{display:false},ticks:{color:'#9CA3AF'}},y:{grid:{color:gc},ticks:yT,min:0}}}});

new Chart(document.getElementById('monthlyChart'),{type:'bar',data:{labels:ytd2026Months,datasets:[{label:'Giving',data:ytd2026Income,backgroundColor:'#343A44',borderRadius:4},{label:'Costs',data:ytd2026Expense,backgroundColor:'#C8842A',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>' '+fmt(ctx.raw)}}},scales:{x:{grid:{display:false},ticks:{color:'#9CA3AF'}},y:{grid:{color:gc},ticks:yT,min:0}}}});

const nv=[2022,2023,2024,2025,2026].map(y=>janAprIncome[y]-janAprExpense[y]);
new Chart(document.getElementById('netChart'),{type:'bar',data:{labels:['2022','2023','2024','2025','2026'],datasets:[{data:nv,backgroundColor:nv.map(v=>v>=0?'#2F8F5B':'#DC2626'),borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>' Net: '+fmt(ctx.raw)}}},scales:{x:{grid:{display:false},ticks:{color:'#9CA3AF'}},y:{grid:{color:gc},ticks:yN}}}});

let bh=`<thead><tr><th>Year</th><th>Giving goal</th><th>Giving received</th><th>Variance</th><th>vs goal</th></tr></thead><tbody>`;
priorYears.forEach(y=>{const b=annualBudgetIncome[y],a=annualIncome[y];if(b==null||a==null){bh+=`<tr><td>${y}</td><td>${fmt(b)}</td><td>${fmt(a)}</td><td>—</td><td>—</td></tr>`;return;}const d=a-b,c=d>=0?'pos':'neg';bh+=`<tr><td>${y}</td><td>${fmt(b)}</td><td>${fmt(a)}</td><td class="${c}">${d>=0?'+':''}${fmt(d)}</td><td class="${c}">${d>=0?'+':''}${(d/b*100).toFixed(1)}%</td></tr>`;});
if(budget2026){bh+=`<tr><td>2026 (Jan–${lastMonth})</td><td>${fmt(budget2026)} annual goal</td><td>${fmt(ytdInc)} received</td><td class="ytd-col">${Math.round(ytdInc/budget2026*100)}% of goal reached</td><td class="ytd-col">YTD only</td></tr>`;}
bh+=`</tbody>`;
document.getElementById('budgetTable').innerHTML=bh;

let sh=`<thead><tr><th>Year</th><th>Giving received</th><th>Operating costs</th><th>Net</th><th>Giving YoY</th></tr></thead><tbody>`;
priorYears.forEach((y,i)=>{const inc=annualIncome[y],exp=annualExpense[y],net=(inc==null||exp==null)?null:inc-exp,prev=i>0?annualIncome[priorYears[i-1]]:null,cs=(prev&&inc!=null)?((inc-prev)/prev*100).toFixed(1)+'%':'—',cc=(prev&&inc!=null)?(inc>=prev?'pos':'neg'):'';sh+=`<tr><td>${y}</td><td>${fmt(inc)}</td><td>${fmt(exp)}</td><td class="${net!=null&&net>=0?'pos':'neg'}">${net!=null&&net>=0?'+':''}${fmt(net)}</td><td class="${cc}">${(prev&&inc!=null)?(inc>=prev?'+':'')+cs:cs}</td></tr>`;});
sh+=`<tr><td>2026 (Jan–${lastMonth})</td><td class="ytd-col">${fmt(ytdInc)}</td><td class="ytd-col">${fmt(ytdExp)}</td><td class="${ytdNet>=0?'pos':'neg'}">${fmt(ytdNet)}</td><td class="ytd-col">${incChg>=0?'+':''}${incChg}% vs 2025 same period</td></tr></tbody>`;
document.getElementById('summaryTable').innerHTML=sh;
</script>
</body>
</html>
"""


def _js_obj(d):
    return "{" + ",".join("%d:%s" % (k, _js_num(v)) for k, v in sorted(d.items())) + "}"


def _js_arr(xs):
    return "[" + ",".join(_js_num(v) for v in xs) + "]"


def _js_num(v):
    if v is None:
        return "null"
    return repr(round(v, 2)) if isinstance(v, float) and v != int(v) else str(int(round(v)))


def data_block(d):
    lines = [
        "const annualIncome  = %s;" % _js_obj(d["annual_income"]),
        "const annualExpense = %s;" % _js_obj(d["annual_expense"]),
        "const annualBudgetIncome  = %s;" % _js_obj(d["budget_income"]),
        "const ytd2026Income  = %s;" % _js_arr(d["ytd_income"]),
        "const ytd2026Expense = %s;" % _js_arr(d["ytd_expense"]),
        "const ytd2026Months  = %s;" % json.dumps(d["months"]),
        "const janAprIncome  = %s;" % _js_obj(d["jan_income"]),
        "const janAprExpense = %s;" % _js_obj(d["jan_expense"]),
        "const LAST_UPDATED = %s;" % json.dumps(d["last_updated"]),
        "const DATA_NOTE    = %s;" % json.dumps(DATA_NOTE),
        "const CASH_ON_HAND = %s;" % _js_num(d["cash_on_hand"]),
        "const PAYROLL_NOTE = %s;" % json.dumps(d["payroll_note"]),
    ]
    return "\n".join(lines)


def render(d):
    html = TEMPLATE.replace("__DATA_BLOCK__", data_block(d))
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    with open(os.path.join(BASE, "data", "financials.json"), "w") as f:
        json.dump(d, f, indent=2)
    with open(os.path.join(BASE, "financials.html"), "w") as f:
        f.write(html)


def main():
    d = extract()
    render(d)
    m = MONTH_FULL[d["reporting_month"] - 1]
    ytd_inc = _sum(d["ytd_income"])
    ytd_exp = _sum(d["ytd_expense"])
    print("Built financials.html + data/financials.json — data through %s %d" % (m, CUR_YEAR))
    print("  YTD giving %s / costs %s / net %s"
          % (ytd_inc, ytd_exp, round((ytd_inc or 0) - (ytd_exp or 0), 2)))
    print("  annual giving (actual): " +
          ", ".join("%d=%s" % (y, d["annual_income"][y]) for y in YEARS[:-1]))
    print("  cash on hand: %s" % d["cash_on_hand"])
    for w in _warnings:
        print("  " + w)
    if not _warnings:
        print("  all values sourced from the warehouse (no fallbacks used).")


if __name__ == "__main__":
    main()
