/**
 * MCC Connection KPMs — monthly write-back endpoint (Google Apps Script Web App)
 *
 * Purpose: let the weekly Connections refresh job auto-fill the Planning Center
 * Profile Data block of the "2026 KPMs" tab from PCO, so the KPM sheet's history
 * extends automatically each month (no manual entry).
 *
 * ── ONE-TIME SETUP ────────────────────────────────────────────────────────────
 * 1. Open the "MCC Connection KPMs" sheet → Extensions → Apps Script.
 * 2. Paste this whole file in (replace any Code.gs contents). Save.
 * 3. Edit SECRET below to a long random string of your choosing.
 * 4. Deploy → New deployment → type "Web app".
 *      - Execute as: Me (your account)
 *      - Who has access: "Anyone" (the SECRET is what protects it)
 *    Deploy, authorize, and COPY the Web app URL (…/exec).
 * 5. Give Sam that URL + the SECRET (Sam stores them in the repo config, never in
 *    the public site) and Sam wires the weekly job to POST to it once a month.
 *
 * The job POSTs JSON like:
 *   { "secret":"…", "tab":"2026 KPMs", "month":"May",
 *     "metrics": { "active":1490,"adults":1010,"students":152,"kids":328,
 *                  "households":455,"life_group_members":405,"life_care_groups":580,
 *                  "total_groups_students":645,"serving_sundays":360,"serving_anywhere":415 } }
 * Only the metrics present are written; the month row is matched by label, so no
 * hardcoded row numbers — resilient if the layout shifts.
 */

var SECRET = "CHANGE-ME-to-a-long-random-string";

// incoming metric key -> header label substring in the profile block
var COLMAP = {
  active: "active profiles",
  adults: "active adults",
  students: "active students",
  kids: "active kids",
  households: "unique households",
  life_group_members: "unique mem of a life group",
  life_care_groups: "life / class / care",
  total_groups_students: "total groups and students",
  serving_sundays: "serving sundays",
  serving_anywhere: "serving anywhere"
};

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (body.secret !== SECRET) return json_({ ok: false, error: "bad secret" });

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(body.tab || "2026 KPMs");
    if (!sheet) return json_({ ok: false, error: "tab not found" });

    var values = sheet.getDataRange().getValues();
    var norm = function (v) { return String(v == null ? "" : v).trim().toLowerCase(); };

    // Find the profile-block header row: the row containing "active profiles".
    var hRow = -1, hCol = -1;
    for (var r = 0; r < values.length && hRow < 0; r++) {
      for (var c = 0; c < values[r].length; c++) {
        if (norm(values[r][c]) === "active profiles") { hRow = r; hCol = c; break; }
      }
    }
    if (hRow < 0) return json_({ ok: false, error: "profile header not found" });

    var monthCol = hCol - 1; // "Month" column sits just left of ACTIVE profiles
    var header = values[hRow];

    // Map each requested metric to its column index via header label.
    var metricCol = {};
    for (var key in COLMAP) {
      for (var cc = 0; cc < header.length; cc++) {
        if (norm(header[cc]).indexOf(COLMAP[key]) === 0 || norm(header[cc]) === COLMAP[key]) { metricCol[key] = cc; break; }
        if (norm(header[cc]).indexOf(COLMAP[key]) !== -1) { metricCol[key] = cc; break; }
      }
    }

    // Find the month row within the block (match first 3 letters, e.g. "Jun"/"June").
    var want = norm(body.month).substring(0, 3);
    var targetRow = -1;
    for (var rr = hRow + 1; rr < values.length; rr++) {
      var label = norm(values[rr][monthCol]).substring(0, 3);
      if (["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"].indexOf(label) === -1) break; // left the block
      if (label === want) { targetRow = rr; break; }
    }
    if (targetRow < 0) return json_({ ok: false, error: "month row not found: " + body.month });

    var written = {};
    for (var mk in body.metrics) {
      if (metricCol[mk] == null) continue;
      var val = body.metrics[mk];
      if (val === null || val === "") continue;
      sheet.getRange(targetRow + 1, metricCol[mk] + 1).setValue(val);
      written[mk] = val;
    }
    return json_({ ok: true, tab: sheet.getName(), month: body.month, row: targetRow + 1, written: written });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
