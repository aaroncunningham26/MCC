#!/usr/bin/env python3
"""
MCC Connections dashboard renderer.

Reads data/connections.json and writes connections.html.

Data layers:
  attendance (weekly)  -- Google Sheet '2026' tab, weekly total attendance.
  pco (live current)   -- Planning Center saved Lists (open-month snapshot).
  history (monthly YoY)-- 'MCC Connection KPMs' Google Sheet, read via the Drive
                          connector by the weekly refresh job.

Weekly job: overwrite data/connections.json, then run: python3 build_connections.py
"""
import json, os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE, "data", "connections.json")) as f:
    D = json.load(f)

M = D["meta"]; P = D["pco"]; A = D["attendance"]; H = D["history"]
RUN_DATE = M["run_date"]; DATA_THROUGH = M["data_through"]
PREV_MONTH_LABEL = M["prev_month_label"]
HIST_MONTH = M["history_through_month"]; HIST_LABEL = M["history_through_label"]
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

# ---- Attendance (weekly series) ----
weekly = A["weekly"]
totals = [t for _, t in weekly]
dates  = [datetime.strptime(d, "%Y-%m-%d") for d, _ in weekly]
weekend = totals[-1]; weekend_date = dates[-1].strftime("%b %-d")
prev_weekend = totals[-2] if len(totals) > 1 else None
avg_weekly_ytd = round(sum(totals) / len(totals))
mov6 = round(sum(totals[-6:]) / min(6, len(totals)))
PM = M["prev_month_num"]
_pm = [t for dt, t in zip(dates, totals) if dt.month == PM]
avg_weekly_prev = round(sum(_pm) / len(_pm)) if _pm else None
_pm2 = [t for dt, t in zip(dates, totals) if dt.month == PM - 1]
avg_weekly_prev2 = round(sum(_pm2) / len(_pm2)) if _pm2 else None

# ---- PCO roster (live) ----
active = P["active_profiles"]; students = P["student_profiles"]; kids = P["kid_profiles"]
adults = active - students - kids
households = P["households"]
group_members = P["group_members"]; serving_sun = P["serving_sundays"]; serving_any = P["serving_anywhere"]
kids_ci = P["kids_checkins"]; student_ci = P["student_checkins"]
new_guests = P["new_guests_month"]; starting_point_live = P["starting_point"]

# ---- History-derived YTD / by-year ----
def last_recorded(arr):
    v = [x for x in arr if x is not None]
    return v[-1] if v else None
prof = H["profile_monthly_2026"]
active_apr = last_recorded(prof["active"]); adults_apr = last_recorded(prof["adults"])
students_apr = last_recorded(prof["students"]); kids_apr = last_recorded(prof["kids"])
hh_apr = last_recorded(prof["households"])
gs = H["groups_serving_2026"]
group_apr = last_recorded(gs["group_members"]); serving_sun_apr = last_recorded(gs["serving_sundays"])
baptisms_ytd = H["baptisms_by_year"].get("2026")
starting_ytd = H["starting_point_by_year"].get("2026")
cb2026 = [x for x in H["connect_breakfast_monthly"]["2026"] if x is not None]
connect_ytd = sum(cb2026) if cb2026 else None
guests_ytd = sum(x for x in H["guests_monthly"]["2026"] if x is not None)

def n(v):
    return "&mdash;" if v is None else "{:,}".format(v)

# ---- Delta chip (vs a baseline); up = green, down = red ----
def delta(cur, base, label):
    if cur is None or base is None:
        return ""
    d = cur - base
    if d == 0:
        return '<span class="delta flat">&plusmn;0 %s</span>' % label
    arrow = "&#9650;" if d > 0 else "&#9660;"
    cls = "up" if d > 0 else "down"
    return '<span class="delta %s">%s %s %s</span>' % (cls, arrow, ("+" if d > 0 else "&minus;") + f"{abs(d):,}", label)

