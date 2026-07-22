#!/usr/bin/env python3
"""
MCC Finance Team Dashboard renderer.

Merges three data layers and writes finance-team.html:
  data/static.json       -- frozen: 2022-2025 history, budget constants, loan terms
  data/2026-actuals.json -- cached: finalized (closed) 2026 months
  data/live.json         -- dynamic: this week's open month, KPIs, PCO, Ramp, balances

Weekly job only needs to: refresh live.json (and, when a month closes, append it to
2026-actuals.json), then run:  python3 build_dashboard.py

The template/CSS/chart config below is stable; numbers come entirely from the JSON.
"""
import json, os, sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
def load(p):
    with open(os.path.join(BASE, "data", p)) as f:
        return json.load(f)

static = load("static.json")
actuals = load("2026-actuals.json")
live = load("live.json")

MONTHS12 = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

C = static["constants"]
WEEKLY_BUDGET = C["weekly_budget"]; ANNUAL_BUDGET = C["annual_budget"]; RESTR = C["restricted_offset"]
LT = static["loan_terms"]
RUN_DATE = live["run_date"]; RUN_WEEKDAY = live["run_weekday"]; DATA_THROUGH = live["data_through"]
WEEKS_YTD = live["weeks_ytd"]; RMI = live["reporting_month_index"]  # 1-based count of months Jan..reporting
# Last-week giving window = the 7 days ending on the last Sunday (= DATA_THROUGH). Derived, never hardcoded.
_wk_end = datetime.strptime(DATA_THROUGH, "%B %d, %Y"); _wk_start = _wk_end - timedelta(days=6)
if _wk_start.month == _wk_end.month:
    WEEK_LABEL = "%s %d&ndash;%d" % (_wk_start.strftime("%b"), _wk_start.day, _wk_end.day)
else:
    WEEK_LABEL = "%s %d&ndash;%s %d" % (_wk_start.strftime("%b"), _wk_start.day, _wk_end.strftime("%b"), _wk_end.day)

# ---- Merge closed + current into 2026 monthly arrays (length = RMI) ----
def series(field):
    arr = [actuals["closed_months"][MONTHS12[i]][field] for i in range(RMI-1)]
    arr.append(live["current_month"][field])
    return arr
g26  = series("giving4100")
oi26 = series("op_income")
oe26 = series("op_expense")
pe26 = series("personnel")
fa26 = series("facilities")

ytd_giving = round(sum(g26),2); ytd_opinc = round(sum(oi26),2); ytd_opexp = round(sum(oe26),2)
ytd_pers   = round(sum(pe26),2); ytd_fac   = round(sum(fa26),2)
n_closed = RMI-1
avg_monthly_opexp = sum(oe26[:n_closed])/n_closed if n_closed else oe26[0]

# ---- KPIs ----
last_week_giving = live["last_week_giving"]
current_giving   = live["current_month"]["giving4100"]
bank = live["bank"]; unrestricted = round(bank - RESTR, 2)
months_cash = unrestricted/avg_monthly_opexp
loan_balance = live["loan_balance"]
loan_rate = LT["rate"]; loan_pay = LT["payment"]; loan_prin = LT["principal"]; loan_int = LT["interest"]

gh = live["giving_health"]
committed = gh["committed"]; households = gh["households"]; participation = committed/households*100
new_donors_year = gh["new_donors_year"]; new_donors_week = gh["new_donors_week"]
rt = live["retention"]
retained = rt["retained"]; lapsed = rt["lapsed"]; newly = rt["new"]; retention = rt["rate"]; prior_committed = rt["prior"]

ytd_budget = WEEKLY_BUDGET*WEEKS_YTD
budget_var = round(ytd_giving - ytd_budget,2)
budget_pct = ytd_giving/ytd_budget*100
avg_wk_giving = ytd_giving/WEEKS_YTD
inc_bar = ytd_giving/ANNUAL_BUDGET*100
exp_bar = ytd_opexp/ANNUAL_BUDGET*100
opinc_bar = ytd_opinc/ANNUAL_BUDGET*100
op_net = round(ytd_opinc - ytd_opexp, 2)          # >0 surplus, <0 deficit
op_ratio = ytd_opexp/ytd_opinc*100 if ytd_opinc else 0
pace = WEEKS_YTD/52*100
pers_ann = ytd_pers*52/WEEKS_YTD; pers_pct = pers_ann/ANNUAL_BUDGET*100
fac_ann  = ytd_fac*52/WEEKS_YTD;  fac_pct  = fac_ann/ANNUAL_BUDGET*100

rmp = live["ramp"]
card_mtd=rmp["card_mtd"]; card_mtd_n=rmp["card_mtd_n"]; card_7d=rmp["card_7d"]; card_7d_n=rmp["card_7d_n"]
ap_paid_mtd=rmp["ap_paid_mtd"]; ap_paid_n=rmp["ap_paid_n"]; ap_out=rmp["ap_out"]; ap_open_n=rmp["ap_open_n"]
card_over=rmp["card_over"]; bills_paid=rmp["bills_paid"]

inc = {int(y):v for y,v in static["history_income"].items()}
exp = {int(y):v for y,v in static["history_expense"].items()}
RMONTH = live["reporting_month_name"]

