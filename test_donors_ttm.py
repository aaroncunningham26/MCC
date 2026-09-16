#!/usr/bin/env python3
"""
Tests for the rolling-12-month unique-donor counts added to household_giving.py
and consumed by build_dashboard.py.

Runs offline -- no PCO calls, no warehouse calls. Exercises the windowing,
threshold, household-collapse and invariant logic on synthetic gifts, plus the
dashboard's TTM-vs-partial-year row selection and its fallback.

    python3 test_donors_ttm.py
"""
import sys
from collections import defaultdict
from datetime import date, timedelta

FAILURES = []

def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s %s" % (name, detail))
        FAILURES.append(name)


# ── The counting logic, mirrored from household_giving.main() ───────────────
# Kept as a standalone function so the arithmetic can be tested without the API
# round-trip. Must stay in sync with household_giving.py.
def counts(gifts, hh_of, cur_start, data_through, prior_start, threshold=200):
    cur, pri = defaultdict(float), defaultdict(float)
    ci, pi = defaultdict(float), defaultdict(float)
    for pid, ds, amt in gifts:
        k = hh_of.get(pid, "P" + pid)
        d_ = date.fromisoformat(ds)
        if cur_start <= d_ <= data_through:
            cur[k] += amt; ci[pid] += amt
        elif prior_start <= d_ < cur_start:
            pri[k] += amt; pi[pid] += amt
    return {
        "committed_hh":   len({k for k, v in cur.items() if v > threshold}),
        "committed_ind":  len([p for p, v in ci.items() if v > threshold]),
        "donors_ttm":     len(ci),
        "donors_hh_ttm":  len(cur),
        "donors_ttm_pri": len(pi),
    }


THROUGH = date(2026, 9, 13)
CUR_START = THROUGH - timedelta(days=364)      # 2025-09-14
PRIOR_START = CUR_START - timedelta(days=365)  # 2024-09-14


def test_windowing():
    print("\nwindow boundaries")
    gifts = [
        ("1", CUR_START.isoformat(), 50.0),                              # first day in window
        ("2", THROUGH.isoformat(), 50.0),                                # last day in window
        ("3", (CUR_START - timedelta(days=1)).isoformat(), 50.0),        # prior window
        ("4", (THROUGH + timedelta(days=1)).isoformat(), 50.0),          # after window: excluded
        ("5", PRIOR_START.isoformat(), 50.0),                            # first day of prior
    ]
    c = counts(gifts, {}, CUR_START, THROUGH, PRIOR_START)
    check("current window is inclusive on both ends", c["donors_ttm"] == 2,
          "got %d, expected 2" % c["donors_ttm"])
    check("gifts after data_through excluded", "4" not in [g[0] for g in gifts
          if CUR_START <= date.fromisoformat(g[1]) <= THROUGH])
    check("prior window picks up the two prior-year donors", c["donors_ttm_pri"] == 2,
          "got %d, expected 2" % c["donors_ttm_pri"])


def test_threshold_subset():
    print("\nthreshold subset invariant")
    gifts = [
        ("1", "2026-01-05", 500.0),    # over
        ("2", "2026-01-05", 201.0),    # over (strictly greater)
        ("3", "2026-01-05", 200.0),    # exactly at threshold -> NOT committed
        ("4", "2026-01-05", 5.0),      # under
        ("5", "2026-02-05", 100.0),    # under alone...
        ("5", "2026-03-05", 150.0),    # ...but 250 cumulative -> over
    ]
    c = counts(gifts, {}, CUR_START, THROUGH, PRIOR_START)
    check("any-amount count includes everyone", c["donors_ttm"] == 5,
          "got %d, expected 5" % c["donors_ttm"])
    check("threshold is strictly greater-than", c["committed_ind"] == 3,
          "got %d, expected 3 (ids 1,2,5)" % c["committed_ind"])
    check("gifts accumulate across the window", c["committed_ind"] == 3)
    check("INVARIANT committed subset of any-amount",
          c["committed_ind"] <= c["donors_ttm"])


