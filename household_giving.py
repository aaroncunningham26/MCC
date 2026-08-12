#!/usr/bin/env python3
"""
Household-basis committed giving and retention for the MCC finance dashboard.

WHY THIS EXISTS
The PCO worker's committed_units / churn tools count INDIVIDUAL donor records.
A married couple who both give shows up as two committed units. That inflates the
base, understates the average gift, and — worst — made the dashboard's
participation figure divide individual units by households, which never compared
like with like.

This script recomputes the same concepts on a HOUSEHOLD basis, straight from the
PCO Giving API, and merges the results into data/live.json under:
    giving_health.committed          (household committed count)
    giving_health.committed_individuals   (kept for continuity/reference)
    retention.{retained,lapsed,new,rate,prior}   (household basis)
    retention.basis = "household"

Run this BEFORE build_dashboard.py in the weekly job:
    python3 household_giving.py && python3 build_dashboard.py

Takes about 3 minutes (roughly 130 API pages). Requires PCO_APP_ID / PCO_SECRET
in ~/.mcc/pco-mcp-secrets.json. If the API is unreachable it leaves live.json
untouched and exits non-zero, so the render keeps the prior week's figures
rather than publishing a wrong number.
"""
import base64, json, os, sys, time, urllib.request
from collections import defaultdict
from datetime import date, timedelta

BASE     = "https://api.planningcenteronline.com"
FUND_ID  = "204568"          # Tithe/Offering == QBO 4100
THRESHOLD = 200              # "committed" = gave MORE THAN this, trailing 12 mo
HERE     = os.path.dirname(os.path.abspath(__file__))
LIVE     = os.path.join(HERE, "data", "live.json")

def auth():
    p = os.path.expanduser("~/.mcc/pco-mcp-secrets.json")
    s = json.load(open(p))
    return base64.b64encode(f"{s['PCO_APP_ID']}:{s['PCO_SECRET']}".encode()).decode()

def get(url, a, tries=5):
    if not url.startswith("http"):
        url = BASE + url
    for i in range(tries):
        try:
            rq = urllib.request.Request(url, headers={"Authorization": "Basic " + a})
            with urllib.request.urlopen(rq, timeout=60) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))

def main():
    live = json.load(open(LIVE))
    # Align the windows to the dashboard's data_through, not to "today".
    dt = live["data_through"]                      # e.g. "August 2, 2026"
    from datetime import datetime
    data_through = datetime.strptime(dt, "%B %d, %Y").date()
    cur_start    = data_through - timedelta(days=364)
    prior_start  = cur_start - timedelta(days=365)

    a = auth()

    # ---- donations in both windows, Tithe/Offering only --------------------
    gifts = []                       # (person_id, iso_date, dollars)
    url = (f"/giving/v2/donations?per_page=100&include=designations"
           f"&where[received_at][gte]={prior_start.isoformat()}"
           f"&where[received_at][lte]={data_through.isoformat()}&order=received_at")
    pages = 0
    while url:
        d = get(url, a)
        desig = {x["id"]: x for x in d.get("included", []) if x["type"] == "Designation"}
        for don in d["data"]:
            at = don["attributes"]
            if at.get("payment_status") != "succeeded" or at.get("refunded"):
                continue
            pr = don["relationships"]["person"]["data"]
            if not pr:
                continue                                  # loose cash / anonymous
            cents = sum(desig[r["id"]]["attributes"]["amount_cents"]
                        for r in don["relationships"]["designations"]["data"]
                        if r["id"] in desig
                        and (desig[r["id"]]["relationships"]["fund"]["data"] or {}).get("id") == FUND_ID)
            if cents > 0:
                gifts.append((pr["id"], at["received_at"][:10], cents / 100.0))
        pages += 1
        url = d["links"].get("next")
    if not gifts:
        raise RuntimeError("no Tithe/Offering gifts returned; refusing to overwrite live.json")

    # ---- map each donor to a household ------------------------------------
    pids = sorted({p for p, _, _ in gifts})
    hh_of = {}
    for i in range(0, len(pids), 25):
        d = get(f"/people/v2/people?where[id]={','.join(pids[i:i+25])}"
                f"&per_page=100&include=households", a)
        for p in d["data"]:
            rel = (p.get("relationships", {}) or {}).get("households", {}) or {}
            data = rel.get("data") or []
            hh_of[p["id"]] = ("H" + data[0]["id"]) if data else ("P" + p["id"])

    # ---- totals per household in each window -------------------------------
    cur, pri = defaultdict(float), defaultdict(float)
    ci, pi = defaultdict(float), defaultdict(float)      # individual, for reference
    for pid, ds, amt in gifts:
        k = hh_of.get(pid, "P" + pid)
        d_ = date.fromisoformat(ds)
        if cur_start <= d_ <= data_through:
            cur[k] += amt; ci[pid] += amt
        elif prior_start <= d_ < cur_start:
            pri[k] += amt; pi[pid] += amt

    committed_now   = {k for k, v in cur.items() if v > THRESHOLD}
    committed_prior = {k for k, v in pri.items() if v > THRESHOLD}
    retained = committed_prior & committed_now
    lapsed   = committed_prior - committed_now
    newly    = committed_now - committed_prior
    rate     = len(retained) / len(committed_prior) * 100 if committed_prior else 0.0

    ind_now = len([p for p, v in ci.items() if v > THRESHOLD])

    # ---- merge into live.json ---------------------------------------------
    # RE-READ before writing. live.json sits in a Google Drive-synced tree and the
    # weekly job writes it too; the PCO pull above takes ~3 minutes, which is plenty
    # of time for a newer version to land underneath us. Patch only our own keys
    # onto the freshest copy, and abort if the reporting window moved while we ran
    # (that means a different run owns the file now).
    fresh = json.load(open(LIVE))
    if fresh.get("data_through") != dt:
        raise RuntimeError(
            f"live.json changed while this ran (data_through was {dt!r}, now "
            f"{fresh.get('data_through')!r}). Not writing -- re-run after the other job finishes.")

    gh = fresh["giving_health"]
    gh["committed_individuals"] = ind_now          # what the old tool reported
    gh["committed"] = len(committed_now)           # household basis (what renders)
    gh["committed_basis"] = "household"

    fresh["retention"] = {
        "retained": len(retained),
        "lapsed":   len(lapsed),
        "new":      len(newly),
        "rate":     round(rate, 1),
        "prior":    len(committed_prior),
        "basis":    "household",
    }
    tmp = LIVE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(fresh, f, indent=1)
    os.replace(tmp, LIVE)          # atomic swap, no partially-written file

    print(f"households committed: {len(committed_now)} (prior {len(committed_prior)}) | "
          f"retained {len(retained)} lapsed {len(lapsed)} new {len(newly)} "
          f"| retention {rate:.1f}% | individual basis would be {ind_now} "
          f"| {len(gifts)} gifts / {pages} pages")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: household_giving.py failed ({e}); live.json left unchanged", file=sys.stderr)
        sys.exit(1)
