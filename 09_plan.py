# -*- coding: utf-8 -*-
"""
09_plan.py  -  Her seyi tek bir fuar planinda birlestirir: data/SCC_Plan.xlsx

Girdi : data/booths.csv (07), data/talks.csv (08), data/SCC_Univention_Report.xlsx (05),
        data/raw/sessions (speaker'larin session'lari icin)
API kullanmaz, istedigin kadar tekrar calistirabilirsin.

Sekmeler:
  Booths      : gidilecek standlar (priority>=2), hall/stand sirasina gore -> yuruyus rotasi
  Agenda      : dinlenecek session'lar (relevance>=2), gun/saat sirasina gore, cakismalar ve "Wer geht?" kolonu
  Meetings    : gorusulecek kisiler + onlari NEREDE bulacagimiz (stand ya da konusma saati)
  Competitors : rakip standlar
  All_Booths / All_Talks : tum liste, filtrelenebilir
"""

import re

import pandas as pd
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from scc_common import DATA, LABELS, PRIO_COLS, SHEETS, load_pages, org_key, prio_internal, prio_label, print

OUT = DATA / "SCC_Plan.xlsx"
MAX_PER_ORG = 4   # Meetings sekmesinde ayni kurumdan en fazla kac kisi


def stand_sort_key(stand):
    nums = re.findall(r"\d+", str(stand or ""))
    return tuple(int(n) for n in nums) if nums else (999,)


HEAD_FILL = PatternFill("solid", fgColor="D9D9D9")   # sade gri baslik, Excel varsayilan fontu


MARK_FILL = PatternFill("solid", fgColor="FFF2CC")   # Prio 1 / empfohlen satirlari