# ---- Takeaways ----
group_pct = round(group_members / adults * 100) if adults else 0
peak = max(totals); peak_date = dates[totals.index(peak)].strftime("%b %-d")
def yr_avg(arr):
    v = [x for x in arr if x is not None]; return round(sum(v)/len(v)) if v else None
att25 = yr_avg(H["attendance_monthly"]["2025"])
takeaways = [
    ("green", "Weekend attendance is healthy &mdash; the YTD weekly average is <strong>%s</strong> (6-week moving average <strong>%s</strong>). %s was the year's strongest week at %s." % (f"{avg_weekly_ytd:,}", f"{mov6:,}", peak_date, f"{peak:,}")),
    ("blue", "Year over year, the 2026 monthly attendance is tracking <strong>above</strong> 2025 (2025 averaged %s/week) and well above 2021&ndash;2023." % (f"{att25:,}" if att25 else "&mdash;")),
    ("green", "Discipleship base is strong &mdash; <strong>%s adults</strong> are in a group (~%d%% of adults) and <strong>%s</strong> serve on Sundays." % (f"{group_members:,}", group_pct, f"{serving_sun:,}")),
    ("blue", "So far in 2026: <strong>%s</strong> baptisms, <strong>%s</strong> through Starting Point, and <strong>%s</strong> new Sunday guests (YTD)." % (baptisms_ytd, starting_ytd, f"{guests_ytd:,}")),
]
def takeaway_items():
    dot = {"green":"dot-green","amber":"dot-amber","red":"dot-red","blue":"dot-blue"}
    return "".join('<li><span class="dot %s"></span><span>%s</span></li>' % (dot[s], b) for s, b in takeaways)