# ---- formatters: minus BEFORE dollar ----
def d(n):
    n=round(n); return ("-${:,}".format(abs(int(n)))) if n<0 else ("${:,}".format(int(n)))
def dc(n):
    return ("-${:,.2f}".format(abs(n))) if n<0 else ("${:,.2f}".format(n))

# ---- chart datasets (full 12-mo prior years; 2026 padded with null) ----
giving_2024 = inc[2024]; giving_2025 = inc[2025]; giving_2026 = g26 + [None]*(12-RMI)
exp_2024 = exp[2024]; exp_2025 = exp[2025]; exp_2026 = oe26 + [None]*(12-RMI)

# YoY (closed months only, apples-to-apples)
giv_yoy = (sum(g26[:n_closed])/sum(inc[2025][:n_closed])-1)*100
exp_yoy = (sum(oe26[:n_closed])/sum(exp[2025][:n_closed])-1)*100

# Monthly operating surplus/deficit across closed months (for the deficit-trend insight)
net_closed = [round(oi26[i]-oe26[i],2) for i in range(n_closed)]
ytd_net_closed = round(sum(net_closed),2)
first2 = round(sum(net_closed[:2])/2,2) if n_closed>=2 else net_closed[0]
last_closed_net = net_closed[-1]
best_closed_net = max(net_closed)

# ---- Insights engine: each rule reads THIS run's numbers, sets its own
#      severity (green/amber/red) from thresholds, and only surfaces the
#      framing the data supports. Sorted most-urgent first. ----
net_committed = newly - lapsed
def _dir(x, pos, neg):        # directional word by sign
    return pos if x >= 0 else neg
def _pct(x):                  # "up ~12%" / "down ~3%"
    return ("up ~%.0f%%" % x) if x >= 0 else ("down ~%.0f%%" % abs(x))

insights = []
def add(sev, label, title, body):
    insights.append((sev, label, title, body))

# --- Giving vs budget pace ---
if budget_pct >= 100:
    add("green","Strength","Giving at or above budget",
        "Average weekly giving is %s vs the %s/week budget (%.0f%% of pace) &mdash; about %s/week ahead. YTD giving %s vs a %s budgeted pace."
        % (d(avg_wk_giving), d(WEEKLY_BUDGET), budget_pct, d(avg_wk_giving-WEEKLY_BUDGET), d(ytd_giving), d(ytd_budget)))
elif budget_pct >= 90:
    add("amber","Watch","Giving slightly behind budget",
        "Average weekly giving is %s vs the %s/week budget (%.0f%% of pace) &mdash; about %s/week behind. YTD giving %s vs a %s budgeted pace."
        % (d(avg_wk_giving), d(WEEKLY_BUDGET), budget_pct, d(avg_wk_giving-WEEKLY_BUDGET), d(ytd_giving), d(ytd_budget)))
else:
    add("red","Concern","Giving behind budget",
        "Average weekly giving is %s vs the %s/week budget (only %.0f%% of pace) &mdash; about %s/week behind. YTD giving %s trails the %s budgeted pace by %s."
        % (d(avg_wk_giving), d(WEEKLY_BUDGET), budget_pct, d(avg_wk_giving-WEEKLY_BUDGET), d(ytd_giving), d(ytd_budget), d(abs(budget_var))))

# --- Operating surplus / deficit (closed months, apples-to-apples) ---
if ytd_net_closed >= 0:
    add("green","Strength","Operating surplus year-to-date",
        "Through %s, operating income exceeds expense by %s across closed months; the most recent closed month netted %s."
        % (MONTHS12[n_closed-1], d(ytd_net_closed), d(last_closed_net)))
elif last_closed_net >= first2:
    add("amber","Watch","Operating deficit, narrowing",
        "Closed months show a YTD operating deficit of %s, but the monthly shortfall improved from about %s early on to %s most recently &mdash; trending the right way, not yet in the black."
        % (d(ytd_net_closed), d(first2), d(last_closed_net)))
else:
    add("red","Concern","Operating deficit widening",
        "Closed months show a YTD operating deficit of %s, and the monthly shortfall has worsened from about %s early on to %s most recently."
        % (d(ytd_net_closed), d(first2), d(last_closed_net)))

# --- Expense growth vs giving growth (YoY, closed months) ---
if exp_yoy - giv_yoy >= 8:
    add("red","Concern","Expenses outpacing giving",
        "Operating expenses are %s vs 2025 (Jan&ndash;%s) while giving is only %s &mdash; the widening gap is driving the operating shortfall."
        % (_pct(exp_yoy), MONTHS12[n_closed-1], _pct(giv_yoy)))
elif exp_yoy - giv_yoy >= 3:
    add("amber","Watch","Expenses growing faster than giving",
        "Operating expenses are %s vs 2025 (Jan&ndash;%s) while giving is %s &mdash; cost growth is running ahead of receipts."
        % (_pct(exp_yoy), MONTHS12[n_closed-1], _pct(giv_yoy)))
