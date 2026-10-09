# -*- coding: utf-8 -*-
"""
07_booths.py  -  Hangi standlara gidelim?

Girdi : data/raw/exhibitors/*.json (01_collect.py exhibitors), data/companies_classified.csv (03),
        data/people_prescored.csv + llm_cache/people_v1.jsonl (05)
Cikti : data/booths.csv  (09_plan.py bunu Excel'e koyar)
Cache : data/llm_cache/booths_v1.jsonl

Her stand icin: ziyaret onceligi (0-3), ziyaret amaci, rakip mi, gerekce, standda sorulacak soru,
ve o firmadan fuarda olan oncelikli kisilerimiz.
"""

import re

import pandas as pd

from scc_common import (DATA, UNIVENTION_CONTEXT, get_openai_client, llm_json, load_pages,
                        load_people_scored, org_key, print, run_cached)

BATCH = 20
CACHE = DATA / "llm_cache" / "booths_v2.jsonl"   # v2: daha siki kalibrasyon
SKIP_CATS = {"SCC 26", "Segments", "Routes", "Miscellaneous"}

GOALS = ["Partner-Potenzial", "Kunde/Betreiber", "Wettbewerber beobachten",
         "Souveränität/Ökosystem", "Trend/Inspiration", "Nicht besuchen"]

SYSTEM = UNIVENTION_CONTEXT + """

Du planst für das Univention-Team den Besuch von Ausstellerständen auf der Smart Country Convention.
Bewerte jeden Aussteller (nur anhand der Daten, nichts erfinden):

Das Team kann nur ca. 40 Stände wirklich besuchen. Sei STRENG:
visit_priority (0-3):
3 = Pflichtbesuch (nur ca. 5-8 % der Aussteller):
    - öffentliche IT-Dienstleister / Landes- und kommunale Rechenzentren (z.B. Dataport, AKDB, Komm.ONE, ITDZ)
    - Organisationen der Souveränitäts-/Open-Source-Community und des openDesk-Ökosystems
      (ZenDiS, OSBA, Sovereign Cloud Stack, Open-Source-Hersteller wie Nextcloud, Open-Xchange, OpenProject,
      Collabora, Element, XWiki, Heinlein)
    - Integratoren/SI mit erkennbarem Fokus auf IAM, Schul-IT, Open Source oder souveräne Plattformen
    - direkte Wettbewerber mit eigenem IAM-/Directory-/Schulplattform-Produkt
    - Gremien mit Steuerungswirkung (IT-Planungsrat, FITKO, Vitako, KDN, Digitalministerien der Länder)
2 = lohnt sich: große Systemhäuser/Beratungen mit Public-Sector-Geschäft, Cloud-/Plattformanbieter,
    Behörden/Länder mit eigenem Stand ohne klaren IT-Betriebsbezug
1 = nur wenn Zeit: Hyperscaler/Konzerne ohne IAM-/Open-Source-Bezug, einzelne kleine Kommunen,
    Fachverfahren ohne Identitätsbezug
0 = nicht relevant
our_priority_contacts ist nur ein Tie-Breaker: viele Kontakte machen einen Stand NICHT zur Pflicht.

is_competitor: nur wenn die Organisation SELBST ein IAM-/Directory-/SSO- oder Schulplattform-Produkt
anbietet, das mit UCS/Nubus konkurriert. Open-Source-Partner aus dem openDesk-Ökosystem sind KEINE
Wettbewerber (visit_goal "Souveränität/Ökosystem").

visit_goal: der Hauptgrund für den Besuch.
why: EIN knapper Satz (max. 20 Wörter) auf Deutsch, nur belegbar.
booth_question: EINE konkrete Frage (max. 25 Wörter, Deutsch), die wir am Stand stellen, um
Partnerschaft, Bedarf oder Wettbewerbsposition herauszufinden."""

