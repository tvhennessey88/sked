#!/usr/bin/env python3
"""
Hennessey Family Scheduler — archive past events out of the live sync store.

WHY (Tom, 2026-10-30): "i think you are deleting events that are 7 days prior. that
feels too short. Ideally I'd like the record to be there."  Two things were losing
history: work_sync.py rewrites `tom_work` every morning with a today-7 window, so a
work trip vanished a week later; and the live textdb store has to stay under ~700 KB,
which forced a prune of past family events on 2026-10-28.

WHAT THIS DOES.  Past rows are copied into monthly files in this repo —
archive/YYYY-MM.json — which the site loads on demand when someone scrolls back.
Every field is kept (title, times, location, link, notes, guests, join link), so the
record is a real event, not a screenshot.  Then:
  * family rows (user_events) whose last day is more than FAMILY_DAYS ago are removed
    from the live store and tombstoned in deleted_user, so no phone's cached copy can
    put them back and no feed re-adds them;
  * work / forge rows (tom_work, tom_forge) dated before today are archived but left in
    the store — work_sync.py owns that key and drops them on its own schedule.  This is
    why the task runs DAILY, before the 5:45am ET work sync: a row is captured well
    inside its 7-day window.
  * a `repeat` row (weekly series) is never removed; its past occurrences are written
    to the archive as instances (id `<root>@YYYY-MM-DD`) so the history survives if
    the series is ever removed.  The site hides an archived instance while its root is
    still live, so nothing is drawn twice.
  * the family's own edits (store `overrides`) are baked into the archived copy, so the
    archive says what the calendar actually showed.

Deterministic, idempotent, stdlib only.  Default is a DRY RUN; --write edits the files
and POSTs the store (re-read immediately before the POST, verified after).

    python3 archive.py [--write] [--family-days 30] [--repo DIR] [--store-file F]
"""
import argparse, datetime as dt, json, os, re, sys, urllib.request, zoneinfo

STORE = "https://textdb.dev/api/data/hsked-1578268b-3ae8-4007-b940-9b27e5be8917"
TZ = zoneinfo.ZoneInfo("America/New_York")
FAMILY_DAYS = 30


def get(url):
    with urllib.request.urlopen(url + ("&" if "?" in url else "?") + "t=" + str(int(dt.datetime.now().timestamp())), timeout=60) as r:
        return r.read().decode()


def ymd(d): return d.strftime("%Y-%m-%d")


def parse(s):
    return dt.date.fromisoformat(str(s)[:10])


def last_day(e):
    """The last calendar day a row occupies."""
    try:
        return parse(e.get("end") or e.get("start"))
    except Exception:
        try: return parse(e["start"])
        except Exception: return None


TOKEN_Q = re.compile(r"([?&])(token|key|k|auth|access_token|sig)=[^&#\s]*", re.I)


def scrub(url):
    """The repo is public; a feed URL that carries a token stays out of it.  The live
    store still has the full link, so the site shows the real thing for live rows."""
    if not url or "?" not in str(url): return url
    u = TOKEN_Q.sub(r"\1\2=REDACTED", str(url))
    return re.sub(r"[?&](\w+)=REDACTED(&|$)", lambda m: "?" if m.group(2) else "", u).rstrip("?&")


def bake(e, overrides):
    """Apply the site's override (the family's edit) so the archive matches the calendar."""
    o = overrides.get(str(e.get("id")))
    if not o or not isinstance(o.get("f"), dict) or not o["f"]:
        r = dict(e); r["link"] = scrub(r.get("link")); return r
    r = {**e, **o["f"]}
    r["link"] = scrub(r.get("link"))
    r["_edited"] = o.get("ts") or 1
    if e.get("status") and "status" not in o["f"]:
        r["status"] = e["status"]
    return r


