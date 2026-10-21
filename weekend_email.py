#!/usr/bin/env python3
"""Hennessey weekend sports email — builds the Friday HTML digest.

Tom, 2026-10-21: "every Friday — email tvhennessey@gmail.com, lauraehennessey@gmail.com,
tomhjr@gmail.com, and marydhennessey@gmail.com a stylized email that shows times and
location of each kid's sporting event on the weekend. Links to the addresses or fields,
distinction between arrival time versus start time, etc. Easy to read and digest.
Include practices as well in a faded way."

HOW IT GETS ITS DATA — the same way the family does.  It renders the scheduler itself
(index.html next to this file) in headless Chromium, lets the page load the shared store
and the repo JSON files, and reads the page's own `visible()` list.  Overrides, hidden and
deleted rows, weekly repeats, cross-feed de-duplication (v13) and cancellations (v15) are
therefore exactly what the site shows; nothing is re-implemented here.

    python3 weekend_email.py [--date YYYY-MM-DD] [--out DIR]

Writes <out>/weekend.html (the email body), <out>/weekend.txt (plain-text alternative),
<out>/weekend.json ({subject, counts, days}) and prints the JSON.  Sending is the
scheduled task's job (Gmail connector, htmlBody=weekend.html).

Window: Friday 3pm → Sunday midnight (America/New_York).  Kids T/E/S only; events whose
type is game/tournament/practice or whose title names a sport.  Rides, school-day items and
the work calendars never qualify.
"""
import argparse, asyncio, datetime as dt, html, json, os, re, sys, urllib.parse
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
KIDS = {"T": ("Tommy", "#1a73e8", "#e8f0fe"), "E": ("Emily", "#d81b60", "#fce4ec"), "S": ("Sophie", "#188038", "#e6f4ea")}
SPORT_RE = re.compile(r"\b(game|practice|tournament|showcase|clinic|scrimmage|soccer|lacrosse|lax|hockey|basketball|swim|track|cross country|xc|training|prospect|tryout|match|league|ski|tennis|golf|baseball|football|ghost games|3d|mass elite|via|bando|wpc|aces|warriors)\b", re.I)
NOT_SPORT_RE = re.compile(r"ride home|carpool|drive to|pickup|pick up|bat mitzvah|birthday|haircut|tutoring|dinner|party|dentist|doctor", re.I)
SKIP_LINK_HOSTS = ("calendar-api.teamsnap.com", "mail.google.com", "www.google.com/calendar", "textdb.dev")
DEFAULT_ARRIVE = {"game": 30, "tournament": 45}


def esc(s):
    return html.escape(str(s or ""), quote=True)


def fmt_t(hm):
    h, m = map(int, hm.split(":"))
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{ap}" if m else f"{h12}{ap}"


def minus(hm, n):
    h, m = map(int, hm.split(":"))
    t = max(0, h * 60 + m - n)
    return f"{t // 60:02d}:{t % 60:02d}"


def arrival(ev):
    """(arrive_hm, how) from the notes; game/tournament default to 30/45 min early."""
    notes = ev.get("notes") or ""
    m = re.search(r"arriv\w*\s+(?:by\s+)?(\d{1,2})(?::(\d\d))?\s*(am|pm)?\b", notes, re.I)
    if m and (m.group(2) or m.group(3)):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap == "pm" and h < 12: h += 12
        if ap == "am" and h == 12: h = 0
        if not ap and h < 7: h += 12          # "arrive 5:30" at a 6pm practice
        return f"{h:02d}:{mi:02d}", "from the team's notes"
    m = re.search(r"arriv\w*\s+(\d{1,3})\s*(?:min|minutes)\s*(?:early|before|prior)", notes, re.I)
    if m:
        return minus(ev["timeStart"], int(m.group(1))), "from the team's notes"
    d = DEFAULT_ARRIVE.get(ev.get("kind"))
    if d and not ev.get("optional"):
        return minus(ev["timeStart"], d), f"{d} min before — usual warm-up"
    return None, ""


def maps_link(loc):
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(loc)


def good_link(link):
    if not link: return ""
    return "" if any(h in link for h in SKIP_LINK_HOSTS) else link


