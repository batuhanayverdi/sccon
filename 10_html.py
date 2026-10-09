# -*- coding: utf-8 -*-
"""
10_html.py  -  SCC_Plan.xlsx'ten interaktif, kendi kendini kaydeden bir planlayici HTML uretir.

Girdi : data/SCC_Plan.xlsx (09_plan.py)
Cikti : data/SCC_Planner.html  (tek dosya, internet gerekmez, telefonda da calisir)

HTML'de:
  - Talks: once Top (relevance 3), gun/konu/arama filtresi, "Merken", "Ich gehe", not
  - Stände: Pflicht/optional/rakip, hall filtresi, "besucht" isareti, not
  - Personen: onerilen gorusmeler, tum katilimcilar, speaker'lar; "gesprochen" isareti, not
  - Mein Plan: secilen talk'lar gun gun (cakisma uyarisi), standlar rota sirasiyla, kisiler, kendi eklediklerin
  - "+ Eintrag": kendi termin / kisi / gorev ekleme
Kayit:
  - Her degisiklik otomatik olarak tarayicida saklanir (ayni bilgisayar + ayni tarayici).
  - "Als Datei speichern": notlar ICINE GOMULU yeni bir HTML indirir -> bunu ekibe gonderebilirsin.
  - "Import": bir meslektasin kaydettigi HTML/JSON dosyasini kendi planinla birlestirir.
Pipeline tekrar calisip bu dosya yeniden uretilse bile tarayicidaki notlar kaybolmaz (ID'ler sabit).
"""

import json
import re
from datetime import datetime

import pandas as pd

from scc_common import DATA, SHEETS, TEAM_SECTOR, prio_internal, print, unlabel

SRC = DATA / "SCC_Plan.xlsx"

# SCC platformundaki sayfa linkleri. {slug} = baslik/isim, {id} = platform ID'si.
# Linkler yanlis sayfaya gidiyorsa sitede bir vortrag/aussteller sayfasi acip adresini buraya uyarlayin.
TALK_URL = "https://online.smartcountry.berlin/eventdate/eventdate-{slug}--{id}"
BOOTH_URL = "https://online.smartcountry.berlin/company/company-{slug}--{id}"
OUT = DATA / "SCC_Planner.html"

KW = re.compile(r"(?i)identit|\biam\b|\bidm\b|\bsso\b|single sign|keycloak|opendesk|zendis|open.?source|schul|"
                r"school|eudi|wallet|bundid|nutzerkonto|deutschland.?stack|germany stack|verzeichnis|directory|"
                r"arbeitsplatz|workplace|souver|sovereign")


