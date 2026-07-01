#!/usr/bin/env python3
"""
MCC Connections dashboard renderer.

Reads data/connections.json (the live data layer, refreshed weekly by the
Connections refresh job) and writes connections.html.

Data sources:
  Attendance (weekly)  -- Google Sheet '2026' tab (weekly total attendance).
  Everything else      -- Planning Center saved Lists, as of the close of the
                          previous month. Adults = Active - Students - Kids.

Weekly job: overwrite data/connections.json, then run:  python3 build_connections.py
The template/CSS/chart config below is stable; numbers come from the JSON.
"""
import json, os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE, "data", "connections.json")) as f:
    D = json.load(f)

M = D["meta"]; P = D["pco"]; A = D["attendance"]; FL = D.get("flags", {})
RUN_DATE = M["run_date"]; DATA_THROUGH = M["data_through"]
PREV_MONTH_NUM = M["prev_month_num"]; PREV_MONTH_LABEL = M["prev_month_label"]

# ---- Attendance (from weekly series) ----
weekly = A["weekly"]                     # [[iso_date, total], ...]
totals = [t for _, t in weekly]
dates  = [datetime.strptime(d, "%Y-%m-%d") for d, _ in weekly]
weekend = totals[-1]
weekend_date = dates[-1].strftime("%b %-d")
avg_weekly_ytd = round(sum(totals) / len(totals))
mov6 = round(sum(totals[-6:]) / min(6, len(totals)))
_pm = [t for dt, t in zip(dates, totals) if dt.month == PREV_MONTH_NUM]
avg_weekly_prev = round(sum(_pm) / len(_pm)) if _pm else None

# 6-week trailing moving-average series (for the chart)
mov_series = [round(sum(totals[max(0, i - 5):i + 1]) / (min(i, 5) + 1)) for i in range(len(totals))]
chart_labels = [dt.strftime("%-m/%-d") for dt in dates]

# ---- PCO roster ----
active = P["active_profiles"]; students = P["student_profiles"]; kids = P["kid_profiles"]
adults = active - students - kids
households = P["households"]
group_members = P["group_members"]; serving_sun = P["serving_sundays"]; serving_any = P["serving_anywhere"]
kids_ci = P["kids_checkins"]; student_ci = P["student_checkins"]
new_guests = P["new_guests_month"]; starting_point = P["starting_point"]
baptisms = P.get("baptisms"); connect_bf = P.get("connect_breakfast")

def n(v):
    return "&mdash;" if v is None else "{:,}".format(v)

# A card value, or a muted "not tracked" note when the source is unavailable
def val_or_note(v, note_key):
    if v is not None:
        return '<div class="value">%s</div><div class="sub">as of close of %s</div>' % (n(v), PREV_MONTH_LABEL)
    return '<div class="value" style="color:var(--muted)">&mdash;</div><div class="sub yellow">Not tracked in PCO</div>'

# ---- Takeaways (regenerated from this run's numbers) ----
group_pct = round(group_members / adults * 100) if adults else 0
serve_pct = round(serving_sun / (adults + students) * 100) if (adults + students) else 0
peak = max(totals); peak_date = dates[totals.index(peak)].strftime("%b %-d")
takeaways = [
    ("green", "Weekend attendance is healthy &mdash; the YTD weekly average is <strong>%s</strong>, with a 6-week moving average of <strong>%s</strong>. %s was the strongest week of the year at %s." % (f"{avg_weekly_ytd:,}", f"{mov6:,}", peak_date, f"{peak:,}")),
    ("blue", "%s averaged <strong>%s</strong> per weekend&mdash;%s the YTD pace, consistent with the normal early-summer dip." % (PREV_MONTH_LABEL.split()[0], f"{avg_weekly_prev:,}" if avg_weekly_prev else "&mdash;", "below" if avg_weekly_prev and avg_weekly_prev < avg_weekly_ytd else "in line with")),
    ("green", "Discipleship base is strong &mdash; <strong>%s adults</strong> are in a Life/Care/Legacy group (~%d%% of adults) and <strong>%s</strong> serve on Sundays." % (f"{group_members:,}", group_pct, f"{serving_sun:,}")),
    ("blue", "The roster stands at <strong>%s active profiles</strong> across %s households (%s adults, %s students, %s kids), with <strong>%s</strong> new Sunday guests in the last month." % (f"{active:,}", f"{households:,}", f"{adults:,}", students, kids, new_guests)),
]
if baptisms is None or connect_bf is None:
    takeaways.append(("amber", "Two metrics need a live source: <strong>baptisms</strong> and <strong>Connect Breakfast</strong> aren't currently maintained in Planning Center, so they show as not tracked. Point them at a real list or the Sheet to light them up."))