def expand(e, upto):
    """Instances of a `repeat` row dated <= upto (inclusive)."""
    rep = e.get("repeat") or {}
    days = set(rep.get("days") or [])
    if not days: return []
    try:
        start = parse(e["start"]); until = parse(rep.get("until") or ymd(upto))
    except Exception:
        return []
    until = min(until, upto)
    skip = set(rep.get("except") or [])
    out, d, n = [], start, 0
    span = 0
    try: span = (parse(e.get("end") or e["start"]) - start).days
    except Exception: pass
    while d <= until and n < 600:
        # JS getDay(): Sunday=0; Python weekday(): Monday=0
        if ((d.weekday() + 1) % 7) in days and ymd(d) not in skip:
            inst = {k: v for k, v in e.items() if k != "repeat"}
            inst["id"] = f"{e['id']}@{ymd(d)}"
            inst["_root"] = e["id"]
            inst["start"] = ymd(d); inst["end"] = ymd(d + dt.timedelta(days=span))
            out.append(inst); n += 1
        d += dt.timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--family-days", type=int, default=FAMILY_DAYS)
    ap.add_argument("--repo", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--store-file", help="read the store from a file instead of textdb (never POSTs)")
    ap.add_argument("--extra", action="append", default=[], help="extra JSON file(s) of rows to fold into the archive (e.g. an old backup); never touches the store")
    ap.add_argument("--today", help="YYYY-MM-DD override, for tests")
    a = ap.parse_args()

    today = parse(a.today) if a.today else dt.datetime.now(TZ).date()
    fam_cut = today - dt.timedelta(days=a.family_days)   # family rows ending BEFORE this go
    work_cut = today                                      # work rows ending BEFORE today go

    raw = open(a.store_file).read() if a.store_file else get(STORE)
    store = json.loads(raw)
    if isinstance(store, str): store = json.loads(store)
    overrides = store.get("overrides") or {}
    deleted = set(map(str, store.get("deleted_user") or []))
    hidden = set(map(str, store.get("hidden") or []))

    to_archive = []   # rows headed for archive files
    remove_ids = set()  # family ids to drop from user_events + tombstone

    for e in store.get("user_events") or []:
        if not e or not e.get("id") or not e.get("start"): continue
        if e.get("repeat"):
            for inst in expand(e, fam_cut - dt.timedelta(days=1)):
                inst["_cal"] = "family"; to_archive.append(bake(inst, overrides))
            continue
        ld = last_day(e)
        if ld and ld < fam_cut:
            r = bake(e, overrides); r["_cal"] = "family"; to_archive.append(r); remove_ids.add(str(e["id"]))

    for key, cal in (("tom_work", "work"), ("tom_forge", "forge")):
        for e in store.get(key) or []:
            if not e or not e.get("start"): continue
            if not e.get("id"): e = {**e, "id": f"{'tw' if cal=='work' else 'tf'}-{e['start']}-{abs(hash(e.get('title','')))%100000}"}
            if e.get("repeat"):
                for inst in expand(e, work_cut - dt.timedelta(days=1)):
                    inst["_cal"] = cal; to_archive.append(bake(inst, overrides))
                continue
            ld = last_day(e)
            if ld and ld < work_cut:
                r = bake(e, overrides); r["_cal"] = cal; to_archive.append(r)

    for f in a.extra:
        rows = json.load(open(f))
        if isinstance(rows, dict): rows = rows.get("user_events") or rows.get("rows") or []
        for e in rows:
            if not e or not e.get("id") or not e.get("start"): continue
            if e.get("repeat"):
                for inst in expand(e, fam_cut - dt.timedelta(days=1)):
                    inst["_cal"] = "family"; to_archive.append(bake(inst, overrides))
                continue
            ld = last_day(e)
            if ld and ld < today:
                r = bake(e, overrides); r.setdefault("_cal", "work" if str(e["id"]).startswith("tw-") else "forge" if str(e["id"]).startswith("tf-") else "family")
                to_archive.append(r)

    # ---- merge into archive/YYYY-MM.json (one file per month of the row's START) ----
    adir = os.path.join(a.repo, "archive"); os.makedirs(adir, exist_ok=True)
    by_month = {}
    for r in to_archive:
        by_month.setdefault(str(r["start"])[:7], []).append(r)
    changed_files, added_total, updated_total = [], 0, 0
    for mon, rows in sorted(by_month.items()):
        path = os.path.join(adir, f"{mon}.json")
        cur = {"month": mon, "rows": []}
        if os.path.exists(path):
            try: cur = json.load(open(path))
            except Exception: pass
        idx = {str(x["id"]): x for x in cur.get("rows") or [] if x and x.get("id")}
        added = updated = 0
        for r in rows:
            k = str(r["id"]); old = idx.get(k)
            if old is None: idx[k] = r; added += 1
            elif (r.get("ts") or 0) > (old.get("ts") or 0) or (r.get("_edited") or 0) > (old.get("_edited") or 0):
                idx[k] = r; updated += 1
        if added or updated:
            cur["rows"] = sorted(idx.values(), key=lambda x: (str(x.get("start")), str(x.get("timeStart") or ""), str(x["id"])))
            cur["month"] = mon; cur["updated"] = ymd(today); cur["count"] = len(cur["rows"])
            changed_files.append((path, cur)); added_total += added; updated_total += updated
        print(f"archive/{mon}.json: {len(idx)} rows (+{added} new, ~{updated} updated)")

    months = sorted({os.path.basename(p)[:7] for p in (os.listdir(adir) if os.path.isdir(adir) else []) if p.endswith(".json") and p[:4].isdigit()} | set(by_month))
    index = {"months": months, "updated": ymd(today), "family_days": a.family_days,
             "note": "Past events archived out of the live store; the site loads these on demand. Read-only history."}

    print(f"today {ymd(today)} | family rows ending before {ymd(fam_cut)}: {len(remove_ids)} leave the store | work/forge rows before today archived: {sum(1 for r in to_archive if r.get('_cal') in ('work','forge'))} | archive rows touched: {added_total} new, {updated_total} updated")
    for i in sorted(remove_ids)[:15]: print("  -", i)
    if len(remove_ids) > 15: print(f"  … and {len(remove_ids)-15} more")

    if not a.write:
        print("(dry run — nothing written)"); return

    for path, cur in changed_files:
        with open(path, "w") as f: json.dump(cur, f, separators=(",", ":"), ensure_ascii=False)
    with open(os.path.join(adir, "index.json"), "w") as f: json.dump(index, f, indent=1)
    print(f"wrote {len(changed_files)} archive file(s) + archive/index.json")

    if a.store_file or not remove_ids:
        print("store unchanged" if not remove_ids else "store NOT written (reading from a file)"); return

    # re-read right before the POST so a concurrent feed write is not clobbered
    live = json.loads(get(STORE))
    if isinstance(live, str): live = json.loads(live)
    before = len(live.get("user_events") or [])
    live["user_events"] = [e for e in live.get("user_events") or [] if str(e.get("id")) not in remove_ids]
    live["deleted_user"] = sorted(set(map(str, live.get("deleted_user") or [])) | remove_ids)
    live["archive_state"] = {"last_run": ymd(today), "months": months, "removed": len(remove_ids)}
    live["v"] = int(dt.datetime.now().timestamp() * 1000)
    body = json.dumps(live, separators=(",", ":")).encode()
    req = urllib.request.Request(STORE, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r: r.read()
    chk = json.loads(get(STORE))
    if isinstance(chk, str): chk = json.loads(chk)
    assert len(chk["user_events"]) == len(live["user_events"]), "verify failed: count mismatch after POST"
    assert set(chk.keys()) >= set(live.keys()), "verify failed: keys lost"
    assert remove_ids <= set(map(str, chk["deleted_user"])), "verify failed: tombstones missing"
    print(f"Store written and verified: user_events {before} -> {len(live['user_events'])}, {len(body)//1024} KB")


if __name__ == "__main__":
    main()
