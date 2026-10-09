# -*- coding: utf-8 -*-
"""
08_talks.py  -  Hangi konusmalari dinleyelim?

Girdi : data/raw/sessions/*.json (01_collect.py sessions), data/people_prescored.csv + people_v1 cache (05)
Cikti : data/talks.csv  (09_plan.py bunu gun gun ajandaya cevirir)
Cache : data/llm_cache/talks_v1.jsonl

Her session icin: Univention icin relevance (0-3), konular, gerekce, ne ogrenmek/kimle tanismak istedigimiz,
speaker'lar (bizim kisi skorlariyla) ve ayni saatteki diger onemli session'lar (cakisma).
"""

import pandas as pd

from scc_common import (DATA, UNIVENTION_CONTEXT, UNIVENTION_RE, get_openai_client, llm_json, load_pages,
                        load_people_scored, print, prio_label, run_cached)

BATCH = 15
CACHE = DATA / "llm_cache" / "talks_v2.jsonl"   # v2: daha siki kalibrasyon
FORMAT_CATS = {"Stage Program", "Booth Program", "Workshop", "Presentation", "Deep Dive", "Live Demonstration",
               "Networking", "Meet the expert", "Career Day", "Panel", "Keynote"}
SKIP_CATS = {"Format", "Tracks"}

TOPICS = ["IAM/IdM/SSO", "Digitale Souveränität/Open Source", "openDesk/Kollaboration",
          "Deutschland-Stack/Plattformen", "Cloud/Kubernetes", "Schul-IT/Bildung",
          "Kommunale IT/Verwaltungsdigitalisierung", "Beschaffung/Vergabe", "KI", "Cybersecurity",
          "Politik/Strategie", "Sonstiges"]

SYSTEM = UNIVENTION_CONTEXT + """

Du planst für das Univention-Team (Produktmanagement, Vertrieb, Partnermanagement), welche Vorträge
auf der Smart Country Convention besucht werden. Bewerte jede Session (nur anhand der Daten):

Das Team kann pro Tag nur ca. 10-15 Sessions besuchen. Sei STRENG; das Wort "Souveränität" im Titel
allein reicht nicht.
relevance (0-3):
3 = Pflicht (nur ca. 8-10 % aller Sessions):
    - Identität/IAM: digitale Identitäten, EUDI-Wallet, BundID/Nutzerkonten, SSO, Zugangsmanagement
    - openDesk, ZenDiS, souveräne Arbeitsplatz-/Kollaborationslösungen
    - Deutschland-Stack, Plattform- und Cloud-Architektur der Verwaltung, Strategie öffentlicher IT-Dienstleister
    - Schul-IT / digitale Bildungsinfrastruktur (Schulträger, DigitalPakt, Bildungs-IdM)
    - Keynotes/Panels von Schlüsselakteuren (BMDS, IT-Planungsrat, Dataport, große Landes-IT, ZenDiS, OSBA)
    - Beiträge von direkten Wettbewerbern zu IAM/Schulplattformen
2 = nützliches Marktwissen: allgemeine Souveränitäts-/Open-Source-Politik, Beschaffung/EVB-IT,
    Verwaltungsdigitalisierung mit IT-Infrastrukturbezug, kommunale IT-Kooperation
1 = Randthema: KI-Anwendungsfälle, Smart City/Daten ohne Identitäts- oder Plattformbezug,
    Cybersecurity allgemein, Startup-Pitches ohne IAM-Bezug, Firmen-Keynotes ohne Bezug
0 = nicht relevant: Karriere-/Recruiting-Events, Awards, reine Fachthemen (Bau, Umwelt, Mobilität usw.)
Speaker mit hoher speaker_priority (0-3, unsere Kontaktbewertung) können eine 2 zu einer 3 machen.
(Im Feld speakers steht die Kontaktbewertung als "[Prio 1]" = wichtigster Kontakt, "[Prio 2]", "[Prio 3]".)

topics: 1-3 passende Themen.
why: EIN knapper Satz (max. 20 Wörter) auf Deutsch.
goal: was wir dort lernen oder mit wem wir danach sprechen wollen (max. 20 Wörter, Deutsch)."""

ITEM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "relevance", "topics", "why", "goal"],
    "properties": {
        "id": {"type": "string"},
        "relevance": {"type": "integer", "enum": [0, 1, 2, 3]},
        "topics": {"type": "array", "items": {"type": "string", "enum": TOPICS}},
        "why": {"type": "string"},
        "goal": {"type": "string"},
    },
}


