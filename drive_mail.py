#!/usr/bin/env python3
"""drive_mail.py — the sending half of v33's "Email Assignments" (Tom, 2026-10-27).

The scheduler page composes a styled HTML email of one driver's upcoming legs and queues it
in the store under `drive_mail` = {id: {who, to[], cc[], subject, html, text, n, ts, status}}.
This script is what the hourly "Sked: drive assignment emails" task runs:

  python3 drive_mail.py --list            # writes drive_mail/<id>.html and .txt for every
                                          # PENDING entry and prints them as JSON
  python3 drive_mail.py --mark <id> sent  # after a successful Gmail send
  python3 drive_mail.py --mark <id> failed --error "why"

Only the `drive_mail` entries named are touched; every other key in the store is carried
through untouched (the store is shared with every feed and with Tom's work scheduler).
A POST is verified by re-reading the document. Standard library only.
"""
import argparse, json, os, sys, time, urllib.request

STORE = "https://textdb.dev/api/data/hsked-1578268b-3ae8-4007-b940-9b27e5be8917"
OUT = "drive_mail"


def get():
    req = urllib.request.Request(STORE + "?t=%d" % int(time.time() * 1000), headers={"Cache-Control": "no-store"})
    raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    doc = json.loads(raw)
    if isinstance(doc, str):
        doc = json.loads(doc)
    if not isinstance(doc, dict) or len(doc.get("user_events") or []) < 100:
        sys.exit("store looks empty or wrong — refusing to touch it")
    return doc


def post(doc):
    body = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(STORE, data=body, method="POST", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=120).read()
    back = get()
    if back.get("drive_mail") != doc.get("drive_mail"):
        sys.exit("verify failed: drive_mail did not round-trip")


def cmd_list():
    doc = get()
    dm = doc.get("drive_mail") or {}
    os.makedirs(OUT, exist_ok=True)
    out = []
    for k, v in sorted(dm.items(), key=lambda kv: (kv[1] or {}).get("ts", 0)):
        if not v or v.get("status") != "pending":
            continue
        hp, tp = os.path.join(OUT, k + ".html"), os.path.join(OUT, k + ".txt")
        open(hp, "w", encoding="utf-8").write(v.get("html", ""))
        open(tp, "w", encoding="utf-8").write(v.get("text", ""))
        out.append({"id": k, "who": v.get("who"), "to": v.get("to"), "cc": v.get("cc"), "subject": v.get("subject"),
                    "legs": v.get("n"), "queued_ts": v.get("ts"), "html_file": hp, "text_file": tp})
    print(json.dumps(out, indent=1, ensure_ascii=False))
    all_status = {}
    for v in dm.values():
        all_status[(v or {}).get("status", "?")] = all_status.get((v or {}).get("status", "?"), 0) + 1
    print("# drive_mail entries by status:", json.dumps(all_status), file=sys.stderr)


def cmd_mark(mid, status, error):
    doc = get()
    dm = doc.setdefault("drive_mail", {})
    if mid not in dm:
        sys.exit("no drive_mail entry %s" % mid)
    now = int(time.time() * 1000)
    dm[mid]["status"] = status
    dm[mid]["ts"] = now
    if status == "sent":
        dm[mid]["sentAt"] = now
        dm[mid].pop("error", None)
    elif error:
        dm[mid]["error"] = error[:300]
    doc["v"] = now
    post(doc)
    print("marked", mid, status)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--mark", nargs=2, metavar=("ID", "STATUS"))
    ap.add_argument("--error", default="")
    a = ap.parse_args()
    if a.list:
        cmd_list()
    elif a.mark:
        mid, st = a.mark
        if st not in ("sent", "failed"):
            sys.exit("status must be sent or failed")
        cmd_mark(mid, st, a.error)
    else:
        ap.print_help()
