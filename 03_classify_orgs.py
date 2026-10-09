# -*- coding: utf-8 -*-
"""
03_classify_orgs.py  -  Kurumlari OpenAI ile siniflandirir, sonra kisilere on-skor verip shortlist cikarir.

pip install openai pandas openpyxl
API key: bu klasorde openai_key.txt (sadece key) ya da OPENAI_API_KEY ortam degiskeni.

Girdi : data/companies.csv, data/people.csv   (02_normalize.py ciktisi)
Cikti : data/companies_classified.csv
        data/people_prescored.csv
        data/shortlist.csv           (04_profiles.py --ids data/shortlist.csv icin)
Cache : data/llm_cache/orgs.jsonl    (tekrar calistirinca ayni kurumlara para harcamaz)

Once LIMIT = 50 ile dene, sonuclara bak, sonra LIMIT = None yapip hepsini calistir.
"""

import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from openai import OpenAI

from scc_common import DATA, HERE, print

# -------------------- AYARLAR --------------------
MODEL = "gpt-5-mini"   # hesabinda olan ucuz bir model; ornek: "gpt-4.1-mini", "gpt-4o-mini"
LIMIT = None           # test icin ilk N kurum (ornek: 50). Hepsi icin: None
BATCH = 25             # bir API cagrisinda kac kurum
WORKERS = 4            # paralel cagri sayisi
SHORTLIST_MAX = 250    # 04 adiminda profil cekilecek en fazla kisi

PROMPT_VERSION = "v2"  # prompt'u degistirince artir -> eski cache kullanilmaz
CACHE = DATA / "llm_cache" / f"orgs_{PROMPT_VERSION}.jsonl"

# kendi kurumumuz ve etkinlik organizatoru siniflandirilmaz / shortlist'e girmez
EXCLUDE_RE = re.compile(r"univention|smart country convention|messe berlin", re.I)

SECTORS = [
    "Bund", "Land", "Kommune", "Schulträger/Bildungsverwaltung", "Schule/Hochschule/Forschung",
    "Öffentlicher IT-Dienstleister", "Systemhaus/Integrator/Reseller", "Beratung",
    "Software-Hersteller", "Hyperscaler/Big Tech", "Verband/Community/Medien", "Sonstiges",
]
KEEP_FOR = [
    "Education Authority / Schulträger (Operator)",
    "Identity/IAM & Directory Services",
    "Platform/SRE/Kubernetes (Ops)",
    "Vendor/Partner (EdTech/SI)",
    "Public Sector IT (Operator/Dienstleister)",
    "Other (adjacent, DE/DACH)",
    "Not relevant",
]

