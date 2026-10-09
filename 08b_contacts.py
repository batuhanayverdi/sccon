# -*- coding: utf-8 -*-
"""
08b_contacts.py  -  "Empfohlene Kontakte" listesini genis bir aday havuzundan yeniden olusturur.

Neden: 05'in listesi sadece networking'e kayitli kisilerden geliyordu. Programdaki konusmacilarin
cogu (ZenDiS, Dataport yonetimi, ITZBund, FITKO...) orada yok; kilit kurumlarda pozisyonu bos olanlar da
eleniyordu. Bu adim uc kaynaktan aday toplar ve hepsini ayni kriterle OpenAI'ye tekrar degerlendirir:

  A) Networking katilimcilari: 05'te priority >= 2 ve rolu belli (pozisyon ya da LinkedIn headline) ya da speaker
  B) Programdaki TUM konusmacilar (networking'e kayitli olmasalar da), konustuklari session'larla birlikte
  C) Kilit kurumlardan pozisyonu bos kisiler (kurum basina en fazla 3): kamu IT hizmet saglayicilari,
     Bund/Land, egitim idareleri, dernekler; ya da standi Prio 3 olan kurumlar

Girdi : data/SCC_Univention_Report.xlsx (05), data/companies_classified.csv (03), data/booths.csv (07),
        data/talks.csv (08), data/raw/sessions (01)
Cikti : data/contacts.csv  (09 bunu "Empfohlene Kontakte" icin kullanir)
Cache : data/llm_cache/contacts_v1.jsonl
"""

import re
from collections import defaultdict

import pandas as pd

from scc_common import (DATA, UNIVENTION_CONTEXT, get_openai_client, llm_json, load_pages, org_key, print,
                        run_cached)

BATCH = 12
CACHE = DATA / "llm_cache" / "contacts_v1.jsonl"
BASE = "https://online.smartcountry.berlin"
EXCLUDE = re.compile(r"univention|smart country convention|messe berlin", re.I)
KEY_SECTORS = {"Öffentlicher IT-Dienstleister", "Bund", "Land", "Schulträger/Bildungsverwaltung",
               "Verband/Community/Medien"}
MAX_NO_ROLE_PER_ORG = 3
NEG_ROLE = re.compile(r"(?i)\b(?:marketing|event\w*|hr|human resources|personal\w*|recruit\w*|assisten\w*|"
                      r"assistant|werkstudent\w*|praktikant\w*|intern|trainee|communication\w*|\w*kommunikation|presse)\b")

CATEGORIES = ["Entscheider Verwaltung", "Öffentlicher IT-Dienstleister", "Schul-IT/Bildung",
              "Souveränität/openDesk-Ökosystem", "Partner/Integrator", "Wettbewerber",
              "Politik/Multiplikator", "Sonstiges"]

SYSTEM = UNIVENTION_CONTEXT + """

Du wählst für das Univention-Team auf der Smart Country Convention die Personen aus, mit denen ein
Gespräch am meisten bringt (Vertrieb, Partnerschaften, Produktfeedback). Bewerte jede Person nur anhand
der Daten; nichts erfinden.

priority (0-3):
3 = unbedingt ansprechen:
    - Leitung/Entscheider (CEO, CIO, CDO, Geschäftsführung, Abteilungs-/Referatsleitung, Staatssekretär:in,
      Minister:in) bei öffentlichen IT-Dienstleistern, Ländern, Bund, Kommunen oder Bildungsverwaltungen
    - Verantwortliche für IT-Betrieb, IAM/IdM, Plattformen, Arbeitsplatz/Kollaboration oder Schul-IT
    - Leitung und Produkt-/Partnerverantwortliche im Souveränitäts-/openDesk-Ökosystem
      (ZenDiS, OSBA, Sovereign Cloud Stack, Open-Source-Hersteller) und bei passenden Partnern/Integratoren
    - Speaker, deren Session direkt Univention-Themen betrifft (Identität, Souveränität, openDesk,
      Deutschland-Stack, Plattformen, Schul-IT)
2 = lohnt sich: passende Organisation und plausible Rolle, oder Multiplikator (Verband, Presse, Politik)
1 = geringer Bezug (fachfremde Rolle, Themen wie Geodaten, Bau, Smart-City-Daten, KI-Anwendungen ohne
    Plattform-/Identitätsbezug)
0 = kein Bezug
Ist die Position unbekannt, entscheidet die Organisation; dann höchstens 2, außer die Organisation ist ein
zentraler Akteur (z.B. großer öffentlicher IT-Dienstleister, ZenDiS, Bildungsverwaltung eines Landes).
Wettbewerber (org_is_competitor) höchstens 2, category "Wettbewerber".

why: EIN Satz (max. 20 Wörter), nur belegbare Fakten aus den Daten.
talking_point: EIN konkreter Gesprächseinstieg (max. 25 Wörter), der zur tatsächlichen Rolle bzw. Session
passt. Nicht jedem IdM aufdrängen: nur ansprechen, wenn es zur Rolle passt; sonst an Session, Organisation
oder Souveränität/Plattform anknüpfen. Keine Behauptungen über die Organisation, die nicht in den Daten stehen.
Alles auf Deutsch."""