else:
    add("green","Strength","Expense growth contained",
        "Operating expenses are %s vs 2025 (Jan&ndash;%s), in line with or below giving growth (%s) &mdash; costs are not outrunning receipts."
        % (_pct(exp_yoy), MONTHS12[n_closed-1], _pct(giv_yoy)))

# --- Personnel as % of annual budget: 45-55% steady-state, 55-60% growth-investment band, >60% ceiling ---
if pers_pct > 60:
    add("red","Concern","Personnel above growth ceiling",
        "Personnel annualizes to ~%.0f%% of budget &mdash; above the 60%% ceiling set for the growth season (steady-state guideline is 45&ndash;55%%). Even staffing ahead of growth, this is a structural pressure; watch that giving follows and reserves can fund the gap." % pers_pct)
elif pers_pct > 55:
    add("amber","Watch","Personnel elevated &mdash; growth investment",
        "Personnel annualizes to ~%.0f%% of budget &mdash; within the 55&ndash;60%% growth-investment band, above the 45&ndash;55%% steady-state guideline. Expected while staffing ahead of growth; watch that giving and attendance follow." % pers_pct)
elif pers_pct >= 45:
    add("green","Strength","Personnel within guideline",
        "Personnel annualizes to ~%.0f%% of budget &mdash; inside the 45&ndash;55%% steady-state range." % pers_pct)
else:
    add("green","Strength","Personnel below guideline",
        "Personnel annualizes to ~%.0f%% of budget &mdash; below the 45&ndash;55%% range, leaving room in the staffing envelope." % pers_pct)

# --- Facilities as % of annual budget (15-25% guideline) ---
if fac_pct > 30:
    add("red","Concern","Facilities well above guideline",
        "Facilities annualize to ~%.0f%% of budget &mdash; well above the 15&ndash;25%% guideline." % fac_pct)
elif fac_pct > 25:
    add("amber","Watch","Facilities above guideline",
        "Facilities annualize to ~%.0f%% of budget &mdash; above the 15&ndash;25%% guideline; watch upcoming repair/utility cycles." % fac_pct)
elif fac_pct >= 15:
    add("green","Strength","Facilities in healthy range",
        "Facilities annualize to ~%.0f%% of budget &mdash; squarely inside the 15&ndash;25%% guideline." % fac_pct)
else:
    add("green","Strength","Facilities below guideline",
        "Facilities annualize to ~%.0f%% of budget &mdash; below the 15&ndash;25%% guideline." % fac_pct)

# --- Cash runway (months of unrestricted operating cash; 3-mo target) ---
if months_cash >= 3:
    add("green","Strength","Healthy cash runway",
        "Unrestricted cash is about %s &mdash; roughly %.1f months of operating expense, at or above the 3-month target. Total bank %s includes ~%s designated/restricted."
        % (d(unrestricted), months_cash, d(bank), d(RESTR)))
elif months_cash >= 1:
    add("amber","Watch","Lean cash runway",
        "Unrestricted cash is about %s &mdash; roughly %.1f months of operating expense, under the 3-month target. Total bank %s includes ~%s designated/restricted."
        % (d(unrestricted), months_cash, d(bank), d(RESTR)))
else:
    add("red","Concern","Critically low cash runway",
        "Unrestricted cash is about %s &mdash; under one month of operating expense (%.1f mo). Total bank %s is mostly designated/restricted (~%s)."
        % (d(unrestricted), months_cash, d(bank), d(RESTR)))

# --- Donor retention & committed base ---
if retention >= 80 and net_committed >= 0:
    add("green","Strength","Committed base holding",
        "Retention is %.1f%% (%d of %d prior committed units), with %d newly committed vs %d lapsed &mdash; a net change of %+d. Participation is %.0f%% of households."
        % (retention, retained, prior_committed, newly, lapsed, net_committed, participation))
elif retention >= 65:
    add("amber","Watch","Committed base eased",
        "Retention is %.1f%% (%d of %d prior committed units); %d lapsed vs %d newly committed &mdash; a net change of %+d, moving the base from %d to %d. Participation is %.0f%% of households."
        % (retention, retained, prior_committed, lapsed, newly, net_committed, prior_committed, committed, participation))
else:
    add("red","Concern","Committed base declining",
        "Retention has slipped to %.1f%% (%d of %d prior committed units); %d lapsed vs %d newly committed (net %+d). Participation is %.0f%% of households."
        % (retention, retained, prior_committed, lapsed, newly, net_committed, participation))

# --- New givers (positive signal, only when there is activity) ---
if new_donors_week > 0:
    add("green","Strength","New givers this week",
        "%d first-time giver(s) in the last 7 days; %d new donors to 4100 year-to-date." % (new_donors_week, new_donors_year))

# --- Seasonality context — only during the summer dip (Jun-Aug) ---
if RMI in (6,7,8):
    add("green","Strength","Summer seasonality",
        "Summer giving typically dips (Jun&ndash;Aug) before the December year-end surge &mdash; some softness now is consistent with the normal calendar.")

# Most urgent first
_sev_order = {"red":0,"amber":1,"green":2}
insights.sort(key=lambda x: _sev_order[x[0]])