async def harvest(date):
    from playwright.async_api import async_playwright
    fri = date + dt.timedelta(days=(4 - date.weekday()) % 7)   # this Friday, or today if it is Friday
    sat, sun = fri + dt.timedelta(days=1), fri + dt.timedelta(days=2)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1200, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        # the digest only READS — never let the page push a merged store back
        async def route(r):
            if r.request.method == "POST": await r.fulfill(status=200, body="{}")
            else: await r.continue_()
        await pg.route("**/textdb.dev/**", route)
        await pg.goto("file://" + os.path.join(HERE, "index.html"))
        await pg.wait_for_function("window._fam!==undefined && userEvents.length>0", timeout=60000)
        await pg.wait_for_timeout(1500)
        rows = await pg.evaluate("""([d0,d1])=>{
          for(const k of Object.keys(filters.people)) filters.people[k]=true;
          for(const k of Object.keys(filters.types)) filters.types[k]=true;
          for(const k of Object.keys(filters.cals||{})) filters.cals[k]=false;
          rebuild();
          const pad=n=>String(n).padStart(2,'0'), ymd=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
          const out=[];
          for(const e of visible()){
            if(!['T','E','S'].includes(e.person)) continue;
            const day=ymd(e.start); if(day<d0||day>d1) continue;
            const cx=(typeof cxKind==='function'&&cxKind(e))||'';
            const ad=!!e.allDay;
            out.push({id:String(e.id), person:e.person, type:e.type||'', title:e.title||'', day,
              allDay:ad, timeStart:ad?'':`${pad(e.start.getHours())}:${pad(e.start.getMinutes())}`,
              timeEnd:ad?'':`${pad(e.end.getHours())}:${pad(e.end.getMinutes())}`,
              endDay:ymd(e.end), location:e.location||'', link:e.link||'', notes:e.notes||'',
              cancelled:cx==='cancelled', postponed:cx==='postponed',
              optional:/^OPTIONAL:/i.test(e.title||''), source:e.source||'',
              cals:(typeof dupFamily==='function'?dupFamily(e):[e]).map(m=>typeof feedLabel==='function'?feedLabel(m):'')});
          }
          return out; }""", [fri.isoformat(), sun.isoformat()])
        n_user = await pg.evaluate("userEvents.length")
        await b.close()
    if errs:
        print("PAGE ERRORS:", errs, file=sys.stderr)
    return fri, sat, sun, rows, n_user


def qualifies(ev):
    if ev["person"] not in KIDS: return False
    if ev["type"] == "potential" or "(potential)" in ev["title"]: return False   # unconfirmed maybes stay on the Tracking tab
    t = ev["title"]
    if NOT_SPORT_RE.search(t): return False
    if ev["type"] in ("game", "tournament", "practice"): return True
    return bool(SPORT_RE.search(t)) and ev["type"] in ("family", "")


def kind_of(ev):
    t = ev["title"].lower()
    if re.search(r"clinic|prospect day|id day", t): return "game"          # a college clinic is an event, not a faded practice
    if ev["type"] == "practice" or re.search(r"\bpractice|training|session|via lacrosse|compete|athletic performance|speed and agility|bando\b", t): return "practice"
    if ev["type"] == "tournament" or re.search(r"tournament|showcase|ghost games|bowl|classic|championship", t): return "tournament"
    return "game"


def clean_title(ev):
    t = re.sub(r"^(CANCELLED|POSTPONED|OPTIONAL):\s*", "", ev["title"], flags=re.I)
    t = re.sub(r"^(Tommy|Emily|Sophie|[TES])\s*[—\-–:]\s*", "", t)
    return t.strip()


