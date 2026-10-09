# -*- coding: utf-8 -*-
"""Ortak ayarlar: token, HTTP session, istek yardimcilari."""

import base64
import functools
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

print = functools.partial(print, flush=True)

HERE = Path(__file__).parent
DATA = HERE / "data"
RAW = DATA / "raw"

TOPIC = "2022_SCC"
BACKEND = "https://live.messebackend.aws.corussoft.de"
COMMON_PARAMS = {
    "topic": TOPIC,
    "os": "web",
    "appUrl": "https://online.smartcountry.berlin",
    "lang": "en",
    "apiVersion": "52",
    "timezoneOffset": "0",
}


def get_token() -> str:
    tok = os.environ.get("SCC_TOKEN", "").strip()
    token_file = HERE / "scc_token.txt"
    if tok:
        print("Token SCC_TOKEN ortam degiskeninden alindi.")
    elif token_file.exists():
        tok = token_file.read_text(encoding="utf-8").strip()
        print(f"Token {token_file.name} dosyasindan alindi.")
    else:
        print(f"Token bulunamadi. {token_file.name} olustur ya da buraya yapistir.")
        tok = input("beconnectiontoken: ").strip()
    if not tok:
        sys.exit("Token yok.")
    return tok


def my_user_id(token: str) -> str:
    """Token'in icindeki kendi kullanici ID'n (profil URL'sinde lazim)."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sotUserId"]


def make_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "accept": "application/json",
        "beconnectiontoken": token,
        "ec-client": "EventGuide/2.26.2-11515[52]",
        "ec-client-branding": TOPIC,
        "origin": "https://online.smartcountry.berlin",
        "referer": "https://online.smartcountry.berlin/",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"),
    })
    return s


def request_json(s: requests.Session, method: str, url: str, **kw):
    for attempt in range(4):
        try:
            r = s.request(method, url, timeout=30, **kw)
        except requests.exceptions.RequestException as e:
            print(f"  !! baglanti hatasi: {e}")
            time.sleep(5)
            continue
        if r.status_code in (401, 403):
            sys.exit(f"HTTP {r.status_code}: token gecersiz/suresi dolmus. Yeniden login olup yeni token al.")
        if r.status_code == 429 or r.status_code >= 500:
            wait = 5 * (attempt + 1)
            print(f"  HTTP {r.status_code}, {wait}s bekleyip tekrar deniyorum...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Tekrar denemeler basarisiz: {url}")


# -------------------- OpenAI yardimcilari (07, 08 icin) --------------------
MODEL = "gpt-5-mini"   # hesabinda olan ucuz bir model; ornek: "gpt-4.1-mini", "gpt-4o-mini"

UNIVENTION_CONTEXT = """Univention (Bremen) ist ein Open-Source-Softwarehersteller für digitale Souveränität:
- **UCS / UCS@school**: Directory/IdM, SSO, Schulserver, App-Ökosystem (v.a. Schulträger, Kommunen)
- **Nubus**: Kubernetes-basierte IAM-Plattform (Keycloak/OIDC, Multi-Tenant, cloud-native), IAM-Komponente in openDesk
Zielgruppen: öffentliche IT-Dienstleister, Kommunen, Länder/Bund, Schulträger sowie Partner/Integratoren.

Wer die Ergebnisse liest: das Univention-Team auf der Messe (Produktmanagement, Technik, Vertrieb,
Partnermanagement). Diese Leute kennen den IAM-Markt sehr gut. Die Geschäftsführung pflegt die Kontakte
zur obersten Leitungsebene (CEO, Vorstand, Präsident:in, Staatssekretär:in) ohnehin selbst."""

# Gemeinsame Qualitaetsregeln fuer alle Fragen / Gespraechseinstiege (07, 08b). Hintergrund: Feedback aus dem
# Team ("ich muss nicht zu einem anderen IAM-Hersteller gehen und fragen, ob er OIDC unterstuetzt").
QUESTION_RULES = """Regeln für Fragen und Gesprächseinstiege:
- KEINE Grundlagenfragen, deren Antwort trivial, Branchenstandard oder auf der Website zu finden ist. Insbesondere
  NIEMALS fragen, ob jemand OIDC, SAML, LDAP, SCIM, Keycloak, SSO oder "Schnittstellen" unterstützt –
  das kann heute jedes IAM-/SaaS-Produkt, und Univention selbst bietet das alles an.