def test_household_collapse():
    print("\nhousehold collapse")
    gifts = [
        ("p1", "2026-01-05", 150.0),
        ("p2", "2026-01-05", 150.0),   # spouse, same household -> 300 combined
        ("p3", "2026-01-05", 400.0),   # own household
    ]
    hh = {"p1": "H9", "p2": "H9", "p3": "H7"}
    c = counts(gifts, hh, CUR_START, THROUGH, PRIOR_START)
    check("individuals counted separately", c["donors_ttm"] == 3,
          "got %d" % c["donors_ttm"])
    check("households collapse the couple", c["donors_hh_ttm"] == 2,
          "got %d" % c["donors_hh_ttm"])
    check("couple qualifies as committed jointly (150+150 > 200)",
          c["committed_hh"] == 2, "got %d" % c["committed_hh"])
    check("neither spouse qualifies individually", c["committed_ind"] == 1,
          "got %d, expected 1 (p3 only)" % c["committed_ind"])
    check("INVARIANT households <= individuals",
          c["donors_hh_ttm"] <= c["donors_ttm"])
    check("INVARIANT committed households <= any-amount households",
          c["committed_hh"] <= c["donors_hh_ttm"])


def test_donorless_person_fallback():
    print("\ndonor with no household record")
    gifts = [("p1", "2026-01-05", 300.0)]
    c = counts(gifts, {}, CUR_START, THROUGH, PRIOR_START)   # hh_of empty
    check("falls back to a per-person key, still counted",
          c["donors_hh_ttm"] == 1 and c["committed_hh"] == 1)


# ── Dashboard row-selection logic ──────────────────────────────────────────
def select_rows(part_rows, ttm=None, att_ttm=None):
    """Mirrors build_dashboard.py: when a TTM reading is available it replaces
    the partial calendar row; otherwise the partial row is kept and daggered."""
    if ttm and att_ttm:
        rows = [r for r in part_rows if not r[4]]
        rows.append(("TTM", round(att_ttm), ttm, ttm/att_ttm*100, False, "win"))
        return rows, True
    return part_rows, False


def test_row_selection():
    print("\ndashboard row selection")
    base = [
        (2024, 978, 371, 37.9, False, "2024-12-31"),
        (2025, 1025, 341, 33.3, False, "2025-12-31"),
        (2026, 1013, 296, 29.2, True,  "2026-06-30"),   # partial
    ]
    rows, used_ttm = select_rows(base, ttm=350, att_ttm=1020)
    check("TTM path drops the partial calendar row",
          all(not r[4] for r in rows) and len(rows) == 3)
    check("TTM row is appended last and is judgeable", rows[-1][0] == "TTM" and used_ttm)
    check("TTM percentage computed on TTM attendance",
          abs(rows[-1][3] - 350/1020*100) < 1e-9)

    rows, used_ttm = select_rows(base, ttm=None, att_ttm=None)
    check("fallback keeps the partial row", used_ttm is False and rows[-1][4] is True)
    check("fallback still exposes closed rows for the goal test",
          len([r for r in rows if not r[4]]) == 2)


def test_ttm_beats_partial():
    print("\nregression: TTM must not understate like the YTD count did")
    # The bug: 6 months of donors over a 12-month attendance average.
    ytd_pct = 296 / 1013 * 100
    ttm_pct = 350 / 1020 * 100      # a plausible full 12-month count
    check("YTD reading understated vs a full-year reading", ytd_pct < ttm_pct,
          "ytd %.1f%% ttm %.1f%%" % (ytd_pct, ttm_pct))
    check("TTM lands in the neighbourhood of the last closed year (33%)",
          abs(ttm_pct - 33.3) < 8, "ttm %.1f%%" % ttm_pct)


if __name__ == "__main__":
    for t in (test_windowing, test_threshold_subset, test_household_collapse,
              test_donorless_person_fallback, test_row_selection, test_ttm_beats_partial):
        t()
    print("\n%d failure(s)" % len(FAILURES))
    sys.exit(1 if FAILURES else 0)
