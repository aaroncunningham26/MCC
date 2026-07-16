#!/usr/bin/env python3
"""
warehouse_reader.py -- shared read-only client for the MCC Data Warehouse.

Data source: MCC Data Warehouse (see CLAUDE.md DATA ARCHITECTURE)

Stdlib-only (urllib/json). Used by build_vitals.py, build_connections.py and
build_dashboard.py so all dashboards read the same single source of truth.

Endpoint:
  POST https://pco-mcp-server.aaroncunningham.workers.dev/warehouse/read
  body: {"secret": <WAREHOUSE_SECRET>, "tab": "observations"|"metric_registry"|"config"}

Tabs (tidy long format):
  observations     date (YYYY-MM-DD), metric_id, value, source, pulled_at, notes
  metric_registry  metric_id, name, pillar, source, cadence, unit, goal,
                   definition, owner, active
  config           key, value, effective_date, source

Conventions honored here:
  * observations is APPEND-ONLY: when duplicate (date, metric_id) rows exist,
    the LAST row wins (corrections supersede earlier rows).
  * Monthly observations are dated the last day of the month; annual
    observations are dated Dec 31. A mid-year Jun-30 row (e.g. 2026-06-30) is
    that year's YTD "annual" value; a later Dec-31 row supersedes it.
  * Responses are cached in-module, so a build script makes at most one HTTP
    request per tab (max 3 per run).
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

# Dedicated warehouse worker (2026-07-16; split off the unstable pco-mcp-server).
ENDPOINT = "https://mcc-warehouse.aaroncunningham.workers.dev/warehouse/read"
SECRETS_PATH = os.path.expanduser("~/.mcc/pco-mcp-secrets.json")
TIMEOUT = 60

# Fallback: hourly JSON export written by the warehouse Apps Script into the
# Drive-synced "Data Sheets" folder. Used only when the Worker is unreachable,
# and only if fresh enough. A Worker outage can no longer block a publish.
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "Data Sheets", "warehouse-cache.json")
CACHE_MAX_AGE_HOURS = 48

_tab_cache = {}   # tab name -> list of row dicts
_obs_cache = None  # deduped, date-sorted observations


def _die(msg):
    sys.exit(
        "ERROR: %s\n"
        "The MCC Data Warehouse could not be read. Check your network "
        "connection and that %s contains a valid WAREHOUSE_SECRET.\n"
        "(No fallback to legacy files -- the warehouse is the single source "
        "of truth.)" % (msg, SECRETS_PATH)
    )


def _secret():
    try:
        with open(SECRETS_PATH) as f:
            secrets = json.load(f)
    except OSError as e:
        _die("cannot open secrets file %s (%s)" % (SECRETS_PATH, e))
    except ValueError as e:
        _die("secrets file %s is not valid JSON (%s)" % (SECRETS_PATH, e))
    secret = secrets.get("WAREHOUSE_SECRET")
    if not secret:
        _die("no WAREHOUSE_SECRET key in %s" % SECRETS_PATH)
    return secret


def _num(v):
    """Best-effort numeric parse; returns float or None."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("$", "")
    try:
        return float(s)
    except ValueError:
        return None


def fetch_tab(tab):
    """Fetch a warehouse tab. Returns a list of dicts keyed by the tab header.
    Results are cached in-module."""
    if tab in _tab_cache:
        return _tab_cache[tab]
    body = json.dumps({"secret": _secret(), "tab": tab}).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body, headers={
            "Content-Type": "application/json",
            # Cloudflare blocks the default "Python-urllib" user agent with a 403.
            "User-Agent": "mcc-warehouse-reader/1.0",
        })
    payload = None
    err = None
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not payload.get("ok"):
            err = "warehouse returned not-ok for tab '%s': %r" % (tab, payload)
            payload = None
    except (urllib.error.URLError, OSError, ValueError) as e:
        err = "request for tab '%s' failed (%s)" % (tab, e)
    if payload is None:
        payload = _cache_fallback(tab, err)
    header = payload["header"]
    rows = [dict(zip(header, r)) for r in payload["rows"]]
    _tab_cache[tab] = rows
    return rows