- Bei Wettbewerbern (eigenes IAM-/Directory-/Schulplattform-Produkt) NICHT nach Funktionen fragen. Stattdessen
  Marktbeobachtung: Welche Kunden/Projekte im öffentlichen Sektor, Ausschreibungen, Betriebsmodell
  (SaaS/On-Prem/Partner), Preis-/Lizenzmodell, Roadmap, Positionierung gegenüber Open Source.
- Bei Open-Source-/openDesk-Partnern: konkrete gemeinsame Kunden, Projekte oder Integrationsschritte, nicht
  ob eine Integration "möglich" ist.
- Bei Betreibern/Behörden/IT-Dienstleistern: nach ihren aktuellen Vorhaben, Problemen, Zeitplänen und
  Entscheidungen fragen (z.B. Konsolidierung von Verzeichnisdiensten, Schul-IdM, openDesk-Rollout,
  Ablösung proprietärer Lösungen), nicht Univention-Produkte anpreisen.
- Kein Verkaufsgespräch im ersten Satz ("Interesse an UCS/Nubus?" ist schlecht).
- Ist eine bestehende Beziehung angegeben (relationship), daran anknüpfen statt sich vorzustellen.
- openDesk-Partner (relationship enthält "openDesk"): Die Integration mit Univention besteht bereits – Nubus ist
  das IAM in openDesk. NIEMALS fragen, ob es Integrationen mit openDesk, IdM/SSO oder Identity-Plattformen gibt
  oder geplant sind. Stattdessen: gemeinsame Kunden und Rollouts, Erfahrungen/Feedback aus Projekten, Roadmap,
  gemeinsame Auftritte oder Ausschreibungen.