def takeaway_items():
    dot = {"green": "dot-green", "amber": "dot-amber", "red": "dot-red", "blue": "dot-blue"}
    return "".join('<li><span class="dot %s"></span><span>%s</span></li>' % (dot[s], b) for s, b in takeaways)

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
  :root {{
    --slate:#343A44; --bg:#F2F2F2; --card:#fff; --ink:#23272e; --muted:#6b7280;
    --line:#e3e5ea; --red:#DC2626; --green:#2F8F5B; --amber:#C8842A; --chart:#4C5564;
  }}
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
  .profile-strip {{ display:grid; grid-template-columns:repeat(5,1fr); background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; box-shadow:0 1px 4px rgba(20,30,60,.05); }}
  .profile-strip .cell {{ padding:18px 16px; text-align:center; border-right:1px solid var(--line); }}
  .profile-strip .cell:last-child {{ border-right:none; }}
  .profile-strip .cell .plabel {{ font-size:11px; color:var(--green); font-weight:700; text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px; }}
  .profile-strip .cell .pval {{ font-size:24px; font-weight:900; color:var(--slate); letter-spacing:-0.5px; }}
  @media (max-width:720px) {{ .profile-strip {{ grid-template-columns:repeat(2,1fr); }} .profile-strip .cell {{ border-bottom:1px solid var(--line); }} }}
  .insights {{ background:#F4F5F7; border:1px solid var(--line); border-radius:10px; padding:20px 24px; margin-top:6px; }}
  .insights h2 {{ font-size:13px; font-weight:900; text-transform:uppercase; letter-spacing:.08em; color:var(--slate); margin-bottom:12px; }}
  .insights ul {{ list-style:none; }}
  .insights ul li {{ padding:8px 0; border-bottom:1px solid var(--line); font-size:13px; color:var(--ink); display:flex; align-items:flex-start; gap:10px; line-height:1.55; }}
  .insights ul li:last-child {{ border-bottom:none; }}
  .dot {{ width:8px; height:8px; border-radius:50%; margin-top:5px; flex-shrink:0; }}
  .dot-green {{ background:var(--green); }} .dot-red {{ background:var(--red); }} .dot-amber {{ background:var(--amber); }} .dot-blue {{ background:var(--slate); }}
  .chart-card {{ background:var(--card); border-radius:10px; padding:22px 22px 18px; border:1px solid var(--line); margin-bottom:14px; box-shadow:0 1px 4px rgba(20,30,60,.05); }}
  .chart-card h2 {{ font-size:15px; font-weight:900; text-transform:uppercase; letter-spacing:-.01em; color:var(--slate); margin-bottom:4px; }}
  .chart-card .chart-sub {{ font-size:13px; color:var(--muted); margin-bottom:16px; }}
  .chart-wrap {{ position:relative; width:100%; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin-bottom:14px; }}
  .legend-item {{ display:flex; align-items:center; gap:6px; font-size:12px; color:var(--muted); font-weight:700; }}
  .legend-dot {{ width:10px; height:10px; border-radius:2px; flex-shrink:0; }}
  .section-divider {{ margin:32px 0 20px; padding-bottom:10px; border-bottom:2px solid var(--slate); display:flex; align-items:center; gap:10px; }}
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
  <div class="right">Attendance through {DATA_THROUGH}<br>Profiles &amp; groups: close of {PREV_MONTH_LABEL}</div>
  </div>
</header>

<div class="page">

  <div class="section-label">Weekend attendance &mdash; updated weekly</div>
  <div class="cards">
    <div class="card top-blue"><div class="label">Weekend Attendance</div><div class="value">{weekend:,}</div><div class="sub">Week of {weekend_date}</div></div>
    <div class="card top-blue"><div class="label">6-Week Moving Avg</div><div class="value">{mov6:,}</div><div class="sub">Rolling 6-week average</div></div>
    <div class="card top-green"><div class="label">Avg Weekly Att. YTD</div><div class="value">{avg_weekly_ytd:,}</div><div class="sub green">Year-to-date average</div></div>
    <div class="card top-blue"><div class="label">Avg Weekly Att. &mdash; {PREV_MONTH_LABEL.split()[0]}</div><div class="value">{n(avg_weekly_prev)}</div><div class="sub">Close of {PREV_MONTH_LABEL.split()[0]}</div></div>
  </div>

  <div class="section-label">Weekly attendance trend &mdash; 2026</div>
  <div class="chart-card">
    <h2>Weekly attendance with 6-week moving average</h2>
    <p class="chart-sub">Each Sunday's total attendance this year, with the trailing 6-week moving average.</p>
    <div class="legend">
      <span class="legend-item"><span class="legend-dot" style="background:#8899AA;"></span>Weekly attendance</span>
      <span class="legend-item"><span class="legend-dot" style="background:#343A44;"></span>6-week moving average</span>
    </div>
    <div class="chart-wrap" style="height:240px;"><canvas id="attChart" role="img" aria-label="Weekly attendance trend 2026"></canvas></div>
  </div>

  <div class="section-label">Planning Center profile data &mdash; close of {PREV_MONTH_LABEL}</div>
  <div class="profile-strip">
    <div class="cell"><div class="plabel">Active Profiles</div><div class="pval">{active:,}</div></div>
    <div class="cell"><div class="plabel">Adults</div><div class="pval">{adults:,}</div></div>
    <div class="cell"><div class="plabel">Students</div><div class="pval">{students:,}</div></div>
    <div class="cell"><div class="plabel">Kids</div><div class="pval">{kids:,}</div></div>
    <div class="cell"><div class="plabel">Unique Households</div><div class="pval">{households:,}</div></div>
  </div>

  <div class="section-label">Key takeaways</div>
  <div class="insights">
    <h2>What this data is telling us</h2>
    <ul>{takeaway_items()}</ul>
  </div>

  <div class="section-divider"><h2>Groups &amp; serving</h2><span class="badge">Close of {PREV_MONTH_LABEL}</span></div>
  <div class="cards">
    <div class="card top-green"><div class="label">In a Group</div><div class="value">{group_members:,}</div><div class="sub green">~{group_pct}% of adults &middot; Life/Care/Legacy</div></div>
    <div class="card top-blue"><div class="label">Serving on Sundays</div><div class="value">{serving_sun:,}</div><div class="sub">Scheduled, last 30 days</div></div>
    <div class="card top-blue"><div class="label">Serving Anywhere</div><div class="value">{serving_any:,}</div><div class="sub">All teams</div></div>
  </div>

  <div class="section-divider"><h2>Check-ins</h2><span class="badge">Close of {PREV_MONTH_LABEL}</span></div>
  <div class="cards">
    <div class="card top-blue"><div class="label">Kids Check-ins</div><div class="value">{kids_ci:,}</div><div class="sub">Unique kids checked in</div></div>
    <div class="card top-blue"><div class="label">Student Check-ins</div><div class="value">{student_ci:,}</div><div class="sub">Unique students checked in</div></div>
  </div>

  <div class="section-divider"><h2>Guests &amp; next steps</h2><span class="badge">Close of {PREV_MONTH_LABEL}</span></div>
  <div class="cards">
    <div class="card top-green"><div class="label">New Sunday Guests</div><div class="value">{new_guests:,}</div><div class="sub green">First-time guests, last month</div></div>
    <div class="card top-blue"><div class="label">Starting Point</div><div class="value">{n(starting_point)}</div><div class="sub">Attendees to date</div></div>
    <div class="card top-amber"><div class="label">Baptisms</div>{val_or_note(baptisms, "baptisms")}</div>
    <div class="card top-amber"><div class="label">Connect Breakfast</div>{val_or_note(connect_bf, "connect_breakfast")}</div>
  </div>

  <div class="mcc-footer">
    <p>Maple City Chapel &nbsp;&middot;&nbsp; MCC Connections Dashboard &nbsp;&middot;&nbsp; Prepared {RUN_DATE}</p>
    <p style="margin-top:2px;">Attendance: internal weekly tracking (Google Sheet). Profiles, groups, serving, check-ins &amp; guests: Planning Center (close of {PREV_MONTH_LABEL}). Refreshed weekly.</p>
  </div>

</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
Chart.defaults.font.family = "'Lato', system-ui, Arial, sans-serif";
Chart.defaults.font.size = 12;
Chart.defaults.color = '#6b7280';
const gc = 'rgba(0,0,0,0.06)';
new Chart(document.getElementById('attChart'), {{
  data: {{
    labels: {json.dumps(chart_labels)},
    datasets: [
      {{ type:'bar', label:'Weekly attendance', data:{json.dumps(totals)}, backgroundColor:'#8899AA', borderRadius:3, order:2 }},
      {{ type:'line', label:'6-week moving average', data:{json.dumps(mov_series)}, borderColor:'#343A44', backgroundColor:'rgba(52,58,68,0.06)', borderWidth:2.5, pointRadius:0, tension:.3, fill:false, order:1 }}
    ]
  }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    interaction:{{mode:'index', intersect:false}},
    plugins:{{ legend:{{display:false}}, tooltip:{{callbacks:{{label:(c)=>' '+c.dataset.label+': '+c.parsed.y.toLocaleString()}}}} }},
    scales:{{ x:{{grid:{{display:false}}, ticks:{{color:'#9CA3AF', maxRotation:0, autoSkip:true}}}},
              y:{{grid:{{color:gc}}, ticks:{{color:'#9CA3AF'}}, min:0}} }}
  }}
}});
</script>
</body>
</html>"""

out = os.path.join(BASE, "connections.html")
with open(out, "w") as f:
    f.write(html)
print("wrote", out, len(html), "bytes | weekend", weekend, "| YTD avg", avg_weekly_ytd,
      "| mov6", mov6, "| adults", adults, "| group", group_members)