def build(fri, sat, sun, rows):
    evs = [e for e in rows if qualifies(e)]
    # Friday: only the late afternoon / evening (the email goes out Friday morning)
    evs = [e for e in evs if not (e["day"] == fri.isoformat() and (e["allDay"] or e["timeStart"] < "15:00"))]
    for e in evs:
        e["kind"] = kind_of(e)
        e["ctitle"] = clean_title(e)
        e["arrive"], e["arrive_how"] = (arrival(e) if (not e["allDay"] and e["kind"] != "practice" and not e["cancelled"]) else (None, ""))
    evs.sort(key=lambda e: (e["day"], e["allDay"] and "" or (e["arrive"] or e["timeStart"]), e["person"]))
    # an all-morning block (Laura's "Mass Elite Purple @ Ghost Games 8:00/9:30/11:00") that wraps
    # two or more of the kid's own games is an UMBRELLA: no arrival of its own, no overlap flags
    STOP = {"mass", "elite", "game", "games", "practice", "the", "and", "vs", "girls", "boys", "tommy", "emily", "sophie", "fc", "u13", "u11", "club", "town"}
    toks = lambda e: {w for w in re.findall(r"[a-z0-9']{3,}", e["ctitle"].lower()) if w not in STOP}
    for a in evs:
        inside = [b for b in evs if b is not a and b["person"] == a["person"] and b["day"] == a["day"] and not a["allDay"] and not b["allDay"]
                  and a["timeStart"] <= b["timeStart"] and b["timeEnd"] <= a["timeEnd"]]
        a["umbrella"] = len(inside) >= 2
        if a["umbrella"]: a["arrive"], a["arrive_how"] = None, ""
    # once you are at a tournament you are there: only the FIRST game of the day in a set of
    # same-tournament games carries an arrival time; the later ones just show their start
    for a_ in evs:
        for b_ in evs:
            if a_ is b_ or a_["person"] != b_["person"] or a_["day"] != b_["day"] or not a_.get("arrive") or not b_.get("arrive"): continue
            if len(toks(a_) & toks(b_)) >= 2 and b_["timeStart"] < a_["timeStart"]:
                a_["arrive"], a_["arrive_how"] = None, ""
    # same-kid overlaps → flag both (not within one tournament's own games, not optional sessions)
    for a in evs:
        for b in evs:
            if a is b or a["person"] != b["person"] or a["day"] != b["day"] or a["allDay"] or b["allDay"]: continue
            if a["cancelled"] or b["cancelled"] or a["optional"] or b["optional"] or a["umbrella"] or b["umbrella"]: continue
            if len(toks(a) & toks(b)) >= 2: continue            # two games of the same tournament
            if a["timeStart"] < b["timeEnd"] and b["timeStart"] < a["timeEnd"]:
                a.setdefault("overlaps", []).append(b["ctitle"])
    days = [(fri, "Friday evening"), (sat, "Saturday"), (sun, "Sunday")]
    day_lists = [(d, lbl, [e for e in evs if e["day"] == d.isoformat()]) for d, lbl in days]
    day_lists = [(d, lbl, l) for d, lbl, l in day_lists if l or d.weekday() in (5, 6)]
    counts = {k: sum(1 for e in evs if e["person"] == k and e["kind"] != "practice" and not e["cancelled"] and not e.get("umbrella")) for k in KIDS}
    pr = {k: sum(1 for e in evs if e["person"] == k and e["kind"] == "practice" and not e["cancelled"]) for k in KIDS}
    subject = f"Weekend sports — Sat {sat:%b %-d} & Sun {sun:%b %-d}: " + ", ".join(
        f"{KIDS[k][0]} {counts[k]}" for k in KIDS if counts[k] or pr[k]) if any(counts.values()) or any(pr.values()) else f"Weekend sports — Sat {sat:%b %-d} & Sun {sun:%b %-d}: nothing on the calendar"
    return evs, day_lists, counts, pr, subject


SEEN_TIPS = set()