# ---- Chart palette for YoY ----
YOY_COLORS = {"2021":"#C9CED6","2022":"#AEB6C2","2023":"#8899AA","2024":"#C8842A","2025":"#2F8F5B","2026":"#343A44"}
def yoy_datasets(series):
    out = []
    for yr in sorted(series.keys()):
        bold = (yr == "2026")
        out.append({
            "label": yr, "data": series[yr], "borderColor": YOY_COLORS.get(yr, "#8899AA"),
            "backgroundColor": YOY_COLORS.get(yr, "#8899AA"),
            "borderWidth": 3 if bold else 1.8, "pointRadius": 3 if bold else 0,
            "tension": 0.3, "spanGaps": False, "borderDash": [] if bold or yr == "2025" else ([4,3] if yr in ("2021","2022") else [])
        })
    return out

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>MCC Connections Dashboard</title>
<link rel="icon" type="image/png" href="favicon.png">
<link rel="apple-touch-icon" href="favicon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap" rel="stylesheet">
<style>
  :root {{ --slate:#343A44; --bg:#F2F2F2; --card:#fff; --ink:#23272e; --muted:#6b7280;
    --line:#e3e5ea; --red:#DC2626; --green:#2F8F5B; --amber:#C8842A; --chart:#4C5564; }}
  *,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Lato',system-ui,-apple-system,Arial,sans-serif; background:var(--bg); color:var(--ink); font-size:15px; line-height:1.6; }}
  .mcc-header {{ position:relative; overflow:hidden; background:var(--slate); color:#fff; }}
  .mcc-header-inner {{ position:relative; max-width:1180px; margin:0 auto; padding:26px 30px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:14px; }}
  .mcc-header::before {{ content:""; position:absolute; inset:0; background:url('https://storage1.snappages.site/VCFHFT/assets/images/21064405_1024x1024_2500.png'); background-size:620px; opacity:.065; pointer-events:none; }}
  .mcc-header .brand {{ display:flex; align-items:center; gap:20px; position:relative; }}
  .mcc-header .logo {{ height:42px; width:auto; display:block; }}
  .mcc-header .back {{ color:#aeb6c2; font-size:11px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; text-decoration:none; display:inline-block; margin-bottom:5px; }}
  .mcc-header .back:hover {{ color:#fff; }}
  .mcc-header h1 {{ font-size:27px; font-weight:900; text-transform:uppercase; letter-spacing:-.02em; line-height:1; }}
  .mcc-header .sub {{ font-size:11.5px; font-weight:400; letter-spacing:.05em; text-transform:uppercase; opacity:.72; margin-top:6px; }}
  .mcc-header .right {{ position:relative; font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; opacity:.8; text-align:right; line-height:1.7; }}
  .page {{ max-width:1180px; margin:0 auto; padding:28px 30px 60px; }}
  .section-label {{ font-size:11px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin-bottom:12px; margin-top:32px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
  .card {{ background:var(--card); border-radius:10px; padding:18px 20px; border:1px solid var(--line); box-shadow:0 1px 4px rgba(20,30,60,.05); }}
  .card .label {{ font-size:11px; color:var(--muted); font-weight:700; text-transform:uppercase; letter-spacing:.08em; margin-bottom:6px; }}
  .card .value {{ font-size:26px; font-weight:900; color:var(--slate); letter-spacing:-0.5px; }}
  .card .sub {{ font-size:12px; margin-top:4px; color:var(--muted); }}
  .card .sub.green {{ color:var(--green); }} .card .sub.yellow {{ color:var(--amber); }}
  .card.top-green {{ border-top:4px solid var(--green); }} .card.top-blue {{ border-top:4px solid var(--slate); }}
  .card.top-amber {{ border-top:4px solid var(--amber); }}
  .delta {{ display:inline-block; font-size:11px; font-weight:700; margin-top:5px; }}
  .delta.up {{ color:var(--green); }} .delta.down {{ color:var(--red); }} .delta.flat {{ color:var(--muted); }}
  .profile-strip {{ display:grid; grid-template-columns:repeat(5,1fr); background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; box-shadow:0 1px 4px rgba(20,30,60,.05); }}
  .profile-strip .cell {{ padding:18px 16px; text-align:center; border-right:1px solid var(--line); }}
  .profile-strip .cell:last-child {{ border-right:none; }}
  .profile-strip .cell .plabel {{ font-size:11px; color:var(--green); font-weight:700; text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px; }}
  .profile-strip .cell .pval {{ font-size:24px; font-weight:900; color:var(--slate); letter-spacing:-0.5px; }}
  .profile-strip .cell .pdelta {{ font-size:10.5px; font-weight:700; margin-top:3px; }}
  @media (max-width:720px) {{ .profile-strip {{ grid-template-columns:repeat(2,1fr); }} .profile-strip .cell {{ border-bottom:1px solid var(--line); }} }}
  .insights {{ background:#F4F5F7; border:1px solid var(--line); border-radius:10px; padding:20px 24px; margin-top:6px; }}
  .insights h2 {{ font-size:13px; font-weight:900; text-transform:uppercase; letter-spacing:.08em; color:var(--slate); margin-bottom:12px; }}
  .insights ul {{ list-style:none; }}
  .insights ul li {{ padding:8px 0; border-bottom:1px solid var(--line); font-size:13px; color:var(--ink); display:flex; align-items:flex-start; gap:10px; line-height:1.55; }}
  .insights ul li:last-child {{ border-bottom:none; }}
  .dot {{ width:8px; height:8px; border-radius:50%; margin-top:5px; flex-shrink:0; }}
  .dot-green {{ background:var(--green); }} .dot-red {{ background:var(--red); }} .dot-amber {{ background:var(--amber); }} .dot-blue {{ background:var(--slate); }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
  @media (max-width:820px) {{ .grid-2 {{ grid-template-columns:1fr; }} }}
  .chart-card {{ background:var(--card); border-radius:10px; padding:22px 22px 18px; border:1px solid var(--line); margin-bottom:14px; box-shadow:0 1px 4px rgba(20,30,60,.05); }}
  .chart-card h2 {{ font-size:15px; font-weight:900; text-transform:uppercase; letter-spacing:-.01em; color:var(--slate); margin-bottom:4px; }}
  .chart-card .chart-sub {{ font-size:13px; color:var(--muted); margin-bottom:16px; }}
  .chart-wrap {{ position:relative; width:100%; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin-bottom:14px; }}
  .legend-item {{ display:flex; align-items:center; gap:6px; font-size:12px; color:var(--muted); font-weight:700; }}
  .legend-dot {{ width:10px; height:10px; border-radius:2px; flex-shrink:0; }}
  .section-divider {{ margin:36px 0 20px; padding-bottom:10px; border-bottom:2px solid var(--slate); display:flex; align-items:center; gap:10px; }}
  .section-divider h2 {{ font-size:15px; font-weight:900; text-transform:uppercase; letter-spacing:-.01em; color:var(--slate); }}
  .section-divider .badge {{ font-size:11px; font-weight:700; color:var(--muted); background:#F0F2F5; padding:2px 8px; border-radius:4px; text-transform:uppercase; letter-spacing:.06em; }}
  .mcc-footer {{ color:var(--muted); font-size:11.5px; margin-top:44px; line-height:1.8; text-align:center; }}
</style>
</head>
<body>
<header class="mcc-header">
  <div class="mcc-header-inner">
  <div class="brand">
    <img class="logo" src="https://storage1.snappages.site/VCFHFT/assets/images/22645050_962x358_500.png" alt="Maple City Chapel">
    <div>
      <a class="back" href="care-connections.html">&larr; Care &amp; Connections</a>
      <h1>MCC Connections</h1>
      <div class="sub">Attendance, Guests, Groups &amp; Next Steps</div>
    </div>
  </div>
  <div class="right">Attendance through {DATA_THROUGH}<br>Profiles &amp; groups: live &middot; history to {HIST_LABEL}</div>
  </div>
</header>

<div class="page">

  <div class="section-label">Weekend attendance &mdash; updated weekly</div>
  <div class="cards">
    <div class="card top-blue"><div class="label">Weekend Attendance</div><div class="value">{weekend:,}</div><div class="sub">Week of {weekend_date}</div>{delta(weekend, prev_weekend, "vs prior week")}</div>
    <div class="card top-blue"><div class="label">6-Week Moving Avg</div><div class="value">{mov6:,}</div><div class="sub">Rolling 6-week average</div></div>
    <div class="card top-green"><div class="label">Avg Weekly Att. YTD</div><div class="value">{avg_weekly_ytd:,}</div><div class="sub green">Year-to-date average</div></div>
    <div class="card top-blue"><div class="label">Avg Weekly Att. &mdash; {PREV_MONTH_LABEL.split()[0]}</div><div class="value">{n(avg_weekly_prev)}</div><div class="sub">Close of {PREV_MONTH_LABEL.split()[0]}</div>{delta(avg_weekly_prev, avg_weekly_prev2, "vs prior month")}</div>
  </div>

  <div class="section-label">Weekly attendance trend &mdash; 2026</div>
  <div class="chart-card">
    <h2>Weekly attendance with 6-week moving average</h2>
    <p class="chart-sub">Each Sunday's total attendance this year, with the trailing 6-week moving average.</p>
    <div class="legend">
      <span class="legend-item"><span class="legend-dot" style="background:#8899AA;"></span>Weekly attendance</span>
      <span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>6-week moving average</span>
    </div>
    <div class="chart-wrap" style="height:240px;"><canvas id="attWeekly"></canvas></div>
  </div>

  <div class="section-label">Planning Center profile data &mdash; live, vs last recorded ({HIST_LABEL})</div>
  <div class="profile-strip">
    <div class="cell"><div class="plabel">Active Profiles</div><div class="pval">{active:,}</div><div class="pdelta">{delta(active, active_apr, "vs "+HIST_LABEL.split()[0])}</div></div>
    <div class="cell"><div class="plabel">Adults</div><div class="pval">{adults:,}</div><div class="pdelta">{delta(adults, adults_apr, "vs "+HIST_LABEL.split()[0])}</div></div>
    <div class="cell"><div class="plabel">Students</div><div class="pval">{students:,}</div><div class="pdelta">{delta(students, students_apr, "vs "+HIST_LABEL.split()[0])}</div></div>
    <div class="cell"><div class="plabel">Kids</div><div class="pval">{kids:,}</div><div class="pdelta">{delta(kids, kids_apr, "vs "+HIST_LABEL.split()[0])}</div></div>
    <div class="cell"><div class="plabel">Unique Households</div><div class="pval">{households:,}</div><div class="pdelta">{delta(households, hh_apr, "vs "+HIST_LABEL.split()[0])}</div></div>
  </div>

  <div class="section-label">Key takeaways</div>
  <div class="insights"><h2>What this data is telling us</h2><ul>{takeaway_items()}</ul></div>

  <div class="section-divider"><h2>Groups &amp; serving</h2><span class="badge">Live &middot; vs {HIST_LABEL.split()[0]}</span></div>
  <div class="cards">
    <div class="card top-green"><div class="label">In a Group</div><div class="value">{group_members:,}</div><div class="sub green">~{group_pct}% of adults</div>{delta(group_members, group_apr, "vs "+HIST_LABEL.split()[0])}</div>
    <div class="card top-blue"><div class="label">Serving on Sundays</div><div class="value">{serving_sun:,}</div><div class="sub">Scheduled, last 30 days</div>{delta(serving_sun, serving_sun_apr, "vs "+HIST_LABEL.split()[0])}</div>
    <div class="card top-blue"><div class="label">Serving Anywhere</div><div class="value">{serving_any:,}</div><div class="sub">All teams</div></div>
  </div>

  <div class="section-divider"><h2>Check-ins</h2><span class="badge">Live</span></div>
  <div class="cards">
    <div class="card top-blue"><div class="label">Kids Check-ins</div><div class="value">{kids_ci:,}</div><div class="sub">Unique kids checked in</div></div>
    <div class="card top-blue"><div class="label">Student Check-ins</div><div class="value">{student_ci:,}</div><div class="sub">Unique students checked in</div></div>
  </div>

  <div class="section-divider"><h2>Guests &amp; next steps</h2><span class="badge">2026 year-to-date</span></div>
  <div class="cards">
    <div class="card top-green"><div class="label">New Sunday Guests</div><div class="value">{new_guests:,}</div><div class="sub green">This month &middot; {n(guests_ytd)} YTD</div></div>
    <div class="card top-blue"><div class="label">Baptisms</div><div class="value">{n(baptisms_ytd)}</div><div class="sub">2026 to date</div></div>
    <div class="card top-blue"><div class="label">Starting Point</div><div class="value">{n(starting_ytd)}</div><div class="sub">2026 to date</div></div>
    <div class="card top-blue"><div class="label">Connect Breakfast</div><div class="value">{n(connect_ytd)}</div><div class="sub">2026 to date</div></div>
  </div>

  <!-- ======================= YEAR-OVER-YEAR TRENDS ======================= -->
  <div class="section-divider"><h2>Year-over-year trends</h2><span class="badge">Monthly, from KPM history</span></div>

  <div class="grid-2">
    <div class="chart-card">
      <h2>Average weekly attendance</h2>
      <p class="chart-sub">Monthly average weekly attendance, this year vs prior years.</p>
      <div class="chart-wrap" style="height:230px;"><canvas id="attYoY"></canvas></div>
    </div>
    <div class="chart-card">
      <h2>New Sunday guests</h2>
      <p class="chart-sub">First-time guests by month, this year vs prior years.</p>
      <div class="chart-wrap" style="height:230px;"><canvas id="guestsYoY"></canvas></div>
    </div>
  </div>

  <div class="grid-2">
    <div class="chart-card">
      <h2>Kids check-ins</h2>
      <p class="chart-sub">Unique kids check-ins by month, year over year.</p>
      <div class="chart-wrap" style="height:230px;"><canvas id="kidsYoY"></canvas></div>
    </div>
    <div class="chart-card">
      <h2>Student check-ins</h2>
      <p class="chart-sub">Unique student check-ins by month, year over year.</p>
      <div class="chart-wrap" style="height:230px;"><canvas id="studentsYoY"></canvas></div>
    </div>
  </div>

  <div class="grid-2">
    <div class="chart-card">
      <h2>Groups &amp; serving &mdash; 2026</h2>
      <p class="chart-sub">Group members and Sunday serving by month (2026), with the 2025 monthly average for reference.</p>
      <div class="legend">
        <span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>In a group</span>
        <span class="legend-item"><span class="legend-dot" style="background:#2F8F5B;"></span>Serving Sundays</span>
      </div>
      <div class="chart-wrap" style="height:230px;"><canvas id="groupsChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h2>Baptisms &amp; Starting Point by year</h2>
      <p class="chart-sub">Annual totals. 2026 is year-to-date.</p>
      <div class="legend">
        <span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>Baptisms</span>
        <span class="legend-item"><span class="legend-dot" style="background:#C8842A;"></span>Starting Point</span>
      </div>
      <div class="chart-wrap" style="height:230px;"><canvas id="nextStepsChart"></canvas></div>
    </div>
  </div>

  <div class="mcc-footer">
    <p>Maple City Chapel &nbsp;&middot;&nbsp; MCC Connections Dashboard &nbsp;&middot;&nbsp; Prepared {RUN_DATE}</p>
    <p style="margin-top:2px;">Attendance: weekly tracking sheet. Live roster/groups/serving/check-ins: Planning Center. Trends &amp; history: MCC Connection KPMs sheet. Refreshed weekly.</p>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
Chart.defaults.font.family = "'Lato', system-ui, Arial, sans-serif";
Chart.defaults.font.size = 12;
Chart.defaults.color = '#6b7280';
const gc = 'rgba(0,0,0,0.06)';
const MONTHS = {json.dumps(MONTHS)};

// Weekly attendance + moving average
new Chart(document.getElementById('attWeekly'), {{
  data: {{ labels: {json.dumps([dt.strftime("%-m/%-d") for dt in dates])},
    datasets: [
      {{ type:'bar', label:'Weekly attendance', data:{json.dumps(totals)}, backgroundColor:'#8899AA', borderRadius:3, order:2 }},
      {{ type:'line', label:'6-week moving average', data:{json.dumps([round(sum(totals[max(0,i-5):i+1])/(min(i,5)+1)) for i in range(len(totals))])}, borderColor:'#343A44', borderWidth:2.5, pointRadius:0, tension:.3, order:1 }}
    ] }},
  options: {{ responsive:true, maintainAspectRatio:false, interaction:{{mode:'index',intersect:false}},
    plugins:{{legend:{{display:false}}, tooltip:{{callbacks:{{label:(c)=>' '+c.dataset.label+': '+c.parsed.y.toLocaleString()}}}}}},
    scales:{{x:{{grid:{{display:false}},ticks:{{color:'#9CA3AF',maxRotation:0,autoSkip:true}}}},y:{{grid:{{color:gc}},ticks:{{color:'#9CA3AF'}},min:0}}}} }}
}});

function yoy(id, datasets, pctY) {{
  new Chart(document.getElementById(id), {{
    type:'line',
    data: {{ labels: MONTHS, datasets: datasets }},
    options: {{ responsive:true, maintainAspectRatio:false, interaction:{{mode:'index',intersect:false}},
      plugins:{{ legend:{{position:'top', labels:{{usePointStyle:true, boxWidth:8, font:{{size:11, weight:'700'}}}}}},
        tooltip:{{callbacks:{{label:(c)=>c.dataset.label+': '+(c.parsed.y==null?'—':c.parsed.y.toLocaleString()+(pctY?'%':''))}}}} }},
      scales:{{ x:{{grid:{{display:false}},ticks:{{color:'#9CA3AF'}}}},
        y:{{grid:{{color:gc}},ticks:{{color:'#9CA3AF',callback:(v)=>pctY?v+'%':v}},min:0}} }} }}
  }});
}}

yoy('attYoY', {json.dumps(yoy_datasets(H["attendance_monthly"]))});
yoy('guestsYoY', {json.dumps(yoy_datasets(H["guests_monthly"]))});
yoy('kidsYoY', {json.dumps(yoy_datasets(H["kids_checkins_monthly"]))});
yoy('studentsYoY', {json.dumps(yoy_datasets(H["student_checkins_monthly"]))});

// Groups & serving 2026 monthly + 2025 avg reference
const gs = {json.dumps(H["groups_serving_2026"])};
const gsRef = {json.dumps(H["groups_serving_prioryear_avg"].get("2025", {}))};
new Chart(document.getElementById('groupsChart'), {{
  type:'line',
  data: {{ labels: MONTHS, datasets: [
    {{ label:'In a group', data:gs.group_members, borderColor:'#343A44', backgroundColor:'#343A44', borderWidth:3, pointRadius:3, tension:.3, spanGaps:false }},
    {{ label:'Serving Sundays', data:gs.serving_sundays, borderColor:'#2F8F5B', backgroundColor:'#2F8F5B', borderWidth:3, pointRadius:3, tension:.3, spanGaps:false }},
    {{ label:'2025 group avg', data:MONTHS.map(()=>gsRef.group_members), borderColor:'#343A44', borderDash:[5,4], borderWidth:1.3, pointRadius:0 }},
    {{ label:'2025 serving avg', data:MONTHS.map(()=>gsRef.serving_sundays), borderColor:'#2F8F5B', borderDash:[5,4], borderWidth:1.3, pointRadius:0 }}
  ] }},
  options: {{ responsive:true, maintainAspectRatio:false, interaction:{{mode:'index',intersect:false}},
    plugins:{{legend:{{display:false}}, tooltip:{{callbacks:{{label:(c)=>c.dataset.label+': '+(c.parsed.y==null?'—':c.parsed.y)}}}}}},
    scales:{{x:{{grid:{{display:false}},ticks:{{color:'#9CA3AF'}}}},y:{{grid:{{color:gc}},ticks:{{color:'#9CA3AF'}},min:0}}}} }}
}});

// Baptisms & Starting Point by year
const byrs = {json.dumps(sorted(H["baptisms_by_year"].keys()))};
new Chart(document.getElementById('nextStepsChart'), {{
  type:'bar',
  data: {{ labels: byrs, datasets: [
    {{ label:'Baptisms', data:byrs.map(y=>({json.dumps(H["baptisms_by_year"])})[y]), backgroundColor:'#343A44', borderRadius:4 }},
    {{ label:'Starting Point', data:byrs.map(y=>({json.dumps(H["starting_point_by_year"])})[y]), backgroundColor:'#C8842A', borderRadius:4 }}
  ] }},
  options: {{ responsive:true, maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}, tooltip:{{mode:'index'}}}},
    scales:{{x:{{grid:{{display:false}},ticks:{{color:'#9CA3AF'}}}},y:{{grid:{{color:gc}},ticks:{{color:'#9CA3AF'}},min:0}}}} }}
}});
</script>
</body>
</html>"""

out = os.path.join(BASE, "connections.html")
with open(out, "w") as f:
    f.write(html)
print("wrote", out, len(html), "bytes | weekend", weekend, "| YTD", avg_weekly_ytd,
      "| adults", adults, "(vs Apr", active_apr, ") | baptisms", baptisms_ytd, "| SP", starting_ytd)