- Gibt es keine sinnvolle, konkrete Frage: leeren String zurückgeben statt einer generischen Frage.
Schlechte Beispiele: "Welche Authentifizierungsstandards (OIDC, SAML) unterstützen Sie?",
"Bieten Sie Integrationen zu Keycloak/LDAP an?", "Interesse an Austausch zu IdM-/SSO-Integrationen?"
Gute Beispiele: "Welche Bundesländer setzen Ihre Lösung bereits für Schulen ein, und läuft das als SaaS?",
"Wie weit ist Ihr openDesk-Rollout, und wer betreibt bei Ihnen das Identity-Management?"
"""

# Univention-Mitarbeitende werden nicht bewertet, aber angezeigt (Blatt "Univention-Team").
# Veranstalter (Messe Berlin / SCC) bleiben ganz draussen.
UNIVENTION_RE = re.compile(r"univention", re.I)
ORGANIZER_RE = re.compile(r"smart country convention|messe berlin", re.I)
TEAM_SECTOR = "Univention (eigenes Team)"


def load_known_orgs() -> dict:
    """Optional: data/known_orgs.csv  (Spalten: organisation,status,notiz)
    Bestehende Kunden/Partner/Kontakte. Wird an das Modell gegeben (relationship) und in den Listen angezeigt,
    damit keine Grundlagenfragen an Organisationen gestellt werden, mit denen wir laengst arbeiten.
    Rueckgabe: {org_key: "Kunde – Notiz"}"""
    import pandas as pd
    f = DATA / "known_orgs.csv"
    if not f.exists():
        return {}
    df = pd.read_csv(f, sep=None, engine="python").fillna("")
    df.columns = [c.strip().lower() for c in df.columns]
    out = {}
    for _, r in df.iterrows():
        k = org_key(str(r.get("organisation", "")))
        if k:
            out[k] = " – ".join(x for x in (str(r.get("status", "")).strip(), str(r.get("notiz", "")).strip()) if x)
    print(f"known_orgs.csv: {len(out)} bekannte Organisationen")
    return out


def cache_key(item_id, rel: str) -> str:
    """Cache-Schluessel: ohne bekannte Beziehung = id (alte Cache-Eintraege bleiben gueltig);
    mit Beziehung = id + Hash, damit diese Eintraege nach Aenderung von known_orgs.csv neu bewertet werden."""
    import hashlib
    return str(item_id) if not rel else f"{item_id}|rel:{hashlib.md5(rel.encode('utf-8')).hexdigest()[:8]}"


def relationship(known: dict, org: str) -> str:
    """Bekannte Beziehung zu einer Organisation (exakter org_key oder bekannter Name als Wortfolge darin)."""
    k = org_key(org)
    if not k or not known:
        return ""
    if k in known:
        return known[k]
    for kk, v in known.items():
        if re.search(r"(?:^|\s)" + re.escape(kk) + r"(?:\s|$)", k):
            return v
    return ""


# -------------------- Prio-Anzeige --------------------
# Intern rechnen alle Schritte mit 0-3 (3 = am wichtigsten). Angezeigt wird wie gewohnt "Prio 1" = hoechste.
def prio_label(v):
    """intern 3/2/1/0 -> Anzeige 1/2/3/"–" """
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return "–"
    return {3: 1, 2: 2, 1: 3}.get(v, "–")


def prio_internal(v) -> int:
    """Anzeige 1/2/3/"–" (aus dem Excel) -> intern 3/2/1/0"""
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return {1: 3, 2: 2, 3: 1}.get(v, 0)


def get_openai_client():
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    kf = HERE / "openai_key.txt"
    if not key and kf.exists():
        key = kf.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit("OpenAI key yok: openai_key.txt olustur ya da OPENAI_API_KEY ver.")
    return OpenAI(api_key=key)


def llm_json(client, system: str, items: list, item_schema: dict, name: str) -> list[dict]:
    """items listesini gonderir, {"results": [item_schema...]} seklinde strict JSON doner."""
    schema = {"type": "object", "additionalProperties": False, "required": ["results"],
              "properties": {"results": {"type": "array", "items": item_schema}}}
    kwargs = dict(
        model=MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": json.dumps(items, ensure_ascii=False, default=str)}],
        response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
    )
    if MODEL.startswith("gpt-5"):
        kwargs["reasoning_effort"] = "low"
    else:
        kwargs["temperature"] = 0
    resp = client.chat.completions.create(**kwargs)
    print(f"  batch ok | tokens in={resp.usage.prompt_tokens} out={resp.usage.completion_tokens}")
    return json.loads(resp.choices[0].message.content)["results"]


def run_cached(items: list[dict], key: str, cache_file: Path, fn, batch: int, workers: int = 4) -> dict:
    """items'i batch'ler halinde fn(batch_items) ile isler; sonuclari cache_file'a (jsonl) yazar.
    Cache'te olan kayitlar tekrar gonderilmez. Donus: {key_degeri: sonuc}"""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    cache = {}
    if cache_file.exists():
        for line in cache_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                k = r.get(key) or r.get("id")   # eski cache satirlarinda "ck" yok -> id
                if k:
                    cache[k] = r
    todo = [it for it in items if it[key] not in cache]
    print(f"{cache_file.name}: {len(items)} kayit, {len(items) - len(todo)} cache'te, {len(todo)} API'ye gidecek")
    if not todo:
        return cache
    lock = threading.Lock()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    batches = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fn, b): b for b in batches}
        for fut in as_completed(futs):
            try:
                valid = {it[key] for it in futs[fut]}
                rows = [r for r in fut.result() if r.get(key) in valid]
                with lock, cache_file.open("a", encoding="utf-8") as f:
                    for r in rows:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                        cache[r[key]] = r
            except Exception as e:
                print(f"  !! batch hata: {e} (tekrar calistirinca yeniden denenir)")
    return cache


def load_pages(name: str) -> list[dict]:
    """01_collect.py'nin kaydettigi sayfalardaki tum entity'leri dondurur."""
    out = []
    for f in sorted((RAW / name).glob("page_*.json")):
        out.extend(json.loads(f.read_text(encoding="utf-8")).get("entities", []))
    return out