def card(e):
    name, hex_, light = KIDS[e["person"]]
    practice = e["kind"] == "practice"
    cx = e["cancelled"] or e["postponed"]
    op = "0.55" if (practice or e["optional"]) and not cx else "1"
    badge = {"game": "GAME", "tournament": "TOURNAMENT", "practice": "PRACTICE"}[e["kind"]]
    if re.search(r"clinic|prospect", e["ctitle"], re.I): badge = "CLINIC"
    if e.get("umbrella"): badge = "TOURNAMENT DAY"
    if e["optional"]: badge = "OPTIONAL " + badge
    if e["cancelled"]: badge = "CANCELLED"
    if e["postponed"]: badge = "POSTPONED"
    bcol = "#b3261e" if cx else ("#9aa0a6" if practice else hex_)
    tstyle = "text-decoration:line-through;color:#80868b;" if cx else ""
    # time block
    if e["allDay"]:
        when = '<div style="font-size:15px;font-weight:700;color:#202124;">All day</div>'
    elif e["arrive"] and e["arrive"] != e["timeStart"]:
        when = (f'<div style="font-size:12px;letter-spacing:.4px;color:#5f6368;text-transform:uppercase;font-weight:700;">Arrive</div>'
                f'<div style="font-size:22px;font-weight:800;color:{hex_};line-height:1.1;">{fmt_t(e["arrive"])}</div>'
                f'<div style="font-size:12px;color:#5f6368;margin-top:4px;">Starts <b style="color:#202124;">{fmt_t(e["timeStart"])}</b> · ends {fmt_t(e["timeEnd"])}</div>')
    else:
        when = (f'<div style="font-size:12px;letter-spacing:.4px;color:#5f6368;text-transform:uppercase;font-weight:700;">{"Starts" if practice else "Time"}</div>'
                f'<div style="font-size:22px;font-weight:800;color:{"#80868b" if practice else hex_};line-height:1.1;">{fmt_t(e["timeStart"])}</div>'
                f'<div style="font-size:12px;color:#5f6368;margin-top:4px;">until {fmt_t(e["timeEnd"])}</div>')
    loc = ""
    if e["location"]:
        loc = (f'<div style="margin-top:6px;font-size:13px;color:#3c4043;">📍 <a href="{esc(maps_link(e["location"]))}" '
               f'style="color:#1a73e8;text-decoration:underline;">{esc(e["location"])}</a></div>')
    link = good_link(e["link"])
    extra = ""
    if link:
        host = re.sub(r"^https?://(www\.)?", "", link).split("/")[0]
        extra += f'<a href="{esc(link)}" style="color:#1a73e8;text-decoration:underline;font-size:12.5px;">Schedule page ({esc(host)})</a>'
    if e.get("overlaps"):
        extra += (f'<div style="margin-top:6px;font-size:12.5px;color:#b06000;background:#fef7e0;border-radius:6px;padding:4px 8px;display:inline-block;">'
                  f'⚠️ Overlaps: {esc("; ".join(e["overlaps"]))}</div>')
    # one useful line from the notes: uniform / bring / pack
    tip = ""
    m = re.search(r"(uniform[^.]*\.|bring[^.]*\.|pack[^.]*\.|no team tent[^.]*\.)", e["notes"], re.I)
    if m and not practice and (e["person"], e["day"], m.group(1)) not in SEEN_TIPS:
        SEEN_TIPS.add((e["person"], e["day"], m.group(1)))
        tip = f'<div style="margin-top:6px;font-size:12.5px;color:#5f6368;">{esc(m.group(1).strip())}</div>'
    return f"""
<tr><td style="padding:0 0 10px 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-left:5px solid {bcol};background:{"#f8f9fa" if practice else light};border-radius:10px;opacity:{op};">
<tr>
<td width="118" valign="top" style="padding:12px 10px 12px 14px;">{when}</td>
<td valign="top" style="padding:12px 14px 12px 4px;">
<div style="font-size:11px;font-weight:800;letter-spacing:.6px;color:{bcol};">{esc(name).upper()} · {badge}</div>
<div style="font-size:15.5px;font-weight:700;color:#202124;margin-top:3px;line-height:1.3;{tstyle}">{esc(e["ctitle"])}</div>
{loc}{tip}{('<div style="margin-top:6px;">' + extra + '</div>') if extra else ''}
</td></tr></table></td></tr>"""