ITEM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "visit_priority", "visit_goal", "is_competitor", "why", "booth_question"],
    "properties": {
        "id": {"type": "string"},
        "visit_priority": {"type": "integer", "enum": [0, 1, 2, 3]},
        "visit_goal": {"type": "string", "enum": GOALS},
        "is_competitor": {"type": "boolean"},
        "why": {"type": "string"},
        "booth_question": {"type": "string"},
    },
}


def stand_sort_key(stand: str):
    nums = re.findall(r"\d+", stand or "")
    return tuple(int(n) for n in nums) if nums else (999,)


def main():
    ex = load_pages("exhibitors")
    print(f"Exhibitor: {len(ex)}")
    comp = pd.read_csv(DATA / "companies_classified.csv")
    comp_by_key = comp.drop_duplicates("org_key").set_index("org_key")
    people = load_people_scored()

    ex = [e for e in ex if not re.search(r"univention|smart country convention|messe berlin", e.get("name", ""), re.I)]
    rows = []
    for e in ex:
        cats = [c.get("name", "") for c in e.get("categories") or []]
        stands = e.get("stands") or []
        k = org_key(e.get("name", ""))
        c = comp_by_key.loc[k] if k in comp_by_key.index else None
        ppl = people[people["org_key"] == k].sort_values("priority", ascending=False)
        top = ppl[ppl["priority"] >= 2]
        rows.append({
            "id": str(e["id"]),
            "exhibitor": e.get("name", ""),
            "hall": stands[0].get("hallName", "") if stands else "",
            "stand": " / ".join(s.get("displayName", "") for s in stands),
            "city": e.get("city", ""), "country": e.get("country", ""),
            "partner_level": ", ".join(x for x in cats if "Partner" in x or x == "Patronage"),
            "categories": ", ".join(x for x in cats if x not in SKIP_CATS and "Partner" not in x),
            "teaser": (e.get("teaser") or "").strip(),
            "n_booth_sessions": len(e.get("eventdates") or []),
            "org_key": k,
            "org_relevance": None if c is None else c.get("relevance"),
            "org_sector": "" if c is None else c.get("sector", ""),
            "org_why": "" if c is None else c.get("why", ""),
            "n_registered": len(ppl),
            "our_priority_contacts": len(top),
            "contacts_to_meet": " | ".join(
                f"{r['name']} ({r['position'] or r['userType']}) [P{int(r['priority'])}]" for _, r in top.head(6).iterrows()),
        })
    df = pd.DataFrame(rows)

    client = None

    def fn(batch):
        nonlocal client
        client = client or get_openai_client()
        items = [{k: r[k] for k in ("id", "exhibitor", "teaser", "categories", "partner_level", "city",
                                    "org_relevance", "org_sector", "org_why", "our_priority_contacts",
                                    "n_booth_sessions")} for r in batch]
        return llm_json(client, SYSTEM, items, ITEM_SCHEMA, "booths")

    res = run_cached(df.to_dict("records"), "id", CACHE, fn, BATCH)
    sc = pd.DataFrame(res.values()).drop_duplicates("id", keep="last")
    df = df.merge(sc, on="id", how="left")

    df["_stand"] = df["stand"].map(stand_sort_key)
    df = df.sort_values(["visit_priority", "our_priority_contacts"], ascending=False).drop(columns="_stand")
    df.to_csv(DATA / "booths.csv", index=False, encoding="utf-8-sig")

    print("\nvisit_priority dagilimi:")
    print(df["visit_priority"].value_counts().sort_index(ascending=False).to_string())
    print("\nrakip:", ", ".join(df.loc[df["is_competitor"] == True, "exhibitor"]))
    print("\nziyaret amaci (priority>=2):")
    print(df[df["visit_priority"] >= 2]["visit_goal"].value_counts().to_string())
    pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 70)
    print("\nIlk 15 stand:")
    print(df.head(15)[["exhibitor", "stand", "visit_goal", "our_priority_contacts", "why"]].to_string(index=False))
    print(f"\n-> {DATA / 'booths.csv'}")


if __name__ == "__main__":
    main()