SYSTEM = f"""Du bist Expert:in für den öffentlichen Sektor in DACH (Bund, Länder, Kommunen, Schulträger),
IAM/Directory-Dienste und Kubernetes-Plattformen. Du bewertest Organisationen, die auf der
Smart Country Convention (Berlin) vertreten sind, aus Sicht von **Univention**:
- **UCS / UCS@school**: Directory/IdM, SSO, Schulserver, App-Ökosystem
- **Nubus**: Kubernetes-basierte IAM-Plattform (Keycloak/OIDC, Multi-Tenant, cloud-native), u.a. IAM in openDesk
Univention steht für Open Source und digitale Souveränität.

Bewerte jede Organisation (nur anhand Name, Beispielpositionen und Kennzahlen; nichts erfinden).
Sei STRENG. Fast alle Aussteller haben irgendeinen Public-Sector-Bezug; das allein reicht nicht für 3.

relevance (0-3):
3 = nur für diese drei Gruppen:
    (a) Betreiber: Kommunen, Landes-/Bundesbehörden mit eigener IT, Schulträger/Bildungsverwaltung/Medienzentren
    (b) öffentliche IT-Dienstleister (kommunale/Landes-Rechenzentren, AöR, eG wie govdigital)
    (c) Partner/SI mit erkennbarem Schwerpunkt Schul-IT, IdM/IAM, Open Source oder souveräne Plattformen
2 = Systemhäuser, Integratoren und Beratungen mit breitem Public-Sector-Geschäft (auch große wie
    Capgemini, Materna, msg), Verbände/Communities/Souveränitäts-Initiativen, Fachpresse,
    Forschung mit GovTech/Bildungsbezug
1 = Big Tech/Hyperscaler/internationale Konzerne ohne spezifischen IAM-/Schul-/Open-Source-Bezug,
    Fachverfahrens-Hersteller ohne IAM-Bezug, sonstiger Randbezug
0 = kein erkennbarer Bezug
Kalibrierung: Erwarte ungefähr 10-15 % der Organisationen mit 3.

is_competitor = true nur, wenn die Organisation selbst IAM/Directory, Schulserver/Schulplattformen
oder Identitäts-/Kollaborationsplattformen als Produkt anbietet, die direkt mit UCS/Nubus konkurrieren.
Ein Integrator, der solche Produkte nur implementiert, ist kein Wettbewerber.

canonical_org: kurzer einheitlicher Name der Mutterorganisation (z.B. "IBM Deutschland GmbH" -> "IBM").
why: EIN knapper Satz (max. 20 Wörter) auf Deutsch. Produkt-Fit ("UCS-Fit: ...", "Nubus-Fit: ...") NUR
nennen, wenn es einen konkreten Hinweis gibt; sonst keinen Fit erwähnen. Keine Floskeln.
Bei unbekannten Namen: confidence "low" und eher niedrig bewerten statt raten."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["results"],
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["org_key", "canonical_org", "sector", "relevance", "keep_for",
                             "is_competitor", "why", "confidence"],
                "properties": {
                    "org_key": {"type": "string"},
                    "canonical_org": {"type": "string"},
                    "sector": {"type": "string", "enum": SECTORS},
                    "relevance": {"type": "integer", "enum": [0, 1, 2, 3]},
                    "keep_for": {"type": "string", "enum": KEEP_FOR},
                    "is_competitor": {"type": "boolean"},
                    "why": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        }
    },
}

# pozisyon metninde bu kelimeler varsa kisi on-skoruna bonus
# \b sinirlari onemli: yoksa "cto" -> "Sector", "Director" ile eslesiyordu
ROLE_RE = re.compile(
    r"\b(?:cio|cdo|cto|ciso|chief\s+\w*\s*officer|it-\w+|leiter\w*\s+(?:der\s+)?it|"
    r"systembetreu\w*|\w*administrat\w*|admin|"
    r"referatsleit\w*|abteilungsleit\w*|amtsleit\w*|dezernent\w*|bürgermeister\w*|staatssekret\w*|"
    r"digitalisierung\w*|\w*architekt\w*|\w*architect|identity|iam|idm|directory|keycloak|kubernetes|k8s|"
    r"\w*plattform\w*|platform\w*|sre|devops|\w*schul\w*|bildung\w*|education|souverän\w*|open\s?source)\b",
    re.I,
)
# profil ziyaretine degmeyecek roller (vendor tarafinda satis/pazarlama/etkinlik/IK vb.)
NEG_RE = re.compile(
    r"\b(?:marketing|event\w*|hr|human resources|personal\w*|recruit\w*|assisten\w*|assistant|"
    r"werkstudent\w*|praktikant\w*|intern|trainee|communication\w*|kommunikation|presse)\b",
    re.I,
)
MAX_PER_ORG = 6   # shortlist'te ayni kurumdan en fazla kac kisi


# -------------------- YARDIMCILAR --------------------
def get_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    kf = HERE / "openai_key.txt"
    if not key and kf.exists():
        key = kf.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit("OpenAI key yok: openai_key.txt olustur ya da OPENAI_API_KEY ver.")
    return OpenAI(api_key=key)


def load_cache() -> dict:
    out = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["org_key"]] = r
    return out


_lock = threading.Lock()


def append_cache(rows: list[dict]):
    with _lock:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with CACHE.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def classify_batch(client: OpenAI, batch: pd.DataFrame) -> list[dict]:
    items = [{
        "org_key": r.org_key,
        "organization": r.organization,
        "people": int(r.n_people),
        "exhibitor": bool(r.is_exhibitor),
        "speakers": int(r.n_speaker),
        "sample_positions": (r.positions or "")[:300],
    } for r in batch.itertuples()]

    kwargs = dict(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
        ],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "orgs", "strict": True, "schema": SCHEMA}},
    )
    if MODEL.startswith("gpt-5"):
        kwargs["reasoning_effort"] = "low"   # minimal fazla yuzeysel kaldi
    else:
        kwargs["temperature"] = 0

    resp = client.chat.completions.create(**kwargs)
    results = json.loads(resp.choices[0].message.content)["results"]
    valid = set(batch["org_key"])
    results = [r for r in results if r["org_key"] in valid]
    u = resp.usage
    print(f"  batch {len(results)}/{len(batch)} ok | tokens in={u.prompt_tokens} out={u.completion_tokens}")
    return results


# -------------------- ANA AKIS --------------------
def main():
    companies = pd.read_csv(DATA / "companies.csv").fillna({"positions": ""})
    people = pd.read_csv(DATA / "people.csv").fillna({"position": "", "organization": "", "org_key": ""})

    excluded = companies["organization"].fillna("").str.contains(EXCLUDE_RE)
    print(f"Haric tutulan kurum: {', '.join(companies.loc[excluded, 'organization'])}")
    companies = companies[~excluded]
    people = people[~people["organization"].str.contains(EXCLUDE_RE)]

    todo_all = companies.sort_values("n_people", ascending=False)
    if LIMIT:
        todo_all = todo_all.head(LIMIT)
    cache = load_cache()
    todo = todo_all[~todo_all["org_key"].isin(cache)]
    print(f"Kurum: {len(todo_all)} secili, {len(todo_all) - len(todo)} cache'te, {len(todo)} API'ye gidecek. Model: {MODEL}")

    if len(todo):
        client = get_client()
        batches = [todo.iloc[i:i + BATCH] for i in range(0, len(todo), BATCH)]
        with ThreadPoolExecutor(WORKERS) as ex:
            futs = {ex.submit(classify_batch, client, b): i for i, b in enumerate(batches)}
            for fut in as_completed(futs):
                try:
                    rows = fut.result()
                    append_cache(rows)
                    for r in rows:
                        cache[r["org_key"]] = r
                except Exception as e:
                    print(f"  !! batch {futs[fut]} hata: {e} (tekrar calistirinca yeniden denenir)")

    # ---- kurum tablosu ----
    cls = pd.DataFrame(cache.values())
    comp = companies.merge(cls, on="org_key", how="left")
    comp = comp.sort_values(["relevance", "n_people"], ascending=[False, False])
    comp.to_csv(DATA / "companies_classified.csv", index=False, encoding="utf-8-sig")

    # ---- kisi on-skoru ----
    p = people.merge(cls[["org_key", "canonical_org", "sector", "relevance", "keep_for", "is_competitor"]],
                     on="org_key", how="left")
    p["role_hit"] = p["position"].str.contains(ROLE_RE)
    p["role_neg"] = p["position"].str.contains(NEG_RE)
    p["has_position"] = p["position"].str.strip() != ""
    p["pre_score"] = (p["relevance"].fillna(0)
                      + p["role_hit"].astype(int)
                      - p["role_neg"].astype(int)
                      + (p["userType"] == "speaker").astype(int))
    # esitlikte: rol eslesmesi > pozisyonu dolu > digerleri
    p = p.sort_values(["pre_score", "role_hit", "has_position"], ascending=False)
    p.to_csv(DATA / "people_prescored.csv", index=False, encoding="utf-8-sig")

    # rakipleri de dahil ediyoruz (is_competitor raporda ayrica gorunecek);
    # ayni kurum listeyi doldurmasin diye kurum basina MAX_PER_ORG
    cand = p[(p["relevance"] >= 2) & ~p["role_neg"]].copy()
    cand["org_group"] = cand["canonical_org"].fillna(cand["org_key"])
    cand = cand.groupby("org_group", sort=False).head(MAX_PER_ORG)
    short = cand.head(SHORTLIST_MAX)
    print(f"\nShortlist: {short['org_group'].nunique()} kurumdan {len(short)} kisi | "
          f"rol eslesmesi: {int(short['role_hit'].sum())} | pozisyonsuz: {int((~short['has_position']).sum())}")
    short.to_csv(DATA / "shortlist.csv", index=False, encoding="utf-8-sig")

    done = comp["relevance"].notna()
    print(f"\nSiniflandirilan kurum: {done.sum()}/{len(comp)}")
    print(comp.loc[done, "relevance"].value_counts().sort_index(ascending=False).to_string())
    pd.set_option("display.max_colwidth", 110)
    pd.set_option("display.width", 250)
    comp_rows = comp[comp["is_competitor"] == True]
    print(f"\nRakip olarak isaretlenen ({len(comp_rows)}): {', '.join(comp_rows['organization'])}")
    print("\nSektor dagilimi:")
    print(comp.loc[done, "sector"].value_counts().to_string())
    for rel in (3, 2):
        sub = comp[comp["relevance"] == rel]
        print(f"\n--- relevance {rel} ({len(sub)}) ---")
        print(sub.head(20)[["organization", "n_people", "sector", "why"]].to_string(index=False))
    print(f"\nShortlist: {len(short)} kisi -> {DATA / 'shortlist.csv'}")


if __name__ == "__main__":
    main()