# ---- table/insight builders ----
def cmp_table(arr2026, hist):
    rows=""
    for yr in (2022,2023,2024,2025):
        cells="".join("<td>%s</td>"%d(hist[yr][i]) for i in range(RMI))
        rows+="<tr><th>%d</th>%s<td class='tot'>%s</td></tr>"%(yr,cells,d(sum(hist[yr][:RMI])))
    cells="".join("<td>%s</td>"%d(arr2026[i]) for i in range(RMI))
    rows+="<tr class='cur'><th>2026</th>%s<td class='tot'>%s</td></tr>"%(cells,d(sum(arr2026)))
    return rows

def th_months():
    return "".join("<th>%s</th>"%MONTHS12[i] for i in range(RMI))

def insight_items():
    out=""
    for sev,label,title,body in insights:
        out+=("<div class='ins ins-%s'><div class='ins-h'><span class='dot dot-%s'></span>"
              "<span class='ins-t'>%s</span><span class='ins-tag tag-%s'>%s</span></div>"
              "<div class='ins-b'>%s</div></div>")%(sev,sev,title,sev,label,body)
    return out

def insight_budget():
    py25 = sum(inc[2025][:RMI]); yoy = (ytd_giving/py25-1)*100
    dir_b = "ahead of" if budget_var >= 0 else "behind"
    dir_y = "above" if yoy >= 0 else "below"
    tone = "amber" if budget_var < 0 else "green"
    items=[
      "Giving (4100) of %s is %s %s the %s budgeted pace (%d weeks &times; %s/wk) &mdash; %.0f%% of YTD budget." % (d(ytd_giving), d(abs(budget_var)), dir_b, d(ytd_budget), WEEKS_YTD, d(WEEKLY_BUDGET), budget_pct),
      "That is ~%.0f%% %s the same Jan&ndash;%s period in 2025 (%s), though %s 2026 is still partial (through %s)." % (abs(yoy), dir_y, RMONTH, d(py25), RMONTH, DATA_THROUGH),
    ]
    return "<div style='margin-top:6px'>" + "".join("<div class='ins ins-%s' style='background:#fafbfc'><div class='ins-b' style='margin-top:0'>%s</div></div>"%(tone,x) for x in items) + "</div>"

def insight_opex():
    tone = "green" if op_net >= 0 else "amber"
    if op_net >= 0:
        head = "YTD operating income (%s) exceeds expense (%s) &mdash; an operating surplus of %s. Expenses run %.0f%% of income." % (d(ytd_opinc), d(ytd_opexp), d(op_net), op_ratio)
    else:
        head = "YTD operating expense (%s) exceeds income (%s) &mdash; an operating deficit of %s. Expenses run %.0f%% of income." % (d(ytd_opexp), d(ytd_opinc), d(abs(op_net)), op_ratio)
    ctx = "Against the %s annual budget, income is at %.0f%% and expense at %.0f%% with the year %.0f%% elapsed. Operating figures only (excl. designated); %s 2026 partial through %s." % (d(ANNUAL_BUDGET), opinc_bar, exp_bar, pace, RMONTH, DATA_THROUGH)
    items=[head, ctx]
    return "<div style='margin-top:6px'>" + "".join("<div class='ins ins-%s' style='background:#fafbfc'><div class='ins-b' style='margin-top:0'>%s</div></div>"%(tone,x) for x in items) + "</div>"

def card_over_rows():
    if not card_over: return "<tr><td colspan='5' class='none'>None over $500 this week</td></tr>"
    return "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td class='ldesc'>%s</td><td class='amt'>%s</td></tr>"%(r[0],r[1],r[2],r[3] or "&mdash;",dc(r[4])) for r in card_over)

def bills_rows():
    if not bills_paid: return "<tr><td colspan='4' class='none'>No bills paid this week</td></tr>"
    return "".join("<tr><td>%s</td><td>%s</td><td class='ldesc'>%s</td><td class='amt'>%s</td></tr>"%(r[0],r[1],r[2] or "&mdash;",dc(r[3])) for r in bills_paid)