def render_html(fri, sat, sun, day_lists, counts, pr, evs):
    glance = "".join(
        f'<td align="center" style="padding:8px 4px;">'
        f'<div style="width:38px;height:38px;line-height:38px;border-radius:50%;background:{KIDS[k][1]};color:#fff;font-weight:800;font-size:16px;margin:0 auto;">{KIDS[k][0][0]}</div>'
        f'<div style="font-size:13px;font-weight:700;color:#202124;margin-top:5px;">{KIDS[k][0]}</div>'
        f'<div style="font-size:12px;color:#5f6368;">{counts[k]} game{"s" if counts[k] != 1 else ""}{(" · " + str(pr[k]) + " practice" + ("s" if pr[k] != 1 else "")) if pr[k] else ""}</div></td>'
        for k in KIDS)
    sections = ""
    for d, lbl, lst in day_lists:
        sections += (f'<tr><td style="padding:18px 0 8px 0;"><div style="font-size:18px;font-weight:800;color:#202124;">{lbl}</div>'
                     f'<div style="font-size:13px;color:#5f6368;">{d:%B %-d}</div></td></tr>')
        if lst:
            sections += "".join(card(e) for e in lst)
        else:
            sections += '<tr><td style="padding:0 0 10px 0;"><div style="background:#f8f9fa;border-radius:10px;padding:14px;color:#5f6368;font-size:14px;">Nothing on the calendar.</div></td></tr>'
    legend = ('<div style="font-size:12px;color:#80868b;line-height:1.6;">'
              '<b>Arrive</b> is when to be there; <b>Starts</b> is kickoff. Arrival comes from the team&rsquo;s own notes when they gave one, otherwise 30 min before a game and 45 before a tournament. '
              'Practices and optional sessions are shown faded. Tap an address for directions. '
              f'Built from the family scheduler on {dt.datetime.now(ET):%a %b %-d, %-I:%M %p} — if something moved after that, the scheduler is right.</div>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Weekend sports</title></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#202124;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;"><tr><td align="center" style="padding:16px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;">
<tr><td style="padding:0 0 6px 0;">
<div style="font-size:12px;font-weight:800;letter-spacing:1px;color:#7c3aed;text-transform:uppercase;">Hennessey weekend</div>
<div style="font-size:26px;font-weight:800;color:#202124;line-height:1.15;margin-top:2px;">Sat {sat:%b %-d} &amp; Sun {sun:%b %-d}</div>
</td></tr>
<tr><td style="padding:10px 0 4px 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9fa;border-radius:12px;"><tr>{glance}</tr></table></td></tr>
{sections}
<tr><td style="padding:16px 0 0 0;border-top:1px solid #e8eaed;">{legend}
<div style="margin-top:8px;font-size:12px;"><a href="https://sked.coalition.ventures" style="color:#1a73e8;">Open the scheduler</a></div></td></tr>
</table></td></tr></table></body></html>"""


def render_text(sat, sun, day_lists):
    out = [f"HENNESSEY WEEKEND — Sat {sat:%b %-d} & Sun {sun:%b %-d}", ""]
    for d, lbl, lst in day_lists:
        out.append(f"{lbl.upper()} ({d:%b %-d})")
        if not lst: out.append("  Nothing on the calendar.")
        for e in lst:
            name = KIDS[e["person"]][0]
            t = "all day" if e["allDay"] else (f"arrive {fmt_t(e['arrive'])}, starts {fmt_t(e['timeStart'])}" if e["arrive"] and e["arrive"] != e["timeStart"] else f"{fmt_t(e['timeStart'])}–{fmt_t(e['timeEnd'])}")
            tag = "CANCELLED " if e["cancelled"] else ("(practice) " if e["kind"] == "practice" else "")
            out.append(f"  {name}: {tag}{e['ctitle']} — {t}" + (f" — {e['location']}" if e["location"] else ""))
        out.append("")
    out.append("Arrive = be there; Starts = kickoff. Scheduler: https://sked.coalition.ventures")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="any date in the target week (default: today ET)")
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(ET).date()
    fri, sat, sun, rows, n_user = asyncio.run(harvest(today))
    if n_user < 100:
        print(json.dumps({"error": f"store looked empty ({n_user} user_events) — refusing to send a blank digest"})); sys.exit(2)
    evs, day_lists, counts, pr, subject = build(fri, sat, sun, rows)
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "weekend.html"), "w").write(render_html(fri, sat, sun, day_lists, counts, pr, evs))
    open(os.path.join(a.out, "weekend.txt"), "w").write(render_text(sat, sun, day_lists))
    summ = {"subject": subject, "friday": fri.isoformat(), "saturday": sat.isoformat(), "sunday": sun.isoformat(),
            "games": counts, "practices": pr, "store_user_events": n_user,
            "events": [{"day": e["day"], "kid": KIDS[e["person"]][0], "kind": e["kind"], "title": e["ctitle"], "arrive": e["arrive"],
                        "start": e["timeStart"], "end": e["timeEnd"], "location": e["location"], "cancelled": e["cancelled"],
                        "overlaps": e.get("overlaps", [])} for e in evs]}
    open(os.path.join(a.out, "weekend.json"), "w").write(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