ITEM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "priority", "category", "why", "talking_point"],
    "properties": {
        "id": {"type": "string"},
        "priority": {"type": "integer", "enum": [0, 1, 2, 3]},
        "category": {"type": "string", "enum": CATEGORIES},
        "why": {"type": "string"},
        "talking_point": {"type": "string"},
    },
}


def s(v):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def slug(x):
    import unicodedata
    x = unicodedata.normalize("NFKD", s(x).replace("ß", "ss")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", x).strip("-")


def main():
    rep = pd.read_excel(DATA / "SCC_Univention_Report.xlsx", sheet_name="all_attendees").fillna("")
    rep["id"] = rep["ProfileURL"].astype(str).str.extract(r"--u-(.+)$")[0].fillna("")
    rep["org_key"] = rep["organization"].map(org_key)
    comp = pd.read_csv(DATA / "companies_classified.csv").fillna("")
    comp_by = comp.drop_duplicates("org_key").set_index("org_key")
    booths = pd.read_csv(DATA / "booths.csv").fillna("")
    booth_by = {}
    for _, b in booths.sort_values("visit_priority", ascending=False).iterrows():
        booth_by.setdefault(b["org_key"], (s(b["stand"]), int(float(b["visit_priority"] or 0))))
    talks = pd.read_csv(DATA / "talks.csv").fillna("")
    trel = dict(zip(talks["id"], pd.to_numeric(talks["relevance"], errors="coerce").fillna(0).astype(int)))

    def org_info(org):
        k = org_key(org)
        c = comp_by.loc[k] if k in comp_by.index else None
        st, bp = booth_by.get(k, ("", 0))
        return {
            "org_sector": "" if c is None else s(c.get("sector")),
            "org_relevance": 0 if c is None else int(float(c.get("relevance") or 0)),
            "org_why": "" if c is None else s(c.get("why")),
            "org_is_competitor": False if c is None else str(c.get("is_competitor")).lower() == "true",
            "booth": st, "booth_priority": bp,
        }

    # ---- program konusmacilari ve session'lari ----
    spk = {}          # key -> dict
    by_user = defaultdict(list)
    for sess in load_pages("sessions"):
        r = trel.get(sess["id"], 0)
        line = f"{sess.get('date', '')[5:]} {sess.get('start', '')} @ {sess.get('location', '')}"
        title = f"[R{r}] {sess.get('name', '')[:90]}"
        for p in sess.get("persons") or []:
            key = p.get("userId") or f"p:{p.get('id')}"
            d = spk.setdefault(key, {"name": f"{s(p.get('firstName'))} {s(p.get('lastName'))}".strip(),
                                     "position": s(p.get("position")), "organization": s(p.get("organization")),
                                     "person_id": s(p.get("id")), "talks": [], "where": [], "max_rel": 0})
            d["talks"].append(title)
            d["where"].append(f"Talk {line}")
            d["max_rel"] = max(d["max_rel"], r)
            if p.get("userId"):
                by_user[p["userId"]].append(f"Talk {line}")

    cands = {}

    def add(cid, base, source):
        if EXCLUDE.search(base.get("organization", "")):
            return
        if cid in cands:
            cands[cid]["source"] = cands[cid]["source"] + "+" + source
            return
        cands[cid] = {**base, "id": cid, "source": source, **org_info(base.get("organization", ""))}

    # A) networking: priority>=2 ve rolu belli, ya da speaker. Marketing/HR/Event/Assistenz rolleri haric.
    pr = pd.to_numeric(rep["priority"], errors="coerce").fillna(0)
    has_role = (rep["position"].astype(str).str.strip() != "") | (rep["li_headline"].astype(str).str.strip() != "")
    neg = rep["position"].astype(str).str.contains(NEG_ROLE)
    for _, r in rep[(((pr >= 2) & has_role) | (rep["userType"] == "speaker")) & ~neg].iterrows():
        if not r["id"]:
            continue
        add(r["id"], {"name": r["name"], "position": s(r["position"]), "organization": s(r["organization"]),
                      "linkedin_headline": s(r["li_headline"]), "role_at_event": s(r["userType"]),
                      "LinkedIn": s(r["LinkedIn"]), "li_followers": r["li_followers"], "ProfileURL": s(r["ProfileURL"])},
            "networking")

    # B) programdaki konusmacilar (max_rel>=2 ya da kurumu relevance>=2)
    for key, d in spk.items():
        oi = org_info(d["organization"])
        if d["max_rel"] < 2 and oi["org_relevance"] < 2:
            continue
        att = rep[rep["id"] == key]
        base = {"name": d["name"], "position": d["position"], "organization": d["organization"],
                "sessions": " | ".join(d["talks"][:4]), "role_at_event": "speaker"}
        if len(att):
            a = att.iloc[0]
            base.update({"linkedin_headline": s(a["li_headline"]), "LinkedIn": s(a["LinkedIn"]),
                         "li_followers": a["li_followers"], "ProfileURL": s(a["ProfileURL"])})
            if key in cands:
                cands[key]["sessions"] = base["sessions"]
                cands[key]["source"] += "+program"
                continue
        else:
            base["ProfileURL"] = f"{BASE}/person/person-{slug(d['name'])}--p-{d['person_id']}"
        add(key, base, "program")

    # C) kilit kurumlarda pozisyonu bos olanlar (kurum basina en fazla 3, once staff)
    n_by_org = defaultdict(int)
    noro = rep[~has_role & (rep["id"] != "")].copy()
    noro["_staff"] = (noro["userType"] == "staff").astype(int)
    for _, r in noro.sort_values("_staff", ascending=False).iterrows():
        oi = org_info(r["organization"])
        key_org = oi["org_relevance"] >= 3 and (oi["org_sector"] in KEY_SECTORS or oi["booth_priority"] >= 3)
        if not key_org or n_by_org[r["org_key"]] >= MAX_NO_ROLE_PER_ORG or r["id"] in cands:
            continue
        n_by_org[r["org_key"]] += 1
        add(r["id"], {"name": r["name"], "position": "", "organization": s(r["organization"]),
                      "role_at_event": s(r["userType"]), "LinkedIn": s(r["LinkedIn"]),
                      "li_followers": r["li_followers"], "ProfileURL": s(r["ProfileURL"])}, "key-org")

    df = pd.DataFrame(cands.values()).fillna("")
    print(f"Adaylar: {len(df)}  ->  " + ", ".join(f"{k}: {v}" for k, v in df["source"].value_counts().items()))

    client = None

    def fn(batch):
        nonlocal client
        client = client or get_openai_client()
        cols = ["id", "name", "position", "organization", "linkedin_headline", "role_at_event", "sessions",
                "org_sector", "org_relevance", "org_why", "org_is_competitor", "booth", "booth_priority"]
        items = [{c: r.get(c, "") for c in cols} for r in batch]
        return llm_json(client, SYSTEM, items, ITEM_SCHEMA, "contacts")

    res = run_cached(df.to_dict("records"), "id", CACHE, fn, BATCH)
    sc = pd.DataFrame(res.values()).drop_duplicates("id", keep="last")
    df = df.merge(sc, on="id", how="left")

    # nerede bulunur: konusmalar + kurumun standi
    where = []
    for _, r in df.iterrows():
        w = list(dict.fromkeys(by_user.get(r["id"], []) + spk.get(r["id"], {}).get("where", [])))
        if r["booth"]:
            w.append(f"Stand {r['booth']}" + (" (eigener Stand)" if r.get("role_at_event") == "staff" else ""))
        where.append(" | ".join(w))
    df["wo_finden"] = where
    df = df.rename(columns={"category": "keep_for_person", "why": "why_person", "linkedin_headline": "li_headline",
                            "role_at_event": "userType"})
    df = df.sort_values(["priority", "org_relevance"], ascending=False)
    df.to_csv(DATA / "contacts.csv", index=False, encoding="utf-8-sig")

    print("\npriority:", df["priority"].value_counts().sort_index(ascending=False).to_dict())
    print("Prio 3 nach Quelle:", df[df["priority"] == 3]["source"].value_counts().to_dict())
    print("Prio 3 nach Kategorie:", df[df["priority"] == 3]["keep_for_person"].value_counts().to_dict())
    pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 60)
    print(df[df["priority"] == 3].head(20)[["name", "position", "organization", "source"]].to_string(index=False))
    print(f"\n-> {DATA / 'contacts.csv'}")


if __name__ == "__main__":
    main()