ds = lambda a: json.dumps(a)
labels = json.dumps(MONTHS12)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>MCC Finance Team Dashboard</title>
<link rel="icon" type="image/png" href="favicon.png">
<link rel="apple-touch-icon" href="favicon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{{--slate:#343A44;--bg:#F2F2F2;--card:#fff;--ink:#23272e;--muted:#6b7280;--line:#e3e5ea;--red:#DC2626;--green:#2F8F5B;--amber:#C8842A;--chart:#4C5564;}}
*{{box-sizing:border-box;}}
body{{margin:0;background:var(--bg);font-family:'Lato',system-ui,Arial,sans-serif;color:var(--ink);}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 28px;}}
header{{position:relative;background:var(--slate);overflow:hidden;}}
header::before{{content:"";position:absolute;inset:0;background:url('https://storage1.snappages.site/VCFHFT/assets/images/21064405_1024x1024_2500.png');background-size:620px;opacity:.065;}}
.hdr-inner{{position:relative;max-width:1180px;margin:0 auto;padding:26px 28px;display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap;}}
.brand{{display:flex;align-items:center;gap:18px;}}
.brand img{{height:42px;}}
header h1{{font-weight:900;text-transform:uppercase;letter-spacing:-.02em;color:#fff;margin:0;font-size:26px;line-height:1.05;}}
header .sub{{text-transform:uppercase;letter-spacing:.1em;font-size:11px;font-weight:700;color:#fff;opacity:.72;margin-top:5px;}}
.hdr-meta{{text-align:right;color:#fff;opacity:.85;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;line-height:1.6;}}
section{{padding:26px 0 4px;}}
h2{{font-weight:900;text-transform:uppercase;letter-spacing:.01em;color:var(--slate);font-size:18px;margin:18px 0 14px;}}
.eyebrow{{font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-size:11px;}}
.grid{{display:grid;gap:16px;}}
.g4{{grid-template-columns:repeat(4,1fr);}}
.g5{{grid-template-columns:repeat(5,1fr);}}
.g6{{grid-template-columns:repeat(6,1fr);}}
@media(max-width:900px){{.g4,.g5,.g6{{grid-template-columns:repeat(2,1fr);}}}}
@media(max-width:560px){{.g4,.g5,.g6{{grid-template-columns:1fr;}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 18px 16px;box-shadow:0 1px 2px rgba(20,24,31,.04);}}
.kpi-l{{font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-size:11px;margin-bottom:8px;}}
.kpi-n{{font-weight:900;color:var(--slate);font-size:30px;line-height:1;}}
.kpi-s{{color:var(--muted);font-size:12px;margin-top:7px;line-height:1.4;}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;box-shadow:0 1px 2px rgba(20,24,31,.04);}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:14px;}}
.legend span{{display:inline-flex;align-items:center;gap:6px;}}
.sw{{width:11px;height:11px;border-radius:3px;display:inline-block;}}
.ins{{border-left:4px solid var(--line);padding:11px 14px;margin:9px 0;background:#fafbfc;border-radius:0 8px 8px 0;}}
.ins-red{{border-left-color:var(--red);}}.ins-amber{{border-left-color:var(--amber);}}.ins-green{{border-left-color:var(--green);}}
.ins-h{{display:flex;align-items:center;gap:9px;}}
.dot{{width:9px;height:9px;border-radius:50%;}}.dot-red{{background:var(--red);}}.dot-amber{{background:var(--amber);}}.dot-green{{background:var(--green);}}
.ins-t{{font-weight:900;color:var(--slate);font-size:13.5px;text-transform:uppercase;letter-spacing:.02em;}}
.ins-tag{{margin-left:auto;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;padding:2px 8px;border-radius:20px;color:#fff;}}
.tag-red{{background:var(--red);}}.tag-amber{{background:var(--amber);}}.tag-green{{background:var(--green);}}
.ins-b{{color:var(--ink);font-size:13px;line-height:1.5;margin-top:5px;}}
.cap{{color:var(--muted);font-size:11.5px;line-height:1.5;margin-top:12px;}}
.stat4{{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-bottom:16px;}}
.stat4 div{{padding:14px 16px;border-right:1px solid var(--line);}}
.stat4 div:last-child{{border-right:none;}}
.stat-l{{font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);font-size:10.5px;}}
.stat-n{{font-weight:900;color:var(--slate);font-size:22px;margin-top:6px;}}
.neg{{color:var(--red);}}
.bar-wrap{{margin:14px 0;}}
.bar-row{{display:flex;align-items:center;gap:12px;margin:9px 0;}}
.bar-lab{{width:150px;font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);}}
.bar-track{{flex:1;position:relative;height:20px;background:#eef0f3;border-radius:6px;overflow:hidden;}}
.bar-fill{{position:absolute;left:0;top:0;bottom:0;border-radius:6px;}}
.bar-pace{{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--slate);}}
.bar-val{{width:150px;text-align:right;font-weight:900;color:var(--slate);font-size:13px;}}
.chartbox{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;box-shadow:0 1px 2px rgba(20,24,31,.04);}}
.callout{{color:var(--muted);font-size:12.5px;margin:-6px 0 14px;}}
table.cmp{{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;}}
table.cmp th,table.cmp td{{padding:9px 10px;text-align:right;border-bottom:1px solid var(--line);}}
table.cmp thead th{{background:var(--slate);color:#fff;font-weight:700;text-transform:uppercase;letter-spacing:.05em;font-size:11px;}}
table.cmp thead th:first-child,table.cmp tbody th{{text-align:left;}}
table.cmp tbody th{{font-weight:900;color:var(--slate);}}
table.cmp tr.cur{{background:#eef2f6;}}
table.cmp tr.cur th,table.cmp tr.cur td{{font-weight:900;}}
table.cmp td.tot{{border-left:1px solid var(--line);font-weight:900;color:var(--slate);}}
table.ramp{{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;}}
table.ramp th,table.ramp td{{padding:9px 12px;border-bottom:1px solid var(--line);text-align:left;}}
table.ramp thead th{{background:var(--slate);color:#fff;font-weight:700;text-transform:uppercase;letter-spacing:.05em;font-size:11px;}}
table.ramp td.amt{{text-align:right;font-weight:700;}}
table.ramp td.ldesc{{color:var(--muted);}}
table.ramp td.none{{text-align:center;color:var(--muted);font-style:italic;}}
footer{{margin-top:34px;padding:26px 0 36px;border-top:1px solid var(--line);color:var(--muted);font-size:12px;text-align:center;line-height:1.7;}}
footer a{{color:var(--slate);font-weight:700;text-decoration:none;}}
</style>
</head>
<body>
<header>
  <div class="hdr-inner">
    <div class="brand">
      <img src="https://storage1.snappages.site/VCFHFT/assets/images/22645050_962x358_500.png" alt="Maple City Chapel">
      <div>
        <h1>Finance Team Dashboard</h1>
        <div class="sub">General Fund &middot; Operating figures only (excl. designated)</div>
      </div>
    </div>
    <div class="hdr-meta">Week of {RUN_DATE}<br>Data through {DATA_THROUGH}</div>
  </div>
</header>
<div class="wrap">

<section>
  <div class="grid g6">
    <div class="card"><div class="kpi-l">Last Week's Giving</div><div class="kpi-n">{d(last_week_giving)}</div><div class="kpi-s">Week of {WEEK_LABEL} &middot; QBO 4100</div></div>
    <div class="card"><div class="kpi-l">{RMONTH} Giving</div><div class="kpi-n">{d(current_giving)}</div><div class="kpi-s">Month to date (through {DATA_THROUGH})</div></div>
    <div class="card"><div class="kpi-l">YTD Giving</div><div class="kpi-n">{d(ytd_giving)}</div><div class="kpi-s">Jan&ndash;{RMONTH} &middot; sum of 4100</div></div>
    <div class="card"><div class="kpi-l">YTD Operating Income</div><div class="kpi-n">{d(ytd_opinc)}</div><div class="kpi-s">Jan&ndash;{RMONTH} &middot; total operating revenue</div></div>
    <div class="card"><div class="kpi-l">YTD Operating Expense</div><div class="kpi-n">{d(ytd_opexp)}</div><div class="kpi-s">Jan&ndash;{RMONTH} &middot; total operating expense</div></div>
    <div class="card"><div class="kpi-l">Bank Balance</div><div class="kpi-n">{d(bank)}</div><div class="kpi-s">Unrestricted: {d(unrestricted)} &middot; {months_cash:.1f} mo. cash</div></div>
  </div>
</section>

<section>
  <h2>Key Insights &amp; Watch Items</h2>
  <div class="panel">
    <div class="legend"><span><span class="sw" style="background:var(--green)"></span>Strength</span><span><span class="sw" style="background:var(--amber)"></span>Watch</span><span><span class="sw" style="background:var(--red)"></span>Concern</span></div>
    {insight_items()}
    <div class="cap">Internal trend analysis from QBO, Planning Center &amp; Ramp through {DATA_THROUGH}. Benchmarks (personnel 45&ndash;55%, facilities 15&ndash;25%, 1&ndash;3 months cash) are general guidelines &mdash; confirm major decisions with your CPA or finance committee.</div>
  </div>
</section>

<section>
  <h2>YTD Giving vs Budget</h2>
  <div class="panel">
    <div class="stat4">
      <div><div class="stat-l">YTD Actual Giving</div><div class="stat-n">{d(ytd_giving)}</div></div>
      <div><div class="stat-l">YTD Budget ({WEEKS_YTD} wks)</div><div class="stat-n">{d(ytd_budget)}</div></div>
      <div><div class="stat-l">Variance</div><div class="stat-n neg">{d(budget_var)}</div></div>
      <div><div class="stat-l">% of YTD Budget</div><div class="stat-n">{budget_pct:.0f}%</div></div>
    </div>
    <div class="bar-wrap">
      <div class="bar-row"><div class="bar-lab">Giving vs Annual</div><div class="bar-track"><div class="bar-fill" style="width:{inc_bar:.1f}%;background:var(--green)"></div><div class="bar-pace" style="left:{pace:.1f}%"></div></div><div class="bar-val">{d(ytd_giving)} &middot; {inc_bar:.0f}%</div></div>
      <div class="bar-row"><div class="bar-lab">Expense vs Annual</div><div class="bar-track"><div class="bar-fill" style="width:{exp_bar:.1f}%;background:var(--chart)"></div><div class="bar-pace" style="left:{pace:.1f}%"></div></div><div class="bar-val">{d(ytd_opexp)} &middot; {exp_bar:.0f}%</div></div>
    </div>
    {insight_budget()}
  </div>
</section>

<section>
  <h2>Monthly Giving &mdash; 2026 vs Prior Years</h2>
  <div class="callout">Giving Jan&ndash;{MONTHS12[n_closed-1]} is up ~{giv_yoy:.0f}% vs 2025; {RMONTH} shown partial (through {DATA_THROUGH}).</div>
  <div class="chartbox"><canvas id="givingChart" height="120"></canvas></div>
</section>

<section>
  <h2>Giving Health</h2>
  <div class="grid g4">
    <div class="card"><div class="kpi-l">Committed Giving Units</div><div class="kpi-n">{committed}</div><div class="kpi-s">Gave &gt;$200 to 4100 &middot; trailing 12 mo</div></div>
    <div class="card"><div class="kpi-l">Participation</div><div class="kpi-n">{participation:.0f}%</div><div class="kpi-s">{committed} of {households} active households</div></div>
    <div class="card"><div class="kpi-l">New Donors to 4100</div><div class="kpi-n">{new_donors_year}</div><div class="kpi-s">This year</div></div>
    <div class="card"><div class="kpi-l">New Donors This Week</div><div class="kpi-n">{new_donors_week}</div><div class="kpi-s">First-time givers, last 7 days</div></div>
  </div>
</section>

<section>
  <h2>Donor Retention</h2>
  <div class="grid g4">
    <div class="card"><div class="kpi-l">Retained</div><div class="kpi-n" style="color:var(--green)">{retained}</div><div class="kpi-s">Committed both 12-mo windows</div></div>
    <div class="card"><div class="kpi-l">Lapsed</div><div class="kpi-n" style="color:var(--red)">{lapsed}</div><div class="kpi-s">Committed prior, not now</div></div>
    <div class="card"><div class="kpi-l">Newly Committed</div><div class="kpi-n">{newly}</div><div class="kpi-s">New committed this window</div></div>
    <div class="card"><div class="kpi-l">Retention Rate</div><div class="kpi-n" style="color:var(--green)">{retention:.1f}%</div><div class="kpi-s">of {prior_committed} prior committed units</div></div>
  </div>
  <div class="cap">Committed giving unit = gave &gt;$200 cumulatively to Tithe/Offering (trailing 12 mo). Rolling 12 months vs. the prior 12; net committed change {newly-lapsed}. Live from Planning Center Giving.</div>
</section>

<section>
  <h2>Operating Income vs Expense</h2>
  <div class="panel">
    <div class="stat4">
      <div><div class="stat-l">YTD Operating Income</div><div class="stat-n">{d(ytd_opinc)}</div></div>
      <div><div class="stat-l">YTD Operating Expense</div><div class="stat-n">{d(ytd_opexp)}</div></div>
      <div><div class="stat-l">Operating Surplus / (Deficit)</div><div class="stat-n {'neg' if op_net<0 else ''}">{d(op_net)}</div></div>
      <div><div class="stat-l">Expense-to-Income</div><div class="stat-n">{op_ratio:.0f}%</div></div>
    </div>
    <div class="bar-wrap">
      <div class="bar-row"><div class="bar-lab">Income vs Annual</div><div class="bar-track"><div class="bar-fill" style="width:{opinc_bar:.1f}%;background:var(--green)"></div><div class="bar-pace" style="left:{pace:.1f}%"></div></div><div class="bar-val">{d(ytd_opinc)} &middot; {opinc_bar:.0f}%</div></div>
      <div class="bar-row"><div class="bar-lab">Expense vs Annual</div><div class="bar-track"><div class="bar-fill" style="width:{exp_bar:.1f}%;background:var(--chart)"></div><div class="bar-pace" style="left:{pace:.1f}%"></div></div><div class="bar-val">{d(ytd_opexp)} &middot; {exp_bar:.0f}%</div></div>
    </div>
    {insight_opex()}
    <div class="cap">Operating income = total operating revenue (4000s); operating expense = total expenditures (5000&ndash;6000s). Excludes designated/restricted funds and loan service. Year pace marker shows {WEEKS_YTD} of 52 weeks elapsed.</div>
  </div>
</section>

<section>
  <h2>Operating Income Comparison</h2>
  <table class="cmp"><thead><tr><th>Year</th>{th_months()}<th>Total</th></tr></thead>
  <tbody>{cmp_table(oi26, inc)}</tbody></table>
  <div class="cap">2022&ndash;2025 from PowerChurch; 2026 from QuickBooks Online. {RMONTH} 2026 is partial (through {DATA_THROUGH}).</div>
</section>

<section>
  <h2>Operating Expense &mdash; 2026 vs Prior Years</h2>
  <div class="callout">Operating expenses Jan&ndash;{MONTHS12[n_closed-1]} are up ~{exp_yoy:.0f}% vs 2025; {RMONTH} shown partial (through {DATA_THROUGH}).</div>
  <div class="chartbox"><canvas id="expenseChart" height="120"></canvas></div>
</section>

<section>
  <h2>Operating Expense Comparison</h2>
  <table class="cmp"><thead><tr><th>Year</th>{th_months()}<th>Total</th></tr></thead>
  <tbody>{cmp_table(oe26, exp)}</tbody></table>
  <div class="cap">2022&ndash;2025 from PowerChurch; 2026 from QuickBooks Online. {RMONTH} 2026 is partial (through {DATA_THROUGH}).</div>
</section>

<section>
  <h2>Campaign Loan &mdash; First State Bank</h2>
  <div class="grid g5">
    <div class="card"><div class="kpi-l">Loan Balance</div><div class="kpi-n">{d(loan_balance)}</div><div class="kpi-s">QBO 2100 First State Loan &middot; as of {DATA_THROUGH}</div></div>
    <div class="card"><div class="kpi-l">Interest Rate</div><div class="kpi-n">{loan_rate}</div><div class="kpi-s">Fixed</div></div>
    <div class="card"><div class="kpi-l">Monthly Payment</div><div class="kpi-n">{dc(loan_pay)}</div><div class="kpi-s">Principal + interest</div></div>
    <div class="card"><div class="kpi-l">Monthly Principal</div><div class="kpi-n">{dc(loan_prin)}</div><div class="kpi-s">Reduces balance</div></div>
    <div class="card"><div class="kpi-l">Monthly Interest</div><div class="kpi-n">{dc(loan_int)}</div><div class="kpi-s">Cost of debt</div></div>
  </div>
  <div class="cap">Balance live from QuickBooks (2100 First State Loan); rate, payment, principal &amp; interest from the ONE Campaign Loan Info sheet. Loan service is a designated/capital obligation, separate from the operating figures above.</div>
</section>

<section>
  <h2>Ramp Activity</h2>
  <div class="grid g4">
    <div class="card"><div class="kpi-l">Card Spend &middot; {RMONTH} MTD</div><div class="kpi-n">{d(card_mtd)}</div><div class="kpi-s">{card_mtd_n} transactions</div></div>
    <div class="card"><div class="kpi-l">Card Spend &middot; Past 7 Days</div><div class="kpi-n">{d(card_7d)}</div><div class="kpi-s">{card_7d_n} transactions</div></div>
    <div class="card"><div class="kpi-l">Bill Pay Paid &middot; {RMONTH} MTD</div><div class="kpi-n">{d(ap_paid_mtd)}</div><div class="kpi-s">{ap_paid_n} bills paid</div></div>
    <div class="card"><div class="kpi-l">Bill Pay Outstanding</div><div class="kpi-n">{d(ap_out)}</div><div class="kpi-s">{ap_open_n} open bills</div></div>
  </div>
  <h2 style="font-size:14px;margin-top:22px;">Card Transactions over $500 &middot; Past 7 Days</h2>
  <table class="ramp"><thead><tr><th>Date</th><th>Merchant</th><th>Cardholder</th><th>Memo</th><th style="text-align:right">Amount</th></tr></thead>
  <tbody>{card_over_rows()}</tbody></table>
  <h2 style="font-size:14px;margin-top:22px;">Bills Paid &middot; Past 7 Days</h2>
  <table class="ramp"><thead><tr><th>Paid</th><th>Vendor</th><th>Description</th><th style="text-align:right">Amount</th></tr></thead>
  <tbody>{bills_rows()}</tbody></table>
  <div class="cap">Live from Ramp &middot; card spend (all cardholders, incl. pending) and Bill Pay / accounts payable. Card spend posts to QBO Ramp Card &amp; expense accounts.</div>
</section>

<footer>
  MCC Finance Team &middot; Prepared {RUN_WEEKDAY}, {RUN_DATE} &middot; <a href="https://metrics.maplecity.church">metrics.maplecity.church</a><br>
  2022&ndash;2025: PowerChurch &middot; 2026: QuickBooks Online &middot; Giving: QBO 4100 &middot; Donors &amp; retention: Planning Center Giving &middot; Card spend &amp; bills: Ramp
</footer>
</div>

<script>
Chart.defaults.font.family="'Lato',system-ui,Arial,sans-serif";
Chart.defaults.color="#6b7280";
const LB={labels};
function mk(id,d2024,d2025,d2026,lab){{
 new Chart(document.getElementById(id),{{
  data:{{labels:LB,datasets:[
   {{type:'line',label:'2024 '+lab,data:d2024,borderColor:'#C8842A',backgroundColor:'#C8842A',borderDash:[6,4],borderWidth:2,pointRadius:0,tension:.3,order:1}},
   {{type:'line',label:'2025 '+lab,data:d2025,borderColor:'#2F8F5B',backgroundColor:'#2F8F5B',borderWidth:2,pointRadius:0,tension:.3,order:2}},
   {{type:'bar',label:'2026 '+lab,data:d2026,backgroundColor:'#343A44',order:3}}
  ]}},
  options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},
   plugins:{{legend:{{position:'top',labels:{{usePointStyle:true,boxWidth:8,font:{{size:12,weight:'700'}}}}}},
    tooltip:{{itemSort:(a,b)=>b.datasetIndex-a.datasetIndex,callbacks:{{label:(c)=>c.dataset.label+': '+(c.parsed.y==null?'—':'$'+c.parsed.y.toLocaleString())}}}}}},
   scales:{{y:{{ticks:{{callback:(v)=>'$'+(v/1000)+'k'}},grid:{{color:'#eef0f3'}}}},x:{{grid:{{display:false}}}}}}
  }}
 }});
}}
mk('givingChart',{ds(giving_2024)},{ds(giving_2025)},{ds(giving_2026)},'Giving');
mk('expenseChart',{ds(exp_2024)},{ds(exp_2025)},{ds(exp_2026)},'Expense');
</script>
</body>
</html>"""

out = os.path.join(BASE, "finance-team.html")
with open(out, "w") as f:
    f.write(html)
print("wrote", out, len(html), "bytes  | YTD giving", d(ytd_giving), "| bank", d(bank), "| committed", committed)