def _cache_fallback(tab, err):
    """Worker unreachable: serve the tab from the hourly Apps Script export in
    'Data Sheets/warehouse-cache.json' if it is fresh enough; otherwise die."""
    try:
        with open(CACHE_PATH) as f:
            cache = json.load(f)
        exported = cache.get("exported_at", "1970-01-01T00:00:00")
        age_h = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.datetime.fromisoformat(exported.replace("Z", "+00:00"))
                 ).total_seconds() / 3600.0
        tabs = cache.get("tabs", {})
        if tab not in tabs:
            raise KeyError("tab '%s' not in cache" % tab)
        if age_h > CACHE_MAX_AGE_HOURS:
            _die("%s; local cache exists but is %.0fh old (max %dh)"
                 % (err, age_h, CACHE_MAX_AGE_HOURS))
        sys.stderr.write(
            "WARNING: warehouse endpoint unavailable (%s) — using local cache "
            "from %s (%.1fh old). Data may lag slightly; the Worker needs "
            "attention (see MCC/WAREHOUSE-RUNBOOK.md).\n" % (err, exported, age_h))
        return tabs[tab]
    except (OSError, ValueError, KeyError) as e:
        _die("%s; cache fallback also failed (%s at %s)" % (err, e, CACHE_PATH))


def observations():
    """All observation rows as dicts with numeric `value`, deduped so that for
    each (date, metric_id) pair only the LAST occurrence in the sheet survives
    (append-only corrections supersede). Sorted by date ascending."""
    global _obs_cache
    if _obs_cache is None:
        dedup = {}
        for row in fetch_tab("observations"):
            date = str(row.get("date") or "").strip()
            mid = str(row.get("metric_id") or "").strip()
            if not date or not mid:
                continue
            r = dict(row)
            r["date"] = date
            r["metric_id"] = mid
            r["value"] = _num(row.get("value"))
            dedup[(date, mid)] = r  # sheet order: later rows overwrite earlier
        _obs_cache = sorted(dedup.values(), key=lambda r: r["date"])
    return _obs_cache


def _rows_for(metric_id):
    return [r for r in observations() if r["metric_id"] == metric_id]


def monthly(metric_id, year):
    """dict month_index (1-12) -> value for observations dated within `year`.
    Rows are date-sorted, so if a month somehow has several dated rows the
    latest date wins."""
    prefix = "%04d-" % year
    out = {}
    for r in _rows_for(metric_id):
        if r["date"].startswith(prefix) and r["value"] is not None:
            out[int(r["date"][5:7])] = r["value"]
    return out


def annual(metric_id):
    """dict year -> value for annual observations: rows dated Dec 31 of any
    year, plus ANY current-year dated row (mid-year YTD anchors advance month
    by month as refreshes land). Assigned in date order, so a later-dated row
    supersedes an earlier YTD row for the same year. Only call this for
    metrics whose current-year values are annual/YTD (not monthly series)."""
    this_year = datetime.date.today().year
    out = {}
    for r in _rows_for(metric_id):
        d, v = r["date"], r["value"]
        if v is None:
            continue
        if d.endswith("-12-31") or int(d[:4]) == this_year:
            out[int(d[:4])] = v
    return out


def weekly(metric_id, year):
    """Sorted list of (date_str, value) for observations dated within `year`."""
    prefix = "%04d-" % year
    return [(r["date"], r["value"]) for r in _rows_for(metric_id)
            if r["date"].startswith(prefix) and r["value"] is not None]


def latest(metric_id):
    """Most recent value (by date) for a metric, or None."""
    rows = _rows_for(metric_id)
    return rows[-1]["value"] if rows else None


def config():
    """dict key -> value from the config tab. Values are parsed as numbers
    where possible (commas/$ stripped); non-numeric values (e.g. '6.67%',
    'First State Bank') stay strings. If a key repeats, the last row wins."""
    out = {}
    for row in fetch_tab("config"):
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        raw = row.get("value")
        num = _num(raw)
        out[key] = num if num is not None else raw
    return out


def registry():
    """dict metric_id -> full registry row (name, pillar, goal, unit, ...)."""
    out = {}
    for row in fetch_tab("metric_registry"):
        mid = str(row.get("metric_id") or "").strip()
        if mid:
            out[mid] = row
    return out