def num(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def s(v):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def n(v):
    """Tam sayi metni: 627.0 -> "627", bos -> "" """
    try:
        return str(int(round(float(v))))
    except (TypeError, ValueError):
        return ""


DAYS = {"2026-10-13": "Dienstag, 13.10.", "2026-10-14": "Mittwoch, 14.10.", "2026-10-15": "Donnerstag, 15.10."}


def build_static(talks, booths, people):
    """JavaScript calismayan onizlemeler (iPhone Dosyalar/Mail, Outlook-App...) icin sade, salt okunur gorunum.
    JS calisinca bu icerik interaktif surumle degistirilir."""
    from html import escape as e
    out = ['<div class="nojs-only"><p class="notice">Nur-Lese-Ansicht: Diese Vorschau führt keine Skripte aus. '
           'Zum Merken, für Notizen und den Kalender die Datei im Browser öffnen (Chrome/Safari/Edge, am Laptop).</p>',
           '<p><a href="#s-talks">Vorträge</a> · <a href="#s-booths">Stände</a> · <a href="#s-people">Kontakte</a></p>',
           '<h2 id="s-talks">Vorträge (Prio 1)</h2>']
    seen = set()
    t3 = sorted([t for t in talks if t["rel"] == 3], key=lambda t: (t["d"], t["s"]))
    for d in DAYS:
        rows = []
        for t in t3:
            k = (t["t"], t["host"], t["spk"])
            if t["d"] != d or k in seen:
                continue
            seen.add(k)
            rows.append(f'<li><b>{e(t["s"])}–{e(t["e"])}</b> · {e(t["loc"])}<br>{e(t["t"])}</li>')
        if rows:
            out.append(f"<h3>{DAYS[d]}</h3><ul class='plain'>" + "".join(rows) + "</ul>")
    out.append('<h2 id="s-booths">Stände (Prio 1)</h2><ul class="plain">')
    def sk(b):
        return [int(n) for n in re.findall(r"\d+", b["st"])] or [999]
    for b in sorted([b for b in booths if b["p"] == 3], key=sk):
        out.append(f'<li><b>{e(b["st"])}</b> · {e(b["n"])}<br><span class="muted">{e(b["goal"])}'
                   f'{" · " + e(b["q"]) if b["q"] else ""}</span></li>')
    out.append('</ul><h2 id="s-people">Empfohlene Kontakte (Fachebene)</h2><ul class="plain">')
    for p in [p for p in people if p.get("rec") == 1]:
        role = p["pos"] or p["lih"]
        out.append(f'<li><b>{e(p["n"])}</b> · {e(role)}{" · " if role else ""}{e(p["org"])}'
                   f'{"<br><span class=muted>" + e(p["where"]) + "</span>" if p["where"] else ""}</li>')
    out.append("</ul></div>")
    return "\n".join(out)


def main():
    x = pd.read_excel(SRC, sheet_name=None)
    talks_df = unlabel(x[SHEETS["all_talks"]], ["id", "date", "start", "end", "location", "relevance", "title",
                       "topics", "why", "goal", "speakers", "host_org", "format", "tracks", "also_at",
                       "teaser"]).fillna("")
    booths_df = unlabel(x[SHEETS["all_booths"]], ["id", "visit_priority", "hall", "stand", "exhibitor", "visit_goal",
                        "why", "booth_question", "relationship", "contacts_to_meet", "same_stand_with",
                        "is_competitor", "categories", "teaser"]).fillna("")
    people_df = unlabel(x[SHEETS["people"]], ["is_new", "priority", "name", "position", "organization", "userType",
                        "sector", "wo_finden", "talking_point", "why_person", "LinkedIn", "li_headline",
                        "li_followers", "ProfileURL"]).fillna("")
    meet_df = unlabel(x[SHEETS["meetings"]], ["tier", "is_new", "id", "priority", "name", "position", "organization",
                      "level", "keep_for_person", "wo_finden", "talking_point", "why_person", "relationship",
                      "LinkedIn", "li_headline", "li_followers", "userType", "ProfileURL"]).fillna("")
    spk_df = unlabel(x.get(SHEETS["speakers"], pd.DataFrame()), ["name", "position", "organization",
                     "person_priority", "max_talk_relevance", "sessions"]).fillna("")

    talks = []
    for r in talks_df.to_dict("records"):
        rel = prio_internal(r.get("relevance"))
        text = f"{s(r.get('title'))} {s(r.get('teaser'))} {s(r.get('tracks'))}"
        talks.append({
            "id": s(r["id"]), "t": s(r.get("title")), "d": s(r.get("date")), "s": s(r.get("start")),
            "e": s(r.get("end")), "loc": s(r.get("location")), "rel": rel, "top": s(r.get("topics")),
            "why": s(r.get("why")), "goal": s(r.get("goal")), "spk": s(r.get("speakers")),
            "fmt": s(r.get("format")), "host": s(r.get("host_org")), "tea": s(r.get("teaser")),
            "tr": s(r.get("tracks")), "also": s(r.get("also_at")),
            "chk": 1 if rel <= 1 and KW.search(text) else 0,
        })

    booths = []
    for r in booths_df.to_dict("records"):
        booths.append({
            "id": s(r["id"]), "n": s(r.get("exhibitor")), "hall": s(r.get("hall")), "st": s(r.get("stand")),
            "p": prio_internal(r.get("visit_priority")), "goal": s(r.get("visit_goal")), "why": s(r.get("why")),
            "q": s(r.get("booth_question")), "ct": s(r.get("contacts_to_meet")), "rel": s(r.get("relationship")),
            "same": s(r.get("same_stand_with")), "comp": 1 if s(r.get("is_competitor")).lower() in ("true", "ja") else 0,
            "cat": s(r.get("categories")), "tea": s(r.get("teaser")),
        })


    meet_by_id = {s(r.get("id")): r for r in meet_df.to_dict("records") if s(r.get("id"))}
    more_df = x.get(SHEETS.get("meetings_more", ""), pd.DataFrame())
    more_df = unlabel(more_df, ["id", "priority", "name", "position", "organization", "keep_for_person",
                      "wo_finden", "talking_point", "why_person", "LinkedIn", "li_headline", "li_followers",
                      "userType", "ProfileURL"]).fillna("") if len(more_df) else pd.DataFrame()
    # Stufe -> rec: 1 = empfohlen (Fachebene), 2 = weitere, 3 = Management
    tier = {mid: {"weitere": 2, "Management": 3}.get(s(r.get("tier")), 1) for mid, r in meet_by_id.items()}
    for r in more_df.to_dict("records"):
        if s(r.get("id")) and s(r.get("id")) not in meet_by_id:
            meet_by_id[s(r.get("id"))] = r
            tier[s(r.get("id"))] = 2
    people = []
    for r in people_df.to_dict("records"):
        m = re.search(r"--u-(.+)$", s(r.get("ProfileURL")))
        pid = m.group(1) if m else f"{s(r.get('name'))}|{s(r.get('organization'))}"
        people.append({
            "id": pid, "n": s(r.get("name")), "pos": s(r.get("position")), "org": s(r.get("organization")),
            "ut": s(r.get("userType")), "p": prio_internal(r.get("priority")), "sec": s(r.get("sector")),
            "new": 1 if s(r.get("is_new")) else 0, "team": 1 if s(r.get("sector")) == TEAM_SECTOR else 0,
            "where": s(r.get("wo_finden")), "tp": s(r.get("talking_point")), "why": s(r.get("why_person")),
            "li": s(r.get("LinkedIn")), "lih": s(r.get("li_headline")), "fol": n(r.get("li_followers")),
            "url": s(r.get("ProfileURL")),
            "rec": 0, "cat": "",
        })
    # "Empfohlene Kontakte" (08b) bilgileri: once mevcut kisileri guncelle, sonra programdaki
    # konusmacilar gibi katilimci listesinde olmayanlari ekle
    known = {p["id"]: p for p in people}
    for mid, r in meet_by_id.items():
        upd = {"rec": tier.get(mid, 1), "p": prio_internal(r.get("priority")) or 3, "tp": s(r.get("talking_point")),
               "why": s(r.get("why_person")), "where": s(r.get("wo_finden")), "cat": s(r.get("keep_for_person")),
               "lvl": s(r.get("level")), "rel": s(r.get("relationship")), "new": 1 if s(r.get("is_new")) else 0}
        if mid in known:
            known[mid].update({k: v for k, v in upd.items() if v != ""})
        else:
            people.append({"id": mid, "n": s(r.get("name")), "pos": s(r.get("position")),
                           "org": s(r.get("organization")), "ut": s(r.get("userType")) or "Programm-Speaker",
                           "sec": "", "team": 0, "li": s(r.get("LinkedIn")), "lih": s(r.get("li_headline")),
                           "fol": n(r.get("li_followers")), "url": s(r.get("ProfileURL")), **upd})

    speakers = []
    for i, r in enumerate(spk_df.to_dict("records")):
        speakers.append({
            "id": f"spk|{s(r.get('name'))}|{s(r.get('organization'))}", "n": s(r.get("name")), "pos": s(r.get("position")),
            "org": s(r.get("organization")), "rel": prio_internal(r.get("max_talk_relevance")),
            "pp": n(r.get("person_priority")), "ses": s(r.get("sessions")),
        })

    data = {"built": datetime.now().strftime("%d.%m.%Y %H:%M"), "talks": talks, "booths": booths,
            "people": people, "speakers": speakers}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    static = build_static(talks, booths, people)
    html = (TEMPLATE.replace("__DATA__", blob).replace("__STATIC__", static)
            .replace("__TALK_URL__", TALK_URL).replace("__BOOTH_URL__", BOOTH_URL))
    OUT.write_text(html, encoding="utf-8")
    print(f"Talks: {len(talks)} | Stände: {len(booths)} | Personen: {len(people)} "
          f"(empfohlen: {sum(p.get('rec') == 1 for p in people)}, weitere: {sum(p.get('rec') == 2 for p in people)}, "
          f"Management: {sum(p.get('rec') == 3 for p in people)}, Team: {sum(p.get('team', 0) for p in people)}, "
          f"neu: {sum(p.get('new', 0) for p in people)}) | Speaker: {len(speakers)}")
    print(f"-> {OUT}  ({OUT.stat().st_size / 1e6:.1f} MB). Doppelklick zum Öffnen.")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SCC 2026 – Planung</title>
<style>
body{margin:0;background:#fff;color:#222;font:14px/1.45 Arial,Helvetica,sans-serif}
header{border-bottom:1px solid #ccc;background:#fafafa}
.bar{max-width:1060px;margin:0 auto;padding:10px 16px;display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
h1{font-size:16px;margin:0;font-weight:bold}
.me{font-size:13px;color:#555;display:flex;align-items:center;gap:6px}
.me input{width:120px}
.save{margin-left:auto;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.status{font-size:12px;color:#777}
nav{max-width:1060px;margin:0 auto;padding:0 16px;display:flex;gap:18px;overflow-x:auto}
nav button{border:0;background:none;padding:8px 0;font-size:14px;color:#555;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
nav button.on{color:#000;border-bottom-color:#000;font-weight:bold}
main{max-width:1060px;margin:0 auto;padding:12px 16px 60px}
input,select,textarea,button{font:inherit;color:inherit}
input[type=text],input[type=search],input[type=time],select,textarea{border:1px solid #bbb;border-radius:2px;padding:4px 6px;background:#fff}
textarea{width:100%;min-height:54px}
.btn{border:1px solid #aaa;background:#f3f3f3;border-radius:2px;padding:4px 10px;cursor:pointer;font-size:13px}
.btn:hover{background:#e8e8e8}
.btn.primary{font-weight:bold}
.btn.on{background:#e0e0e0;font-weight:bold}
.filters{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin:4px 0 10px}
.filters input[type=search]{flex:1 1 220px}
.seg{display:inline-flex;gap:0}
.seg button{border:1px solid #aaa;background:#f3f3f3;padding:3px 9px;cursor:pointer;font-size:13px;margin-right:-1px}
.seg button.on{background:#555;color:#fff;border-color:#555}
.count{font-size:13px;color:#666;margin:0 0 6px}
.card{border-bottom:1px solid #ddd;padding:10px 4px}
.card.picked{background:#fffbe6}
.card.done{color:#888}
.row{display:flex;gap:12px;align-items:flex-start}
.row .grow{flex:1;min-width:0}
.meta{font-size:13px;color:#555}
.meta span{margin-right:10px}
.title{font-weight:bold;margin:2px 0 3px}
.badge{font-weight:normal}
.b3{font-weight:bold}
.bw{color:#a00}
.kv{font-size:13px;margin-top:3px}
.kv b{font-weight:normal;color:#666}
.topics{font-size:12px;color:#666}
.actions{display:flex;flex-direction:column;gap:5px;align-items:flex-end;font-size:13px;white-space:nowrap}
.pick{cursor:pointer}
.who{font-size:12px;color:#060}
details{margin-top:4px}summary{cursor:pointer;font-size:12px;color:#666}
.note-has{color:#000}
.warnline{font-size:12px;color:#a00;margin-top:4px}
h2{font-size:15px;margin:18px 0 4px;border-bottom:1px solid #999;padding-bottom:2px}
.empty{color:#666;padding:8px 0}
.summary{font-size:13px;color:#444;margin:4px 0 8px}
.more{display:block;margin:8px auto}
dialog{border:1px solid #999;padding:14px 16px;max-width:440px;width:calc(100% - 32px)}
dialog label{display:block;font-size:13px;color:#555;margin-top:8px}
dialog input,dialog select,dialog textarea{width:100%}
.hint{font-size:12px;color:#666}
a{color:#0645ad}
#notice{max-width:1060px;margin:0 auto;padding:0 16px}
.notice{background:#fff7d6;border:1px solid #e0c96b;padding:8px 10px;margin-top:10px;font-size:13px}
.notice button{margin-left:8px}
.cal-wrap{overflow-x:auto}
.cal{display:grid;grid-template-columns:44px repeat(3,minmax(220px,1fr));min-width:720px;border-top:1px solid #999}
.cal-head{font-weight:bold;font-size:13px;padding:4px 6px;border-bottom:1px solid #999;border-left:1px solid #ddd}
.cal-col{position:relative;border-left:1px solid #ddd}
.cal-hour{position:absolute;left:0;right:0;border-top:1px solid #eee;font-size:11px;color:#888}
.cal-times{position:relative}
.cal-times span{position:absolute;right:4px;font-size:11px;color:#888;transform:translateY(-6px)}
.ev{position:absolute;box-sizing:border-box;padding:2px 4px;font-size:11.5px;line-height:1.25;overflow:hidden;
    background:#eef2f6;border:1px solid #b8c3cf;border-left:3px solid #4a5a6a}
.ev.own{background:#eef6ea;border-color:#b9ccb0;border-left-color:#4f7a3a}
.ev.go{border-left-color:#000;font-weight:bold}
.ev a{color:inherit;text-decoration:none}
.ev .t{display:block}
html:not(.js) .js-only{display:none!important}
html.js .nojs-only{display:none!important}
.notice{background:#fff7d6;border:1px solid #e0c96b;padding:8px 10px;font-size:13px}
ul.plain{list-style:none;padding:0;margin:0}
ul.plain li{padding:7px 0;border-bottom:1px solid #ddd}
.muted{color:#666;font-size:13px}
h3{font-size:14px;margin:14px 0 4px}
@media (max-width:640px){
  body{font-size:15px}
  .bar{padding:8px 12px;gap:6px 10px}
  h1{font-size:15px;width:100%}
  .me input{width:140px}
  .save{margin-left:0;gap:5px}
  .status{width:100%;order:9}
  .btn{padding:8px 11px;font-size:14px}
  .save .btn{padding:6px 9px;font-size:13px}   /* Kopfzeile kompakt halten */
  .me{font-size:13px}
  input[type=text],input[type=search],input[type=time],select,textarea{font-size:16px}  /* iOS zoomt sonst beim Tippen */
  /* Reiter als feste Leiste unten: mit dem Daumen erreichbar */
  nav#tabs{position:fixed;left:0;right:0;bottom:0;z-index:30;background:#fafafa;border-top:1px solid #bbb;
           padding:0 0 env(safe-area-inset-bottom);gap:0;justify-content:space-around;max-width:none}
  nav#tabs button{flex:1;padding:13px 2px;font-size:13px;border-bottom:0;border-top:3px solid transparent}
  nav#tabs button.on{border-top-color:#000;border-bottom-color:transparent}
  main{padding:10px 12px 90px}
  .filters{gap:6px}
  .seg{flex-wrap:wrap}
  .seg button{padding:8px 10px;font-size:14px;margin-bottom:4px}
  .filters input[type=search]{flex:1 1 100%}
  .row{flex-direction:column;gap:6px}
  .actions{flex-direction:row;align-items:center;flex-wrap:wrap;gap:12px}
  .pick input{width:20px;height:20px;vertical-align:middle}
  .cal{min-width:660px}
}
@media print{header,.filters,.actions,details,.more{display:none!important}}
</style>
</head>
<body>
<script>document.documentElement.className += " js";</script>
<header>
  <div class="bar">
    <h1>SCC 2026 – Planung</h1>
    <label class="me js-only">Ich bin <input type="text" id="me" placeholder="Name"></label>
    <div class="save js-only">
      <span class="status" id="status"></span>
      <button class="btn" id="btnAdd">Eintrag hinzufügen</button>
      <button class="btn primary" id="btnSave" title="Speichert eine Kopie dieser Datei mit allen Notizen">Speichern</button>
      <button class="btn" id="btnExport" title="Notizen als JSON exportieren">Export</button>
      <button class="btn" id="btnImport" title="Datei eines Kollegen einlesen und zusammenführen">Import</button>
      <button class="btn" id="btnReset" title="Alle Markierungen, Notizen und eigenen Einträge löschen">Zurücksetzen</button>
      <input type="file" id="fileImport" accept=".html,.htm,.json" hidden>
    </div>
  </div>
  <nav id="tabs" class="js-only">
    <button data-tab="plan" class="on">Mein Plan</button>
    <button data-tab="talks">Vorträge</button>
    <button data-tab="booths">Stände</button>
    <button data-tab="people">Personen</button>
    <button data-tab="cal">Kalender</button>
  </nav>
</header>
<div id="notice"></div>
<main id="main">__STATIC__</main>

<dialog id="dlg">
  <form method="dialog" id="dlgForm">
    <h2 style="margin-top:0">Eintrag hinzufügen</h2>
    <label>Typ
      <select id="fType"><option value="event">Termin / Treffen</option><option value="person">Person</option><option value="task">Aufgabe</option></select>
    </label>
    <label>Titel / Name <input type="text" id="fTitle" required></label>
    <div id="fWhen">
      <label>Tag <select id="fDate"><option value="2026-10-13">Di 13.10.</option><option value="2026-10-14">Mi 14.10.</option><option value="2026-10-15">Do 15.10.</option></select></label>
      <label>Von <input type="time" id="fStart"></label>
      <label>Bis <input type="time" id="fEnd"></label>
    </div>
    <label>Ort / Organisation <input type="text" id="fLoc"></label>
    <label>Notiz <textarea id="fNote"></textarea></label>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
      <button class="btn" value="cancel" formnovalidate>Abbrechen</button>
      <button class="btn primary" value="ok" id="fOk">Hinzufügen</button>
    </div>
  </form>
</dialog>

<script id="app-data" type="application/json">__DATA__</script>
<script id="saved-state" type="application/json">{}</script>
<script>
(function(){
"use strict";
const DATA = JSON.parse(document.getElementById("app-data").textContent);
const STATIC_MAIN = document.getElementById("main").innerHTML;   // Lese-Ansicht ohne JS, wird beim Speichern wieder eingesetzt
const LS_KEY = "scc2026-planner-state";
const DAYS = {"2026-10-13":"Di 13.10.","2026-10-14":"Mi 14.10.","2026-10-15":"Do 15.10."};
const STATUS = ["", "gesprochen"];   // eski kayitlardaki diger durumlar da "gesprochen" sayilir

// ---------------- state ----------------
function emptyState(){ return {v:1, updatedAt:0, savedAt:0, me:"", talks:{}, booths:{}, people:{}, speakers:{}, custom:[]}; }
function readJSON(txt){ try{ const o = JSON.parse(txt); return (o && typeof o==="object") ? o : null; }catch(e){ return null; } }
let embedded = readJSON(document.getElementById("saved-state").textContent) || {};
let local = null;
try{ local = readJSON(localStorage.getItem(LS_KEY) || ""); }catch(e){}
// Neuerer Stand gewinnt. Enthält die Datei einen älteren, abweichenden Stand, wird ein Hinweis angezeigt.
const useLocal = local && (local.updatedAt||0) >= (embedded.updatedAt||0);
let S = Object.assign(emptyState(), useLocal ? local : embedded);
const olderFileState = useLocal && embedded.updatedAt && embedded.updatedAt !== local.updatedAt ? embedded : null;

function persist(){
  S.updatedAt = Date.now();
  try{ localStorage.setItem(LS_KEY, JSON.stringify(S)); }catch(e){}
  showStatus();
}
const HOSTED = location.protocol === "http:" || location.protocol === "https:";   // Webseite statt lokaler Datei
function showStatus(){
  const el = document.getElementById("status");
  const t = S.updatedAt ? new Date(S.updatedAt).toLocaleTimeString("de-DE",{hour:"2-digit",minute:"2-digit"}) : "–";
  if(HOSTED){ el.textContent = S.updatedAt ? "Automatisch gespeichert, zuletzt " + t : "Eingaben werden automatisch gespeichert"; return; }
  const dirty = S.updatedAt > (S.savedAt||0);
  el.textContent = "Zuletzt geändert " + t + (dirty ? " (noch nicht als Datei gespeichert)" : "");
}
function item(kind, id){ return S[kind][id] || (S[kind][id] = {}); }
function clean(kind, id){ const o = S[kind][id]; if(o && !o.pick && !o.note && !(o.who&&o.who.length) && !o.status && !o.done) delete S[kind][id]; }

// ---------------- helpers ----------------
const esc = s => String(s==null?"":s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm = s => String(s||"").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g,"");
// intern 3 = am wichtigsten; angezeigt wie gewohnt "Prio 1" = hoechste Prioritaet
const PL = r => r>0 ? "Prio "+(4-r) : "Prio –";
function badge(r, label){ return `<span class="badge b${r}">${label||PL(r)}</span>`; }
function mins(t){ const m = /^(\d{1,2}):(\d{2})/.exec(t||""); return m ? (+m[1])*60 + (+m[2]) : null; }
function standKey(st){ return (String(st).match(/\d+/g)||["999"]).map(n=>n.padStart(4,"0")).join("."); }
function noteBlock(kind, id){
  const o = S[kind][id] || {};
  return `<details class="note"${o.note?" open":""}><summary>${o.note?'<span class="note-has">Notiz ✎</span>':"Notiz hinzufügen"}</summary>
    <textarea data-note="${kind}" data-id="${esc(id)}" placeholder="Notiz…">${esc(o.note||"")}</textarea></details>`;
}
function starBtn(kind, id){
  const on = (S[kind][id]||{}).pick;
  return `<label class="pick"><input type="checkbox" data-star="${kind}" data-id="${esc(id)}"${on?" checked":""}> merken</label>`;
}
function slug(x){ return String(x||"").replace(/ß/g,"ss").normalize("NFKD").replace(/[\u0300-\u036f]/g,"")
  .replace(/[^A-Za-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,80); }
const TALK_URL = "__TALK_URL__", BOOTH_URL = "__BOOTH_URL__";
const talkUrl = t => TALK_URL.replace("{slug}", slug(t.t)).replace("{id}", encodeURIComponent(t.id));
const boothUrl = b => BOOTH_URL.replace("{slug}", slug(b.n)).replace("{id}", encodeURIComponent(b.id));
const T = Object.fromEntries(DATA.talks.map(t=>[t.id,t]));
const B = Object.fromEntries(DATA.booths.map(b=>[b.id,b]));
const P = Object.fromEntries(DATA.people.map(p=>[p.id,p]));
const SP = Object.fromEntries(DATA.speakers.map(p=>[p.id,p]));

// ---------------- UI state ----------------
const UI = {cal:{only:"all"}, tab:"plan", talk:{day:"all", tier:"top", q:"", sort:"rel", topic:""}, booth:{tier:"3", hall:"", q:"", only:""},
            person:{src:"rec", q:"", min:"0"}, limit:{talks:150, booths:150, people:100}};

// ---------------- renderers ----------------
function renderTalkCard(t){
  const o = S.talks[t.id] || {};
  const who = (o.who||[]);
  const conflicts = pickedTalks().filter(x => x.id!==t.id && overlaps(x,t));
  return `<div class="card${o.pick?" picked":""}"><div class="row"><div class="grow">
    <div class="meta"><span>${esc(DAYS[t.d]||t.d)} ${esc(t.s)}–${esc(t.e)}</span><span>${esc(t.loc)}</span>${badge(t.rel)}${t.chk?'<span class="bw">evtl. relevant</span>':""}${t.fmt?`<span>${esc(t.fmt)}</span>`:""}</div>
    <div class="title"><a href="${esc(talkUrl(t))}" target="_blank" rel="noopener">${esc(t.t)}</a></div>
    ${t.top?`<div class="topics">${esc(t.top)}</div>`:""}
    ${t.why?`<div class="kv"><b>Warum:</b> ${esc(t.why)}</div>`:""}
    ${t.goal?`<div class="kv"><b>Ziel:</b> ${esc(t.goal)}</div>`:""}
    ${t.spk?`<div class="kv"><b>Speaker:</b> ${esc(t.spk)}</div>`:""}
    ${t.host?`<div class="kv"><b>Veranstalter:</b> ${esc(t.host)}</div>`:""}
    ${t.also?`<div class="kv"><b>Auch am:</b> ${esc(t.also)}</div>`:""}
    ${conflicts.length?`<div class="warnline">Gleichzeitig mit: ${conflicts.map(c=>esc(c.s+" "+c.t.slice(0,45))).join(" · ")}</div>`:""}
    ${t.tea?`<details><summary>Beschreibung</summary><div class="kv">${esc(t.tea)}</div></details>`:""}
    ${noteBlock("talks", t.id)}
  </div><div class="actions">${starBtn("talks", t.id)}
    <button class="btn${who.includes(S.me)&&S.me?" on":""}" data-go="${esc(t.id)}">${who.includes(S.me)&&S.me?"Ich gehe ✓":"Ich gehe"}</button>
    ${who.length?`<span class="who">${esc(who.join(", "))}</span>`:""}
  </div></div></div>`;
}
function renderBoothCard(b){
  const o = S.booths[b.id] || {};
  const tier = PL(b.p);
  return `<div class="card${o.pick?" picked":""}${o.done?" done":""}"><div class="row"><div class="grow">
    <div class="meta"><span><b>${esc(b.st)}</b></span>${badge(b.p, tier)}${b.comp?'<span class="bw">Wettbewerber</span>':""}<span>${esc(b.goal)}</span></div>
    <div class="title"><a href="${esc(boothUrl(b))}" target="_blank" rel="noopener">${esc(b.n)}</a></div>
    ${b.why?`<div class="kv"><b>Warum:</b> ${esc(b.why)}</div>`:""}
    ${b.rel?`<div class="kv"><b>Bestehende Beziehung:</b> ${esc(b.rel)}</div>`:""}
    ${b.q?`<div class="kv"><b>Frage am Stand:</b> ${esc(b.q)}</div>`:""}
    ${b.ct?`<div class="kv"><b>Kontakte:</b> ${esc(b.ct)}</div>`:""}
    ${b.same?`<div class="kv"><b>Am selben Stand:</b> ${esc(b.same)}</div>`:""}
    ${b.tea?`<details><summary>Beschreibung</summary><div class="kv">${esc(b.tea)}</div><div class="kv">${esc(b.cat)}</div></details>`:""}
    ${noteBlock("booths", b.id)}
  </div><div class="actions">${starBtn("booths", b.id)}
    <label class="hint"><input type="checkbox" data-done="${esc(b.id)}"${o.done?" checked":""}> besucht</label>
  </div></div></div>`;
}
function renderPersonCard(p, kind){
  kind = kind || "people";
  const o = S[kind][p.id] || {};
  const st = `<label class="pick"><input type="checkbox" data-talked="${kind}" data-id="${esc(p.id)}"${o.status?" checked":""}> gesprochen</label>`;
  if(kind==="speakers"){
    return `<div class="card${o.pick?" picked":""}"><div class="row"><div class="grow">
      <div class="meta">${badge(p.rel, "Vortrags-"+PL(p.rel))}${p.pp!==""?`<span>Kontakt-Prio ${esc(p.pp)}</span>`:""}</div>
      <div class="title">${esc(p.n)}</div><div class="kv">${esc(p.pos)}${p.org?" · "+esc(p.org):""}</div>
      <div class="kv"><b>Sessions:</b> ${esc(p.ses)}</div>${noteBlock(kind, p.id)}
    </div><div class="actions">${starBtn(kind, p.id)}${st}</div></div></div>`;
  }
  return `<div class="card${o.pick?" picked":""}"><div class="row"><div class="grow">
    <div class="meta">${p.new?'<span class="b3">NEU</span>':""}${p.team?'<span class="b3">Univention-Team</span>':badge(p.p)}${p.rec===1?'<span>empfohlen</span>':p.rec===3?'<span>Management</span>':""}${p.cat?`<span>${esc(p.cat)}</span>`:""}<span>${esc(p.ut)}</span>${p.sec?`<span>${esc(p.sec)}</span>`:""}</div>
    <div class="title">${esc(p.n)}</div>
    <div class="kv">${esc(p.pos||p.lih)}${p.org?" · "+esc(p.org):""}</div>
    ${p.where?`<div class="kv"><b>Wo finden:</b> ${esc(p.where)}</div>`:""}
    ${p.tp?`<div class="kv"><b>Gesprächseinstieg:</b> ${esc(p.tp)}</div>`:""}
    ${p.rel?`<div class="kv"><b>Bestehende Beziehung:</b> ${esc(p.rel)}</div>`:""}
    ${p.why?`<details><summary>Begründung</summary><div class="kv">${esc(p.why)}</div></details>`:""}
    <div class="kv">${p.li?`<a href="${esc(p.li)}" target="_blank" rel="noopener">LinkedIn</a>`:""}${p.fol?` · ${esc(p.fol)} Follower`:""}${p.url?` · <a href="${esc(p.url)}" target="_blank" rel="noopener">SCC-Profil</a>`:""}</div>
    ${noteBlock(kind, p.id)}
  </div><div class="actions">${starBtn(kind, p.id)}${st}</div></div></div>`;
}
if(!S.speakers) S.speakers = {};

function pickedTalks(){ return Object.keys(S.talks).filter(id=>S.talks[id].pick && T[id]).map(id=>T[id])
  .concat(S.custom.filter(c=>c.type==="event").map(c=>({id:c.id,d:c.date,s:c.start,e:c.end,t:c.title,custom:1}))); }
function overlaps(a,b){ if(a.d!==b.d) return false; const as=mins(a.s), ae=mins(a.e)||as+30, bs=mins(b.s), be=mins(b.e)||bs+30;
  return as!=null && bs!=null && as<be && bs<ae; }

function viewPlan(){
  const tp = pickedTalks();
  const bp = DATA.booths.filter(b=>(S.booths[b.id]||{}).pick).sort((a,b)=>standKey(a.st)<standKey(b.st)?-1:1);
  const pp = DATA.people.filter(p=>(S.people[p.id]||{}).pick);
  const sp = DATA.speakers.filter(p=>(S.speakers[p.id]||{}).pick);
  const tasks = S.custom.filter(c=>c.type!=="event");
  const going = DATA.talks.filter(t=>((S.talks[t.id]||{}).who||[]).includes(S.me));
  const visited = bp.filter(b=>(S.booths[b.id]||{}).done).length;
  const met = pp.filter(p=>(S.people[p.id]||{}).status).length;
  let h = `<p class="summary">${tp.length} Vorträge/Termine gemerkt, davon ${going.length} mit mir · Stände besucht: ${visited} von ${bp.length} · mit Personen gesprochen: ${met} von ${pp.length}</p>`;
  if(!tp.length && !bp.length && !pp.length && !tasks.length){
    h += `<p class="empty">Noch nichts gemerkt. Unter Vorträge, Stände und Personen „merken“ anklicken, dann steht es hier. Oben den eigenen Namen eintragen, damit „Ich gehe“ funktioniert.</p>`;
  }
  for(const d of Object.keys(DAYS)){
    const list = tp.filter(t=>t.d===d).sort((a,b)=>(mins(a.s)||0)-(mins(b.s)||0));
    if(!list.length) continue;
    h += `<h2>${DAYS[d]}</h2>`;
    for(const t of list){
      const clash = list.filter(x=>x.id!==t.id && overlaps(x,t));
      if(t.custom){
        const c = S.custom.find(x=>x.id===t.id);
        h += `<div class="card picked"><div class="row"><div class="grow"><div class="meta"><span>${esc(t.s)}–${esc(t.e)}</span><span>${esc(c.loc||"")}</span><span>eigener Termin</span></div>
          <div class="title">${esc(t.t)}</div>${c.note?`<div class="kv">${esc(c.note)}</div>`:""}
          ${clash.length?`<div class="warnline">Überschneidung: ${clash.map(x=>esc(x.s+" "+x.t.slice(0,45))).join(" · ")}</div>`:""}
          </div><div class="actions"><button class="btn" data-delc="${esc(c.id)}">Löschen</button></div></div></div>`;
      } else h += renderTalkCard(t);
    }
  }
  if(bp.length){ h += `<h2>Stände</h2>` + bp.map(renderBoothCard).join(""); }
  if(pp.length || sp.length){ h += `<h2>Personen</h2>` + pp.sort((a,b)=>b.p-a.p).map(p=>renderPersonCard(p)).join("") + sp.map(p=>renderPersonCard(p,"speakers")).join(""); }
  if(tasks.length){
    h += `<h2>Sonstiges</h2>` + tasks.map(c=>`<div class="card"><div class="row"><div class="grow"><div class="meta"><span>${c.type==="person"?"Person":"Aufgabe"}</span><span>${esc(c.loc||"")}</span></div>
      <div class="title">${esc(c.title)}</div>${c.note?`<div class="kv">${esc(c.note)}</div>`:""}</div>
      <div class="actions"><label class="hint"><input type="checkbox" data-cdone="${esc(c.id)}"${c.done?" checked":""}> erledigt</label><button class="btn" data-delc="${esc(c.id)}">Löschen</button></div></div></div>`).join("");
  }
  return h;
}

function viewTalks(){
  const f = UI.talk, q = norm(f.q);
  const topics = [...new Set(DATA.talks.flatMap(t=>t.top?t.top.split(", "):[]))].sort();
  let list = DATA.talks.filter(t =>
    (f.day==="all" || t.d===f.day) &&
    (f.tier==="all" || (f.tier==="top" ? t.rel===3 : f.tier==="more" ? (t.rel===2 || t.chk) : f.tier==="mine" ? (S.talks[t.id]||{}).pick : true)) &&
    (!f.topic || t.top.includes(f.topic)) &&
    (!q || norm(t.t+" "+t.spk+" "+t.host+" "+t.tea+" "+t.loc).includes(q)));
  list.sort((a,b)=> f.sort==="rel" ? (b.rel-a.rel) || (a.d<b.d?-1:a.d>b.d?1:0) || ((mins(a.s)||0)-(mins(b.s)||0))
                                   : (a.d<b.d?-1:a.d>b.d?1:0) || ((mins(a.s)||0)-(mins(b.s)||0)) || (b.rel-a.rel));
  // Wiederholungen (gleicher Titel + Veranstalter + Speaker) nur einmal zeigen, weitere Termine stehen unter „Auch am“
  if(f.tier!=="mine" && f.day==="all"){
    const seen = new Set();
    list = list.filter(t => { const k = t.t+"|"+t.host+"|"+t.spk; if(seen.has(k) && !(S.talks[t.id]||{}).pick) return false; seen.add(k); return true; });
  }
  const seg = (name, cur, opts) => `<div class="seg">${opts.map(([v,l])=>`<button data-f="${name}" data-v="${v}" class="${cur===v?"on":""}">${l}</button>`).join("")}</div>`;
  let h = `<div class="filters">
    ${seg("talk.tier", f.tier, [["top","Prio 1"],["more","Prio 2"],["all","Alle"],["mine","Gemerkt"]])}
    ${seg("talk.day", f.day, [["all","Alle Tage"]].concat(Object.entries(DAYS)))}
    ${seg("talk.sort", f.sort, [["rel","Nach Prio"],["time","Nach Zeit"]])}
    <select data-sel="talk.topic"><option value="">Alle Themen</option>${topics.map(x=>`<option${f.topic===x?" selected":""}>${esc(x)}</option>`).join("")}</select>
    <input type="search" data-q="talk" placeholder="Suche: Titel, Speaker, Organisation…" value="${esc(f.q)}"></div>
    <p class="count">${list.length} Vorträge</p>`;
  h += list.slice(0, UI.limit.talks).map(renderTalkCard).join("") || `<p class="empty">Keine Treffer.</p>`;
  if(list.length > UI.limit.talks) h += `<button class="btn more" data-more="talks">Weitere ${list.length-UI.limit.talks} anzeigen</button>`;
  return h;
}

function viewBooths(){
  const f = UI.booth, q = norm(f.q);
  const halls = [...new Set(DATA.booths.map(b=>b.hall).filter(Boolean))].sort();
  let list = DATA.booths.filter(b =>
    (f.tier==="all" || (f.tier==="mine" ? (S.booths[b.id]||{}).pick : f.tier==="comp" ? b.comp : b.p===+f.tier)) &&
    (!f.hall || b.hall===f.hall) &&
    (!q || norm(b.n+" "+b.st+" "+b.goal+" "+b.cat+" "+b.ct+" "+b.same).includes(q)));
  list.sort((a,b)=> standKey(a.st)<standKey(b.st)?-1:1);
  const seg = (name, cur, opts) => `<div class="seg">${opts.map(([v,l])=>`<button data-f="${name}" data-v="${v}" class="${cur===v?"on":""}">${l}</button>`).join("")}</div>`;
  let h = `<div class="filters">
    ${seg("booth.tier", f.tier, [["3","Prio 1"],["2","Prio 2"],["all","Alle"],["mine","Gemerkt"]])}
    <select data-sel="booth.hall"><option value="">Alle Hallen</option>${halls.map(x=>`<option${f.hall===x?" selected":""}>${esc(x)}</option>`).join("")}</select>
    <input type="search" data-q="booth" placeholder="Suche: Firma, Stand, Kontakt…" value="${esc(f.q)}"></div>
    <p class="count">${list.length} Aussteller, nach Stand sortiert</p>`;
  h += list.slice(0, UI.limit.booths).map(renderBoothCard).join("") || `<p class="empty">Keine Treffer.</p>`;
  if(list.length > UI.limit.booths) h += `<button class="btn more" data-more="booths">Weitere ${list.length-UI.limit.booths} anzeigen</button>`;
  return h;
}

function viewPeople(){
  const f = UI.person, q = norm(f.q);
  const seg = (name, cur, opts) => `<div class="seg">${opts.map(([v,l])=>`<button data-f="${name}" data-v="${v}" class="${cur===v?"on":""}">${l}</button>`).join("")}</div>`;
  let h = `<div class="filters">
    ${seg("person.src", f.src, [["rec","Empfohlen (Fachebene)"],["more","Weitere Kontakte"],["mgmt","Management"],["all","Alle Teilnehmenden"],["new","Neu"],["team","Univention-Team"],["spk","Speaker"],["mine","Gemerkt"]])}
    ${f.src==="all"?seg("person.min", f.min, [["0","alle"],["2","Prio 1–2"],["3","Prio 1"]]):""}
    <input type="search" data-q="person" placeholder="Suche: Name, Organisation, Position…" value="${esc(f.q)}"></div>`;
  let list, kind = "people";
  if(f.src==="spk"){
    kind = "speakers";
    list = DATA.speakers.filter(p => !q || norm(p.n+" "+p.org+" "+p.pos+" "+p.ses).includes(q)).sort((a,b)=>b.rel-a.rel);
  } else if(f.src==="mine"){
    list = DATA.people.filter(p=>(S.people[p.id]||{}).pick);
    const sl = DATA.speakers.filter(p=>(S.speakers[p.id]||{}).pick);
    h += `<p class="count">${list.length+sl.length} gemerkt</p>` + list.map(p=>renderPersonCard(p)).join("") + sl.map(p=>renderPersonCard(p,"speakers")).join("");
    return h || `<p class="empty">Noch niemand gemerkt.</p>`;
  } else {
    list = DATA.people.filter(p =>
      (f.src==="rec" ? p.rec===1 : f.src==="more" ? p.rec===2 : f.src==="mgmt" ? p.rec===3 :
       f.src==="new" ? p.new : f.src==="team" ? p.team : p.p >= +f.min) &&
      (!q || norm(p.n+" "+p.org+" "+p.pos+" "+p.lih+" "+p.sec).includes(q)));
    list.sort((a,b)=> (b.p-a.p) || (b.where?1:0)-(a.where?1:0) || a.org.localeCompare(b.org));
  }
  h += `<p class="count">${list.length} Personen</p>`;
  h += list.slice(0, UI.limit.people).map(p=>renderPersonCard(p, kind)).join("") || `<p class="empty">Keine Treffer.</p>`;
  if(list.length > UI.limit.people) h += `<button class="btn more" data-more="people">Weitere ${list.length-UI.limit.people} anzeigen</button>`;
  return h;
}

// ---------------- Kalender ----------------
function calItems(){
  const mine = UI.cal.only === "me";
  return pickedTalks().map(t => {
    const who = t.custom ? [] : ((S.talks[t.id]||{}).who || []);
    const c = t.custom ? S.custom.find(x=>x.id===t.id) : null;
    return {id:t.id, d:t.d, s:t.s, e:t.e||"", t:t.t, loc: t.custom ? (c.loc||"") : (T[t.id]||{}).loc || "",
            own:!!t.custom, go: !!S.me && who.includes(S.me), url: t.custom ? "" : talkUrl(T[t.id]),
            note: t.custom ? (c.note||"") : ((S.talks[t.id]||{}).note || "")};
  }).filter(x => mins(x.s)!=null && (!mine || x.go || x.own));
}
function viewCalendar(){
  const items = calItems();
  const seg = `<div class="seg"><button data-f="cal.only" data-v="all" class="${UI.cal.only==="all"?"on":""}">Alles Gemerkte</button><button data-f="cal.only" data-v="me" class="${UI.cal.only==="me"?"on":""}">Nur wo ich hingehe</button></div>`;
  let h = `<div class="filters">${seg}<button class="btn" id="btnIcs">Kalenderdatei (.ics) herunterladen</button></div>`;
  if(!items.length) return h + `<p class="empty">Noch keine Termine. Vorträge merken oder unter „Eintrag hinzufügen“ einen Termin anlegen.</p>`;
  const starts = items.map(x=>mins(x.s)), ends = items.map(x=>mins(x.e)||mins(x.s)+30);
  const h0 = Math.min(8, Math.floor(Math.min(...starts)/60)), h1 = Math.max(19, Math.ceil(Math.max(...ends)/60));
  const PX = 1.7, H = (h1-h0)*60*PX;
  let times = `<div class="cal-times" style="height:${H}px">`;
  for(let hr=h0; hr<=h1; hr++) times += `<span style="top:${(hr-h0)*60*PX}px">${hr}:00</span>`;
  times += `</div>`;
  let head = `<div class="cal-head" style="border-left:0"></div>`, cols = "";
  for(const d of Object.keys(DAYS)){
    head += `<div class="cal-head">${DAYS[d]}</div>`;
    let col = `<div class="cal-col" style="height:${H}px">`;
    for(let hr=h0; hr<=h1; hr++) col += `<div class="cal-hour" style="top:${(hr-h0)*60*PX}px"></div>`;
    // Überschneidungen nebeneinander: Cluster bilden, darin Spuren vergeben
    const ev = items.filter(x=>x.d===d).map(x=>({...x, a:mins(x.s), b:(mins(x.e)||mins(x.s)+30)})).sort((p,q)=>p.a-q.a || q.b-p.b);
    let cluster = [], cEnd = -1;
    const flush = () => { const lanes = []; for(const x of cluster){ let i = lanes.findIndex(end=>end<=x.a); if(i<0){ i = lanes.length; lanes.push(0); } lanes[i] = x.b; x.lane = i; }
      for(const x of cluster){ x.n = lanes.length; } cluster = []; };
    for(const x of ev){ if(x.a >= cEnd && cluster.length) flush(); cluster.push(x); cEnd = Math.max(cEnd, x.b); }
    flush();
    for(const x of ev){
      const top = (x.a - h0*60)*PX, height = Math.max(18, (x.b-x.a)*PX - 2), w = 100/x.n;
      const label = `<span class="t">${esc(x.s)}${x.e?"–"+esc(x.e):""}</span><span class="t">${esc(x.t)}</span>${x.loc?`<span class="t">${esc(x.loc)}</span>`:""}`;
      col += `<div class="ev${x.own?" own":""}${x.go?" go":""}" style="top:${top}px;height:${height}px;left:calc(${x.lane*w}% + 2px);width:calc(${w}% - 4px)" title="${esc(x.s+" "+x.t+(x.loc?" · "+x.loc:"")+(x.note?"\n"+x.note:""))}">${x.url?`<a href="${esc(x.url)}" target="_blank" rel="noopener">${label}</a>`:label}</div>`;
    }
    cols += col + `</div>`;
  }
  return h + `<p class="count">${items.length} Termine · fett = ich gehe hin · grün = eigener Termin · nebeneinander = gleichzeitig</p>
    <div class="cal-wrap"><div class="cal">${head}${times}${cols}</div></div>`;
}
function icsText(){
  const pad = n => String(n).padStart(2,"0");
  // Berlin ist vom 13.–15.10.2026 in der Sommerzeit (UTC+2)
  const utc = (d, t) => { const [y,m,dd] = d.split("-").map(Number); const mm = mins(t);
    const x = new Date(Date.UTC(y, m-1, dd, 0, mm - 120));
    return `${x.getUTCFullYear()}${pad(x.getUTCMonth()+1)}${pad(x.getUTCDate())}T${pad(x.getUTCHours())}${pad(x.getUTCMinutes())}00Z`; };
  const e = s => String(s||"").replace(/\\/g,"\\\\").replace(/;/g,"\\;").replace(/,/g,"\\,").replace(/\r?\n/g,"\\n");
  const now = new Date(); const stampNow = `${now.getUTCFullYear()}${pad(now.getUTCMonth()+1)}${pad(now.getUTCDate())}T${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}00Z`;
  const lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//SCC 2026 Planung//DE","CALSCALE:GREGORIAN","METHOD:PUBLISH"];
  for(const x of calItems()){
    const end = x.e && mins(x.e) ? x.e : `${pad(Math.floor((mins(x.s)+30)/60))}:${pad((mins(x.s)+30)%60)}`;
    lines.push("BEGIN:VEVENT", `UID:${e(x.id)}@scc2026-planung`, `DTSTAMP:${stampNow}`, `DTSTART:${utc(x.d, x.s)}`, `DTEND:${utc(x.d, end)}`,
      `SUMMARY:${e(x.t)}`, `LOCATION:${e(x.loc ? x.loc + ", Messe Berlin" : "Messe Berlin")}`,
      `DESCRIPTION:${e([x.note, x.url].filter(Boolean).join("\n"))}`, ...(x.url ? [`URL:${x.url}`] : []), "END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}

// ---------------- Hinweis bei älterem Datei-Stand ----------------
let noticeDismissed = false;
function showNotice(){
  const el = document.getElementById("notice");
  if(!olderFileState || noticeDismissed){ el.innerHTML = ""; return; }
  const when = new Date(olderFileState.updatedAt).toLocaleString("de-DE",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
  el.innerHTML = `<div class="notice">Diese Datei enthält einen gespeicherten Stand${olderFileState.me?" von "+esc(olderFileState.me):""} (${when}). Angezeigt wird der neuere Stand aus diesem Browser.
    <button class="btn" id="nMerge">Zusammenführen</button><button class="btn" id="nFile">Stand aus der Datei laden</button><button class="btn" id="nHide">Ausblenden</button></div>`;
}
document.getElementById("notice").addEventListener("click", e=>{
  const id = e.target.id;
  if(id==="nMerge"){ S = merge(S, Object.assign(emptyState(), olderFileState), olderFileState.me || "Datei"); noticeDismissed = true; persist(); render(true); }
  else if(id==="nFile"){ if(confirm("Den Stand aus der Datei laden? Der aktuelle Browser-Stand wird ersetzt.")){ S = Object.assign(emptyState(), olderFileState); noticeDismissed = true; persist(); render(true); } }
  else if(id==="nHide"){ noticeDismissed = true; showNotice(); }
});

function render(keepScroll){
  const y = window.scrollY;
  const m = document.getElementById("main");
  m.innerHTML = UI.tab==="plan" ? viewPlan() : UI.tab==="talks" ? viewTalks() : UI.tab==="booths" ? viewBooths()
              : UI.tab==="cal" ? viewCalendar() : viewPeople();
  showNotice();
  document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on", b.dataset.tab===UI.tab));
  if(keepScroll) window.scrollTo(0, y);
}

// ---------------- events ----------------
document.getElementById("tabs").addEventListener("click", e=>{
  const b = e.target.closest("button[data-tab]"); if(!b) return;
  UI.tab = b.dataset.tab; render(false); window.scrollTo(0,0);
});
const main = document.getElementById("main");
main.addEventListener("click", e=>{
  const t = e.target;
  const star = t.closest("[data-star]");
  if(star){ const o = item(star.dataset.star, star.dataset.id); o.pick = !o.pick; clean(star.dataset.star, star.dataset.id); persist(); render(true); return; }
  const go = t.closest("[data-go]");
  if(go){
    if(!S.me){ const n = prompt("Dein Name (für „Ich gehe“):"); if(!n) return; S.me = n.trim(); document.getElementById("me").value = S.me; }
    const o = item("talks", go.dataset.go); o.who = o.who || [];
    const i = o.who.indexOf(S.me); if(i>=0) o.who.splice(i,1); else { o.who.push(S.me); o.pick = true; }
    clean("talks", go.dataset.go); persist(); render(true); return;
  }
  const f = t.closest("[data-f]");
  if(f){ const [grp,key] = f.dataset.f.split("."); UI[grp][key] = f.dataset.v; UI.limit = {talks:150, booths:150, people:100}; render(false); return; }
  const more = t.closest("[data-more]");
  if(more){ UI.limit[more.dataset.more] += 200; render(true); return; }
  if(t.id==="btnIcs"){ download(`SCC2026_Kalender_${(S.me||"Team").replace(/[^\w-]+/g,"_")}.ics`, icsText(), "text/calendar"); return; }
  const del = t.closest("[data-delc]");
  if(del){ if(confirm("Eintrag löschen?")){ S.custom = S.custom.filter(c=>c.id!==del.dataset.delc); persist(); render(true); } return; }
});
main.addEventListener("change", e=>{
  const t = e.target;
  if(t.dataset.done){ const o = item("booths", t.dataset.done); o.done = t.checked; if(t.checked) o.pick = true; clean("booths", t.dataset.done); persist(); render(true); }
  else if(t.dataset.talked){ const o = item(t.dataset.talked, t.dataset.id); o.status = t.checked ? "gesprochen" : ""; if(t.checked) o.pick = true; clean(t.dataset.talked, t.dataset.id); persist(); render(true); }
  else if(t.dataset.cdone){ const c = S.custom.find(x=>x.id===t.dataset.cdone); if(c){ c.done = t.checked; persist(); } }
  else if(t.dataset.sel){ const [grp,key] = t.dataset.sel.split("."); UI[grp][key] = t.value; render(false); }
});
let noteTimer = null;
main.addEventListener("input", e=>{
  const t = e.target;
  if(t.dataset.note){ const o = item(t.dataset.note, t.dataset.id); o.note = t.value; clearTimeout(noteTimer); noteTimer = setTimeout(()=>{ clean(t.dataset.note, t.dataset.id); persist(); }, 400); }
  else if(t.dataset.q){ const grp = {talk:"talk", booth:"booth", person:"person"}[t.dataset.q]; UI[grp].q = t.value;
    clearTimeout(noteTimer); noteTimer = setTimeout(()=>{ const pos = t.selectionStart; render(true); const el = main.querySelector(`[data-q="${t.dataset.q}"]`); if(el){ el.focus(); el.setSelectionRange(pos,pos); } }, 250); }
});
document.getElementById("me").value = S.me || "";
document.getElementById("me").addEventListener("change", e=>{ S.me = e.target.value.trim(); persist(); render(true); });

// ---------------- custom entries ----------------
const dlg = document.getElementById("dlg");
document.getElementById("btnAdd").addEventListener("click", ()=>{ document.getElementById("dlgForm").reset(); toggleWhen(); if(typeof dlg.showModal === "function") dlg.showModal(); else addViaPrompt(); });
function addViaPrompt(){
  const title = prompt("Titel / Name des Eintrags:"); if(!title) return;
  const date = prompt("Tag (13, 14 oder 15):", "13"); const start = prompt("Von (HH:MM, leer für Aufgabe):", "");
  const end = start ? prompt("Bis (HH:MM):", "") : "";
  S.custom.push({id:"c"+Date.now().toString(36), type: start ? "event" : "task", title: title.trim(),
    date: "2026-10-" + String(date||"13").trim().padStart(2,"0"), start: start||"", end: end||"", loc:"", note:"", by:S.me||""});
  persist(); UI.tab = "plan"; render(false);
}
function toggleWhen(){ document.getElementById("fWhen").style.display = document.getElementById("fType").value==="event" ? "" : "none"; }
document.getElementById("fType").addEventListener("change", toggleWhen);
dlg.addEventListener("close", ()=>{
  if(dlg.returnValue!=="ok") return;
  const title = document.getElementById("fTitle").value.trim(); if(!title) return;
  const type = document.getElementById("fType").value;
  S.custom.push({id:"c"+Date.now().toString(36), type, title, date:document.getElementById("fDate").value,
    start:document.getElementById("fStart").value, end:document.getElementById("fEnd").value,
    loc:document.getElementById("fLoc").value.trim(), note:document.getElementById("fNote").value.trim(), by:S.me||""});
  persist(); UI.tab = "plan"; render(false);
});

// ---------------- save / export / import ----------------
function download(name, text, type){
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type}));
  a.download = name; document.body.appendChild(a); a.click();
  setTimeout(()=>{ URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
function stamp(){ const d = new Date(); return d.toISOString().slice(0,10) + "_" + String(d.getHours()).padStart(2,"0") + String(d.getMinutes()).padStart(2,"0"); }
if(HOSTED) document.getElementById("btnSave").hidden = true;   // online wird laufend gespeichert, Dateikopie ueberfluessig
document.getElementById("btnSave").addEventListener("click", ()=>{
  S.savedAt = Date.now(); S.updatedAt = Math.max(S.updatedAt, S.savedAt);
  const stateEl = document.getElementById("saved-state");
  stateEl.textContent = JSON.stringify(S).replace(/<\//g, "<\\/");
  const mainEl = document.getElementById("main"), keep = mainEl.innerHTML;
  mainEl.innerHTML = STATIC_MAIN;                          // statt gerenderter Inhalte: Lese-Ansicht fuer Vorschauen
  const dialogOpen = dlg.open; if(dialogOpen) dlg.close();
  const html = "<!DOCTYPE html>\n" + document.documentElement.outerHTML;
  mainEl.innerHTML = keep;
  try{ localStorage.setItem(LS_KEY, JSON.stringify(S)); }catch(e){}
  download(`SCC_Planner_${(S.me||"Team").replace(/[^\w-]+/g,"_")}_${stamp()}.html`, html, "text/html");
  showStatus();
});
document.getElementById("btnReset").addEventListener("click", ()=>{
  if(!confirm("Wirklich alles zurücksetzen?\n\nAlle Markierungen, „Ich gehe“, Status, Notizen und eigenen Einträge werden gelöscht.\nTipp: vorher „Export“ als Sicherung." + (HOSTED ? "" : " oder „Speichern“"))) return;
  const me = S.me;
  S = emptyState(); S.me = me;
  noticeDismissed = true;
  persist(); UI.tab = "plan"; render(false);
});
document.getElementById("btnExport").addEventListener("click", ()=>{
  download(`SCC_Notizen_${(S.me||"Team").replace(/[^\w-]+/g,"_")}_${stamp()}.json`, JSON.stringify(S, null, 1), "application/json");
});
document.getElementById("btnImport").addEventListener("click", ()=>document.getElementById("fileImport").click());
document.getElementById("fileImport").addEventListener("change", e=>{
  const f = e.target.files[0]; if(!f) return;
  const r = new FileReader();
  r.onload = ()=>{
    let other = null, txt = String(r.result);
    if(/\.json$/i.test(f.name)) other = readJSON(txt);
    else { const m = txt.match(/<script id="saved-state" type="application\/json">([\s\S]*?)<\/script>/); other = m ? readJSON(m[1]) : null; }
    if(!other || typeof other!=="object"){ alert("Keine Planner-Daten in dieser Datei gefunden."); return; }
    const who = other.me || f.name;
    S = merge(S, Object.assign(emptyState(), other), who);
    persist(); render(true);
    alert("Zusammengeführt mit: " + who);
  };
  r.readAsText(f); e.target.value = "";
});
// Zusammenführen: Merken = ODER, „Ich gehe“ = Vereinigung, Status = weitester, Notizen = beide behalten
function merge(a, b, who){
  const rank = x => x ? 1 : 0;
  for(const kind of ["talks","booths","people","speakers"]){
    a[kind] = a[kind] || {}; const src = b[kind] || {};
    for(const id in src){
      const x = a[kind][id] || (a[kind][id] = {}), y = src[id];
      if(y.pick) x.pick = true;
      if(y.done) x.done = true;
      if(y.who) x.who = [...new Set([...(x.who||[]), ...y.who])];
      if(y.status && rank(y.status) > rank(x.status)) x.status = y.status;
      if(y.note && y.note !== x.note && !(x.note||"").includes(y.note)) x.note = x.note ? `${x.note}\n— ${who||"Import"}: ${y.note}` : y.note;
    }
  }
  const ids = new Set((a.custom||[]).map(c=>c.id));
  a.custom = (a.custom||[]).concat((b.custom||[]).filter(c=>!ids.has(c.id)));
  if(!a.me && b.me && !who) a.me = b.me;
  return a;
}

window.addEventListener("storage", e=>{ if(e.key===LS_KEY){ const n = readJSON(e.newValue||""); if(n){ S = Object.assign(emptyState(), n); render(true); showStatus(); } } });
showStatus();
render(false);
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