def write_sheet(xw, df, name, widths, mark=None):
    df = df.apply(lambda col: col.map(lambda v: ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v))
    if "is_competitor" in df.columns:
        df["is_competitor"] = df["is_competitor"].map(lambda v: "ja" if str(v).lower() == "true" else "")
    if "userType" in df.columns:
        df["userType"] = df["userType"].map(lambda v: {"attendee": "Besucher", "staff": "Aussteller",
                                                       "speaker": "Speaker", "none": ""}.get(v, v))
    # Prio: intern 3 = am wichtigsten -> angezeigt "1" (wie im Team gewohnt), 0 -> "–"
    for c in PRIO_COLS:
        if c in df.columns:
            df[c] = df[c].map(prio_label)
    # sayilar Excel'de "627.0" gibi gorunmesin: tam sayi kolonlarini tam sayiya cevir
    for c in ("li_followers", "n_sessions", "speaker_priority"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
    keys = list(df.columns)
    df = df.rename(columns=LABELS)
    df.to_excel(xw, sheet_name=name, index=False)
    ws = xw.sheets[name]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, col in enumerate(keys, 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True)
        c.fill = HEAD_FILL
        w = widths.get(col, 14)
        ws.column_dimensions[get_column_letter(i)].width = w
        if w >= 35:
            for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                row[0].alignment = Alignment(wrap_text=True, vertical="top")
    if mark is not None:
        for r, m in enumerate(list(mark), start=2):
            if m:
                for cell in ws[r]:
                    cell.fill = MARK_FILL


def write_overview(ws, b, a, report, allp, speakers, booths, talks, n_b2=0, n_a2=0, n_k2=0, mgmt=None):
    """Kisa, sade bir ilk sayfa."""
    bold = Font(bold=True)
    row = [1]

    def line(text="", font=None):
        c = ws.cell(row=row[0], column=1, value=text)
        if font:
            c.font = font
        row[0] += 1

    def table(title, df, cols):
        line(title, bold)
        for j, c in enumerate(cols, 1):
            cell = ws.cell(row=row[0], column=j, value=LABELS.get(c, c))
            cell.font = bold
            cell.fill = HEAD_FILL
        row[0] += 1
        for _, r in df[cols].iterrows():
            for j, c in enumerate(cols, 1):
                v = r[c]
                ws.cell(row=row[0], column=j, value=ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v)
            row[0] += 1
        line()

    n_stands = b["main_stand"].nunique() if "main_stand" in b.columns else len(b)
    line("Smart Country Convention 2026 – Messevorbereitung", Font(bold=True, size=13))
    line(f"Stand: {pd.Timestamp.now():%d.%m.%Y}")
    line()
    line("Prio 1 = unbedingt, Prio 2 = wenn Zeit ist, Prio 3 = nur bei Gelegenheit, – = nicht relevant. "
         "Prio-1-Zeilen sind gelb markiert.")
    line(f"Stände: {len(b)} Aussteller mit Prio 1 an {n_stands} Ständen, {n_b2} mit Prio 2 "
         f"(Blatt „Stände“, oben beginnend, nach Halle/Stand sortiert).")
    line(f"Vorträge: {len(a)} mit Prio 1, {n_a2} mit Prio 2 (Blatt „Vorträge“). In „Wer geht?“ bitte eintragen.")
    n_m = 0 if mgmt is None else len(mgmt)
    line(f"Kontakte: {len(report)} empfohlen, {n_k2} weitere, {n_m} Management (Blatt „Kontakte“, Spalte „Stufe“).")
    line("  empfohlen = wichtigste Gesprächspartner:innen für das Messeteam: Fachebene (IT-Leitung, Architektur, "
         "IAM/Plattform, Betrieb, Schul-IT, Produkt/Partner) bei relevanten Organisationen, max. 3 pro Organisation.")
    line("  weitere = ebenfalls hoch bewertet, aber Rolle unklar oder Organisation schon mit 3 Personen vertreten.")
    line("  Management = oberste Leitung (CEO/Geschäftsführung, Präsident:in, Bürgermeister:in) – eher für die Geschäftsführung.")
    line("Wettbewerber sind im Blatt „Stände“ in der Spalte „Wettbewerber“ markiert.")
    line("Nur intern verwenden (personenbezogene Daten).")
    line()
    # Wichtigste Stände: fiziksel stand bazinda. Ayni standda cok sayida Prio-3 firma olan ortak standlar
    # (OSBA, ZenDiS/openDesk, Vitako...) ve cok kontaklimiz olanlar once gelir.
    bb = b.copy()
    bb["_st"] = bb["stand"].astype(str).str.split(" / ").str[0].str.strip()
    bb["_c"] = pd.to_numeric(bb.get("our_priority_contacts", 0), errors="coerce").fillna(0)
    gs = (bb.groupby("_st").agg(stand=("_st", "first"), n=("exhibitor", "count"), c=("_c", "sum"),
                                exhibitor=("exhibitor", lambda x: "; ".join(x)),
                                visit_goal=("visit_goal", lambda x: ", ".join(dict.fromkeys(x))))
          .sort_values(["n", "c"], ascending=False).head(15))
    table("Wichtigste Stände", gs, ["stand", "exhibitor", "visit_goal"])
    aa = a.copy()
    aa["_r"] = pd.to_numeric(aa["relevance"], errors="coerce")
    days = {"2026-10-13": "Dienstag, 13.10.", "2026-10-14": "Mittwoch, 14.10.", "2026-10-15": "Donnerstag, 15.10."}
    for d, g in aa.groupby("date"):
        table(f"Vorträge {days.get(d, d)}", g.sort_values(["_r", "start"], ascending=[False, True]).head(8).sort_values("start"),
              ["start", "location", "title", "goal"])
    # Wichtigste Kontakte: Fachebene (Feedback: Top-Management pflegt die Geschaeftsfuehrung selbst).
    # Zuerst die, deren Ort (Talk/Stand) bekannt ist.
    rr = report.copy()
    rr["_s"] = (rr["wo_finden"].astype(str) != "").astype(int)
    table("Wichtigste Kontakte (Fachebene)", rr.sort_values("_s", ascending=False, kind="stable").head(15),
          ["name", "position", "organization", "wo_finden"])
    if mgmt is not None and len(mgmt):
        table("Management-Kontakte (eher für die Geschäftsführung)", mgmt.head(10),
              ["name", "position", "organization", "wo_finden"])
    for col, w in zip("ABCD", (26, 60, 45, 60)):
        ws.column_dimensions[col].width = w


def main():
    booths = pd.read_csv(DATA / "booths.csv").fillna("")
    talks = pd.read_csv(DATA / "talks.csv").fillna("")
    report = pd.read_excel(DATA / "SCC_Univention_Report.xlsx", sheet_name="meeting_shortlist").fillna("")

    # ---- Booths: rota sirasi (hall, stand). Ortak standlari (orn. OSBA, ZenDiS, Vitako) isaretle ----
    booths["main_stand"] = booths["stand"].astype(str).str.split(" / ").str[0].str.strip()
    by_stand = booths.groupby("main_stand")["exhibitor"].apply(list).to_dict()
    booths["same_stand_with"] = [", ".join(x for x in by_stand.get(st, []) if x != ex)
                                 for st, ex in zip(booths["main_stand"], booths["exhibitor"])]
    # ---- Elle duzeltmeler (istege bagli), Prio wie angezeigt (1 = hoechste, "-" = nicht relevant):
    #   data/overrides_talks.csv  -> id,prio            (id: Spalte "ID" im Blatt "Vorträge")
    #   data/overrides_booths.csv -> exhibitor,prio     (exhibitor: genauer Name aus Spalte "Aussteller")
    # (alte Dateien mit relevance / visit_priority in interner Skala 0-3 funktionieren weiter)
    def override_map(f, key, old_col):
        o = pd.read_csv(f, sep=None, engine="python", dtype=str).fillna("")
        o.columns = [c.strip() for c in o.columns]
        if "prio" in o.columns:
            return dict(zip(o[key].str.strip(), o["prio"].map(prio_internal)))
        return dict(zip(o[key].str.strip(), pd.to_numeric(o[old_col], errors="coerce").fillna(0)))
    ot = DATA / "overrides_talks.csv"
    if ot.exists():
        om = override_map(ot, "id", "relevance")
        m_ = talks["id"].astype(str).isin(om)
        talks.loc[m_, "relevance"] = talks.loc[m_, "id"].astype(str).map(om)
        print(f"overrides_talks.csv: {int(m_.sum())} session elle guncellendi")
    ob = DATA / "overrides_booths.csv"
    if ob.exists():
        om = override_map(ob, "exhibitor", "visit_priority")
        m_ = booths["exhibitor"].astype(str).str.strip().isin(om)
        booths.loc[m_, "visit_priority"] = booths.loc[m_, "exhibitor"].astype(str).str.strip().map(om)
        print(f"overrides_booths.csv: {int(m_.sum())} stand elle guncellendi")

    vp = pd.to_numeric(booths["visit_priority"], errors="coerce")

    def route(df):
        df = df.copy()
        df["_k"] = df["stand"].map(stand_sort_key)
        return df.sort_values("_k").drop(columns="_k")

    b = route(booths[vp == 3])          # Pflicht
    b_more = route(booths[vp == 2])     # lohnt sich

    # ---- Agenda: tekrarlanan session'lari tek satira indir (diger slotlar also_at'te) ----
    # Ayni baslik + ayni host + ayni speaker = tekrar. ("International Keynote" gibi genel basliklar ayri kalir)
    # ayni session birden fazla slotta farkli puan almis olabilir -> hepsine en yuksek puani ver (sayilar tutarli olsun)
    talks["relevance"] = pd.to_numeric(talks["relevance"], errors="coerce").fillna(0)
    talks["relevance"] = talks.groupby(["title", "host_org", "speakers"])["relevance"].transform("max")
    rv = pd.to_numeric(talks["relevance"], errors="coerce")
    # Guvenlik agi: model 0-1 verdi ama baslik/aciklama/track'te cekirdek konu kelimesi geciyor -> kontrol icin More'a
    kw = re.compile(r"(?i)identit|\biam\b|\bidm\b|\bsso\b|single sign|keycloak|opendesk|zendis|open.?source|"
                    r"schul|school|eudi|wallet|bundid|nutzerkonto|deutschland.?stack|germany stack|verzeichnis|"
                    r"directory|arbeitsplatz|workplace|souver|sovereign")
    text = talks["title"].astype(str) + " " + talks["teaser"].astype(str) + " " + talks["tracks"].astype(str)
    talks["check"] = ""
    net = (rv <= 1) & text.str.contains(kw)
    talks.loc[net, "check"] = "evtl. relevant, bitte prüfen"

    def agenda(df):
        df = df.copy()
        df["Wer geht?"] = ""
        return df.drop_duplicates(["title", "host_org", "speakers"], keep="first")   # zamana gore sirali

    a = agenda(talks[rv == 3])                  # Pflicht
    a_more = agenda(talks[(rv == 2) | net])     # lohnt sich + kontrol edilecekler
    a_more = a_more.sort_values(["date", "start"])
    a_cols = ["date", "start", "end", "location", "relevance", "title", "topics", "why", "goal",
              "speakers", "overlaps_with", "also_at", "check", "Wer geht?", "format", "host_org"]
    a_cols = [c for c in a_cols if c in a.columns]

    # ---- Meetings: kisiyi nerede buluruz? ----
    report["id"] = report["ProfileURL"].astype(str).str.extract(r"--u-(.+)$")[0]
    stand_by_org = {r["org_key"]: f"Stand {r['stand']}" for _, r in booths.iterrows() if r["stand"]}
    talks_by_user = {}
    for s in load_pages("sessions"):
        for p in s.get("persons") or []:
            if p.get("userId"):
                talks_by_user.setdefault(p["userId"], []).append(
                    f"Talk {s.get('date', '')[5:]} {s.get('start', '')} @ {s.get('location', '')}")
    where = []
    for _, r in report.iterrows():
        w = []
        if r["id"] in talks_by_user:
            w += talks_by_user[r["id"]]
        st = stand_by_org.get(org_key(r["organization"]))
        if st:
            w.append(st + (" (eigener Stand)" if r["userType"] == "staff" else " (Stand der Organisation)"))
        where.append(" | ".join(w))
    report["wo_finden"] = where

    # ---- Meetings'i gercekten gorusulebilir boyuta indir ----
    # 05 kisi puanlamasi comert: ~2.200 kisi priority>=2. Plan icin:
    #  - priority 3 VE rolu biliniyor (pozisyon ya da LinkedIn headline) VE marketing/HR/event degil
    #  - + priority>=2 olan speaker'lar
    #  - ayni kurumdan en fazla MAX_PER_ORG kisi
    # Geri kalanlar All_People sekmesinde (priority filtresiyle) duruyor.
    neg = re.compile(r"(?i)\b(?:marketing|event\w*|hr|human resources|personal\w*|recruit\w*|assisten\w*|"
                     r"assistant|werkstudent\w*|praktikant\w*|intern|trainee|communication\w*|\w*kommunikation|presse)\b")
    pr = pd.to_numeric(report["priority"], errors="coerce").fillna(0)
    has_role = (report["position"].astype(str).str.strip() != "") | \
               (report.get("li_headline", pd.Series("", index=report.index)).astype(str).str.strip() != "")
    is_neg = report["position"].astype(str).str.contains(neg)
    keep = ((pr == 3) & has_role & ~is_neg) | ((pr >= 2) & (report["userType"] == "speaker"))
    report = report[keep].copy()
    report["_p"] = pd.to_numeric(report["priority"], errors="coerce")
    report["_org"] = report["organization"].map(org_key)
    report = (report.sort_values(["_p", "userType"], ascending=[False, True])
              .groupby("_org", sort=False).head(MAX_PER_ORG).drop(columns=["_p", "_org"]))
    report["id"] = report["ProfileURL"].astype(str).str.extract(r"--u-(.+)$")[0].fillna("")

    # 08b_contacts.py calistirildiysa: genis aday havuzundan yeniden degerlendirilmis liste kullanilir
    # (programdaki konusmacilar + kilit kurumlardaki pozisyonsuz kisiler dahil)
    report_more = report.iloc[0:0]
    report_mgmt = report.iloc[0:0]
    cf = DATA / "contacts.csv"
    if cf.exists():
        c = pd.read_csv(cf).fillna("")
        c["_p"] = pd.to_numeric(c["priority"], errors="coerce").fillna(0)
        c["_org"] = c["organization"].map(org_key)
        c.loc[c["_org"] == "", "_org"] = "name:" + c["name"].astype(str)   # kurumu bos olanlar ayri grup
        cat_order = {"Souveränität/openDesk-Ökosystem": 0, "Öffentlicher IT-Dienstleister": 1,
                     "Schul-IT/Bildung": 2, "Entscheider Verwaltung": 3, "Partner/Integrator": 4,
                     "Politik/Multiplikator": 5, "Wettbewerber": 6, "Sonstiges": 7}
        c["_c"] = c["keep_for_person"].map(cat_order).fillna(9)
        c["_w"] = (c["wo_finden"] != "").astype(int)
        c["userType"] = c["userType"].replace({"": "Programm-Speaker"})
        c.loc[c["source"].astype(str) == "program", "userType"] = "Programm-Speaker"
        # Iki ayrim (Feedback: "Kontakte sind sehr high level, eher etwas fuer die Geschaeftsfuehrung"):
        #  empfohlen  = Prio 3, Ebene "Fachebene", Rolle bekannt und zeigt Verantwortung (Leitung, Referat,
        #               Architektur, Produkt, Plattform, IAM, Betrieb, Schul-IT ...), kurum basina en fazla 3
        #  Management = Ebene "Management" (CEO, Vorstand, Praesident:in ...) mit Prio >= 2, kurum basina 2
        #  weitere    = geri kalan Prio 3
        if "level" not in c.columns:
            c["level"] = ""
        c["level"] = c["level"].replace("", "Fachebene")
        # Modell-Ebene per Titel korrigieren: CIO/CDO/IT-Leitung sind Ansprechpartner fuer das Messeteam
        # (Fachebene); CEO/Geschaeftsfuehrung/Vorstand/Buergermeister:in usw. immer Management.
        pos_ = (c["position"].astype(str) + " " + c["li_headline"].astype(str))
        # Wortgrenzen wichtig: sonst "Landratsamt" -> Landrat, "Ministerium" -> Minister, "Referentin des Vorstands"
        top_ = pos_.str.contains(r"(?i)\b(?:ceo|coo|cfo)\b|chief executive|managing director|\bgeschäftsführ\w*|"
                                 r"\b(?:vize)?präsident(?:in)?\b|\b(?:vice )?president\b|^\s*vorstand|\bvorständin\b|"
                                 r"\bvorstandsvorsitz\w*|\bstaatssekretär(?:in)?\b|state secretary|\bminister(?:in)?\b|"
                                 r"\b(?:ober)?bürgermeister(?:in)?\b|\bmayor\b|\blandrat\b|\blandrätin\b|"
                                 r"mitglied der geschäftsleitung|\bkreisr(?:at|ätin)\b|\bregionsr(?:at|ätin)\b|"
                                 r"\bstadtr(?:at|ätin)\b|behördenleit|amtschef")
        it_ = pos_.str.contains(r"(?i)\b(?:cio|cdo|cto|ciso)\b|chief (?:information|digital|technology)|it-leit|"
                                r"leiter\w* (?:der )?(?:it|digitalisierung)|head of it|leitung (?:it|digitalisierung)")
        c.loc[top_, "level"] = "Management"
        c.loc[it_ & ~top_, "level"] = "Fachebene"
        lead = re.compile(r"(?i)\b(?:cio|cdo|cto|ciso|chief)\b|leit|leiter|leitung|head|director|direktor|"
                          r"dezernent|referent|lead\b|owner|partner|produkt|product|architekt|architect|"
                          r"admin|systembetreu|\biam\b|\bidm\b|identity|plattform|platform|schul-?it|workplace|"
                          r"arbeitsplatz|engineer|entwickl|betrieb|infrastru|koordinat|verantwortlich|projektleit")
        role = (c["position"].astype(str) + " " + c["li_headline"].astype(str)).str.strip()
        # Univention'la ilgisi zayif alanlar (Geodaten, Smart-City-Daten, dijital ikiz...) ana listeye girmez
        off = re.compile(r"(?i)geo|kartograph|vermess|urban|zwilling|twin|smart.?city|smart.?region|mobilit|verkehr|"
                         r"\bbau|umwelt|klima|energie|abfall|bergbau")
        org_off = c["organization"].astype(str).str.contains(off)
        c = c.sort_values(["_c", "_w"], ascending=[True, False])
        role = role.loc[c.index]
        is_mgmt = c["level"] == "Management"
        is_work = (role != "") & role.str.contains(lead) & ~role.str.contains(off) & ~org_off.loc[c.index]
        tier_a = c[(c["_p"] == 3) & ~is_mgmt & is_work].groupby("_org", sort=False).head(3)
        # Management: nur relevante Organisationen (keine "Sonstiges", keine fachfremden), kurum basina 2
        tier_m = c[(c["_p"] >= 2) & is_mgmt & (c["keep_for_person"] != "Sonstiges") & ~org_off.loc[c.index]
                   & (pd.to_numeric(c["org_relevance"] if "org_relevance" in c else 3, errors="coerce") >= 2)]
        tier_m = tier_m.groupby("_org", sort=False).head(2)
        tier_b = c[(c["_p"] == 3) & ~c.index.isin(tier_a.index) & ~c.index.isin(tier_m.index)]
        drop = ["_p", "_org", "_c", "_w"]
        report, report_more, report_mgmt = tier_a.drop(columns=drop), tier_b.drop(columns=drop), tier_m.drop(columns=drop)
        print(f"contacts.csv kullanildi: {len(report)} empfohlen (Fachebene) + {len(report_more)} weitere "
              f"+ {len(report_mgmt)} Management")
    m_cols = ["priority", "name", "position", "organization", "level", "keep_for_person", "wo_finden",
              "talking_point", "why_person", "relationship", "LinkedIn", "li_headline", "li_followers", "userType",
              "ProfileURL", "id"]
    m_cols = [c for c in m_cols if c in report.columns or c in report_more.columns or c in report_mgmt.columns]

    comp = booths[booths["is_competitor"].astype(str).str.lower() == "true"].copy()

    W = {"exhibitor": 30, "why": 45, "booth_question": 50, "contacts_to_meet": 50, "categories": 35,
         "title": 45, "goal": 40, "speakers": 55, "overlaps_with": 45, "also_at": 25, "check": 30, "topics": 30, "location": 20,
         "name": 22, "position": 30, "organization": 30, "wo_finden": 35, "talking_point": 50,
         "why_person": 50, "keep_for_person": 25, "LinkedIn": 30, "li_headline": 35, "stand": 16,
         "visit_goal": 22, "host_org": 25, "teaser": 50, "relationship": 25, "level": 12}
    # ---- All_People: tum kayitli kisiler (attendee, staff, speaker, none) ----
    allp = pd.read_excel(DATA / "SCC_Univention_Report.xlsx", sheet_name="all_attendees").fillna("")
    allp["id"] = allp["ProfileURL"].astype(str).str.extract(r"--u-(.+)$")[0]
    allp["wo_finden"] = [" | ".join(talks_by_user.get(i, []) + ([stand_by_org[org_key(o)]]
                         if org_key(o) in stand_by_org else [])) for i, o in zip(allp["id"], allp["organization"])]
    p_cols = [c for c in ["priority", "name", "position", "organization", "userType", "sector",
                          "keep_for_person", "wo_finden", "talking_point", "why_person", "LinkedIn",
                          "li_headline", "li_followers", "City", "Country", "ProfileURL"] if c in allp.columns]

    # ---- All_Speakers: programdaki TUM konusmacilar (networking'e kayitli olmayanlar dahil) ----
    rel = dict(zip(talks["id"], pd.to_numeric(talks["relevance"], errors="coerce").fillna(0)))
    prio = dict(zip(allp["id"], pd.to_numeric(allp["priority"], errors="coerce").fillna(0)))
    spk = {}
    for s_ in load_pages("sessions"):
        for p_ in s_.get("persons") or []:
            k_ = p_.get("id") or f"{p_.get('firstName')}{p_.get('lastName')}"
            d_ = spk.setdefault(k_, {
                "name": f"{p_.get('firstName', '')} {p_.get('lastName', '')}".strip(),
                "position": p_.get("position", ""), "organization": p_.get("organization", ""),
                "person_priority": prio.get(p_.get("userId"), ""), "max_talk_relevance": 0, "sessions": []})
            d_["max_talk_relevance"] = max(d_["max_talk_relevance"], rel.get(s_["id"], 0))
            d_["sessions"].append(f"{s_.get('date', '')[5:]} {s_.get('start', '')} @ {s_.get('location', '')}: "
                                  f"{s_.get('name', '')[:70]}")
    speakers = pd.DataFrame(spk.values())
    if len(speakers):
        speakers["n_sessions"] = speakers["sessions"].map(len)
        speakers["sessions"] = speakers["sessions"].map(" | ".join)
        speakers = speakers.sort_values(["max_talk_relevance", "n_sessions"], ascending=False)

    W.update({"sessions": 70, "sector": 22, "ProfileURL": 30})

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        ab_cols = [c for c in ["id", "visit_priority", "hall", "stand", "exhibitor", "visit_goal", "why",
                               "booth_question", "contacts_to_meet", "same_stand_with", "is_competitor",
                               "partner_level", "categories", "teaser"] if c in booths.columns]
        at_cols = [c for c in ["id", "date", "start", "end", "location", "relevance", "title", "topics", "why",
                               "goal", "speakers", "host_org", "format", "tracks", "also_at", "overlaps_with",
                               "teaser"] if c in talks.columns]
        # --- Stände: tum firmalar tek sekmede. Once Prio 1 (rota sirasi), sonra Prio 2, sonra digerleri ---
        bs = booths.copy()
        bs["_p"] = pd.to_numeric(bs["visit_priority"], errors="coerce").fillna(0)
        bs["_k"] = bs["stand"].map(stand_sort_key)
        bs = bs.sort_values(["_p", "_k"], ascending=[False, True])
        st_cols = [c for c in ["visit_priority", "hall", "stand", "exhibitor", "visit_goal", "why", "booth_question",
                               "relationship", "contacts_to_meet", "same_stand_with", "is_competitor", "categories", "teaser", "id"]
                   if c in bs.columns]

        # --- Vorträge: tum session'lar tek sekmede, tekrarlar tek satir (diger slotlar "Auch am") ---
        ts = talks.copy()
        ts["_r"] = pd.to_numeric(ts["relevance"], errors="coerce").fillna(0)
        ts = ts.sort_values(["date", "start"]).drop_duplicates(["title", "host_org", "speakers"], keep="first")
        ts = ts.sort_values(["_r", "date", "start"], ascending=[False, True, True])
        ts["Wer geht?"] = ""
        vt_cols = [c for c in ["relevance", "date", "start", "end", "location", "title", "topics", "why", "goal",
                               "speakers", "overlaps_with", "also_at", "check", "Wer geht?", "format", "host_org",
                               "tracks", "teaser", "id"] if c in ts.columns]

        # --- Kontakte: empfohlen + weitere + Management tek sekmede, "Stufe" kolonuyla ---
        k1 = report.copy(); k1["tier"] = "empfohlen"
        k2 = report_more.copy(); k2["tier"] = "weitere"
        k3 = report_mgmt.copy(); k3["tier"] = "Management"
        ks = pd.concat([k1, k2, k3], ignore_index=True)
        k_cols = ["tier"] + [c for c in m_cols if c in ks.columns]

        pd.DataFrame().to_excel(xw, sheet_name=SHEETS["overview"])   # asagida doldurulur
        write_sheet(xw, bs[st_cols], SHEETS["booths"], W, mark=(bs["_p"] == 3))
        write_sheet(xw, ts[vt_cols], SHEETS["agenda"], W, mark=(ts["_r"] == 3))
        write_sheet(xw, ks[k_cols], SHEETS["meetings"], W, mark=(ks["tier"] == "empfohlen"))
        write_sheet(xw, allp[p_cols], SHEETS["people"], W)
        write_sheet(xw, speakers, SHEETS["speakers"], W)
        write_overview(xw.sheets[SHEETS["overview"]], b, a, report, allp, speakers, booths, talks,
                       n_b2=len(b_more), n_a2=int((ts["_r"] == 2).sum()), n_k2=len(report_more),
                       mgmt=report_mgmt)

    print(f"Booths Pflicht: {len(b)} ({b['main_stand'].nunique()} Stand) + {len(b_more)} optional | "
          f"Agenda Pflicht: {len(a)} + {len(a_more)} optional | "
          f"Meetings: {len(report)} (yeri belli: {int((report['wo_finden'] != '').sum())}) | Rakip stand: {len(comp)}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