def main():
    ss = load_pages("sessions")
    print(f"Session: {len(ss)}")
    people = load_people_scored().set_index("id")

    rows = []
    for s in ss:
        cats = [c.get("name", "") for c in s.get("categories") or []]
        spk, best = [], 0
        for p in s.get("persons") or []:
            pr = 0
            uid = p.get("userId")
            if uid and uid in people.index:
                pr = int(people.at[uid, "priority"])
            best = max(best, pr)
            spk.append(f"{p.get('firstName', '')} {p.get('lastName', '')} ({p.get('position', '')}, "
                       f"{p.get('organization', '')})" + (f" [Prio {prio_label(pr)}]" if pr else ""))
        orgs = [s.get("organizationName") or ""] + [o.get("name", "") for o in s.get("organizations") or []]
        rows.append({
            "id": s["id"],
            "title": s.get("name", ""),
            "date": s.get("date", ""), "start": s.get("start", ""), "end": s.get("end", ""),
            "location": s.get("location", ""),
            "format": ", ".join(c for c in cats if c in FORMAT_CATS),
            "tracks": ", ".join(c for c in cats if c not in FORMAT_CATS and c not in SKIP_CATS),
            "host_org": ", ".join(o for o in orgs if o),
            "teaser": (s.get("teaser") or "").strip(),
            "speakers": " | ".join(spk),
            "speaker_priority": best,
        })
    df = pd.DataFrame(rows)

    client = None

    def fn(batch):
        nonlocal client
        client = client or get_openai_client()
        items = [{k: r[k] for k in ("id", "title", "format", "tracks", "host_org", "teaser",
                                    "speakers", "speaker_priority")} for r in batch]
        return llm_json(client, SYSTEM, items, ITEM_SCHEMA, "talks")

    res = run_cached(df.to_dict("records"), "id", CACHE, fn, BATCH)
    sc = pd.DataFrame(res.values()).drop_duplicates("id", keep="last")
    sc["topics"] = sc["topics"].map(", ".join)
    df = df.merge(sc, on="id", how="left")
    # kural: Startup-Pitch'ler (10 dk) IAM/Kimlik konusu degilse en fazla 2
    pitch = df["title"].str.match(r"(?i)^pitch\b") & ~df["topics"].fillna("").str.contains("IAM")
    df.loc[pitch & (df["relevance"] == 3), "relevance"] = 2
    # Prio 1 (intern 3) nur fuer Kernthemen: Modell vergibt sonst ~25 % Prio 1 (zu viele zum Besuchen).
    # Uebrige Prio-1-Sessions -> Prio 2; Buehnenprogramm zu Souveraenitaet/Open Source bleibt Prio 1.
    core = df["topics"].fillna("").str.contains(r"IAM/IdM/SSO|openDesk/Kollaboration|Schul-IT/Bildung")
    stage_sov = (df["format"].str.contains("Stage") & ~df["format"].str.contains("Booth")
                 & df["topics"].fillna("").str.contains("Digitale Souveränität/Open Source") & ~pitch)
    down = (df["relevance"] == 3) & ~core & ~stage_sov
    print(f"Prio 1 -> Prio 2 (kein Kernthema): {int(down.sum())}")
    df.loc[down, "relevance"] = 2
    # Univention-eigene Beitraege (Veranstalter oder Speaker von Univention): immer Prio 1, Team-Praesenz
    own = (df["host_org"] + " " + df["speakers"]).str.contains(UNIVENTION_RE)
    df.loc[own, ["relevance", "why", "goal"]] = [3, "Eigener Beitrag von Univention",
                                                 "Team-Präsenz zeigen, danach mit Zuhörenden ins Gespräch kommen"]
    print(f"Univention-Beitraege: {int(own.sum())}")

    # cakisma: ayni gun, zaman araligi kesisen ve relevance>=2 olan diger session'lar
    df["_s"] = pd.to_datetime(df["date"] + " " + df["start"], errors="coerce")
    df["_e"] = pd.to_datetime(df["date"] + " " + df["end"], errors="coerce")
    hot = df[df["relevance"] >= 2]
    overlaps = []
    for _, r in df.iterrows():
        o = hot[(hot["id"] != r["id"]) & (hot["_s"] < r["_e"]) & (hot["_e"] > r["_s"])]
        overlaps.append(" | ".join(f"Prio {prio_label(x.relevance)} {x.start} {x.title[:50]}" for x in o.itertuples()))
    df["overlaps_with"] = overlaps
    # ayni baslik birden fazla slotta varsa (tekrarlanan booth programlari) diger slotlari goster
    slots = df.groupby("title").apply(lambda g: list(zip(g["id"], g["date"].str[5:] + " " + g["start"])))
    df["also_at"] = [" | ".join(t for i, t in slots[r.title] if i != r.id) for r in df.itertuples()]
    df = df.sort_values(["_s", "relevance"], ascending=[True, False]).drop(columns=["_s", "_e"])
    df.to_csv(DATA / "talks.csv", index=False, encoding="utf-8-sig")

    print("\nrelevance dagilimi:")
    print(df["relevance"].value_counts().sort_index(ascending=False).to_string())
    pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 70)
    for d, g in df[df["relevance"] == 3].groupby("date"):
        print(f"\n--- {d}: {len(g)} session (relevance 3) ---")
        print(g[["start", "end", "location", "title"]].head(12).to_string(index=False))
    print(f"\n-> {DATA / 'talks.csv'}")


if __name__ == "__main__":
    main()