def org_key(org) -> str:
    """02_normalize.py ile ayni kurum anahtari (eslestirme icin)."""
    import re
    if not isinstance(org, str) or not org.strip():
        return ""
    forms = [r"gmbh\s*&\s*co\.?\s*kg", r"ag\s*&\s*co\.?\s*ohg", r"ag\s*&\s*co\.?\s*kg", r"ggmbh", r"gmbh",
             r"mbh", r"ag", r"kg", r"ohg", r"se", r"ug", r"e\.?\s*v\.?", r"a\.?ö\.?r\.?", r"aör", r"kdör",
             r"ltd\.?", r"inc\.?", r"llc", r"b\.?v\.?", r"s\.?a\.?"]
    s = re.compile(r"\b(" + "|".join(forms) + r")(?=\W|$)", re.I).sub(" ", org.casefold())
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_people_scored():
    """people_prescored.csv + 05'in puanlari (llm_cache/people_v1.jsonl). Puani olmayanlar priority=0."""
    import pandas as pd
    p = pd.read_csv(DATA / "people_prescored.csv").fillna({"position": "", "organization": "", "org_key": ""})
    sc = {}
    f = DATA / "llm_cache" / "people_v1.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                sc[r["id"]] = r   # son satir kazanir (LinkedIn ile yeniden puanlananlar)
    p["priority"] = p["id"].map(lambda i: sc.get(i, {}).get("priority", 0))
    p["talking_point"] = p["id"].map(lambda i: sc.get(i, {}).get("talking_point", ""))
    return p


# -------------------- Excel: sekme ve kolon adlari (09 yazar, 10 okur) --------------------
# Excel: her konu tek sekmede, Prio-1-satirlari sari. (all_* ayni sekmeyi gosterir, 10 icin)
SHEETS = {
    "overview": "Übersicht", "booths": "Stände", "agenda": "Vorträge", "meetings": "Kontakte",
    "people": "Alle Personen", "speakers": "Alle Speaker", "all_booths": "Stände", "all_talks": "Vorträge",
    "team": "Univention-Team",
}
LABELS = {
    "id": "ID", "visit_priority": "Prio", "relevance": "Prio", "priority": "Prio",
    "hall": "Halle", "stand": "Stand", "exhibitor": "Aussteller", "visit_goal": "Ziel", "why": "Warum",
    "booth_question": "Frage am Stand", "contacts_to_meet": "Kontakte", "same_stand_with": "Am selben Stand",
    "is_competitor": "Wettbewerber", "partner_level": "Partnerstatus", "categories": "Kategorien",
    "date": "Datum", "start": "Von", "end": "Bis", "location": "Ort", "title": "Titel", "topics": "Themen",
    "goal": "Was wir mitnehmen wollen", "speakers": "Speaker", "overlaps_with": "Parallel dazu",
    "also_at": "Auch am", "check": "Prüfen", "Wer geht?": "Wer geht?", "format": "Format",
    "host_org": "Veranstalter", "teaser": "Beschreibung", "tracks": "Tracks",
    "name": "Name", "position": "Position", "organization": "Organisation", "wo_finden": "Wo zu finden",
    "talking_point": "Gesprächseinstieg", "why_person": "Warum", "keep_for_person": "Kategorie",
    "product_fit": "Produkt", "LinkedIn": "LinkedIn", "li_headline": "LinkedIn-Headline",
    "li_followers": "Follower", "userType": "Rolle", "sector": "Sektor", "City": "Stadt", "Country": "Land",
    "ProfileURL": "SCC-Profil", "person_priority": "Kontakt-Prio", "max_talk_relevance": "Vortrags-Prio",
    "sessions": "Sessions", "n_sessions": "Anzahl Sessions", "tier": "Stufe",
    "level": "Ebene", "relationship": "Bestehende Beziehung", "is_new": "Neu",
}
PRIO_COLS = ("priority", "visit_priority", "relevance", "person_priority", "max_talk_relevance")


def unlabel(df, keys):
    """Excel'den okunan Almanca kolonlari ic isimlere geri cevirir (sadece verilen anahtarlar icin)."""
    back = {LABELS.get(k, k): k for k in keys}
    return df.rename(columns={c: back[c] for c in df.columns if c in back})
