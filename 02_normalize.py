# -*- coding: utf-8 -*-
"""
02_normalize.py  -  data/raw/attendees/*.json -> tek kisi tablosu + kurum tablosu

pip install pandas openpyxl

Cikti:
  data/people.csv      (kisi basina 1 satir)
  data/companies.csv   (kurum basina 1 satir, userType dagilimi ile)
  data/scc_overview.xlsx  (ikisi ayri sekmede, hizli bakis icin)
"""

import json
import re
from datetime import date, datetime

import pandas as pd

from scc_common import DATA, RAW, print

RAW_DIR = RAW / "attendees"
OUT_DIR = DATA

# kurum adindan atilacak hukuki ekler (sadece gruplama anahtari icin, orijinal ad korunur)
LEGAL_FORMS = [
    r"gmbh\s*&\s*co\.?\s*kg", r"ag\s*&\s*co\.?\s*ohg", r"ag\s*&\s*co\.?\s*kg",
    r"ggmbh", r"gmbh", r"mbh", r"ag", r"kg", r"ohg", r"se", r"ug", r"e\.?\s*v\.?",
    r"a\.?ö\.?r\.?", r"aör", r"kdör", r"ltd\.?", r"inc\.?", r"llc", r"b\.?v\.?", r"s\.?a\.?",
]
LEGAL_RE = re.compile(r"\b(" + "|".join(LEGAL_FORMS) + r")(?=\W|$)", re.I)


def org_key(org: str) -> str:
    if not isinstance(org, str) or not org.strip():
        return ""
    s = org.casefold()
    s = LEGAL_RE.sub(" ", s)
    s = re.sub(r"[^\w\s]", " ", s)          # noktalama
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_entities() -> list[dict]:
    files = sorted(RAW_DIR.glob("page_*.json"))
    print(f"{len(files)} sayfa dosyasi bulundu.")
    rows = []
    for f in files:
        js = json.loads(f.read_text(encoding="utf-8"))
        rows.extend(js.get("entities", []))
    return rows


def main():
    ents = load_entities()
    df = pd.DataFrame(ents)
    print(f"Ham kayit: {len(df)}")

    for col in ["firstName", "lastName", "position", "organization", "userType", "logoUrl"]:
        if col not in df.columns:
            df[col] = ""
    df = df.fillna({"firstName": "", "lastName": "", "position": "", "organization": "",
                    "userType": "none", "logoUrl": ""})

    df = df.drop_duplicates(subset=["id"]).reset_index(drop=True)
    print(f"Tekil kisi: {len(df)}")

    people = pd.DataFrame({
        "id": df["id"],
        "name": (df["firstName"].str.strip() + " " + df["lastName"].str.strip()).str.strip(),
        "position": df["position"].str.strip(),
        "organization": df["organization"].str.strip(),
        "org_key": df["organization"].map(org_key),
        "userType": df["userType"],
        "has_photo": df["logoUrl"].astype(bool),
        "categories": df.get("categories", pd.Series([[]] * len(df))).map(
            lambda x: ", ".join(map(str, x)) if isinstance(x, list) else ""),
    })

    # first_seen: kisi ilk hangi calistirmada goruldu? (09/10 "Neu" isareti icin)
    # Onceki people.csv varsa oradaki tarih korunur; o dosyada kolon yoksa dosyanin tarihi kullanilir.
    today = date.today().isoformat()
    prev_f = OUT_DIR / "people.csv"
    seen = {}
    if prev_f.exists():
        prev = pd.read_csv(prev_f, dtype=str)
        prev_day = datetime.fromtimestamp(prev_f.stat().st_mtime).date().isoformat()
        col = prev["first_seen"] if "first_seen" in prev.columns else pd.Series(prev_day, index=prev.index)
        seen = dict(zip(prev["id"], col.fillna(prev_day)))
    people["first_seen"] = people["id"].map(seen).fillna(today)
    n_new = int((people["first_seen"] == today).sum()) if seen else 0
    if seen:
        gone = len(set(seen) - set(people["id"]))
        print(f"Onceki calistirmaya gore: {n_new} yeni kisi, {gone} kisi artik listede yok.")

    # kurum tablosu: ayni org_key altinda en sik gecen yazilisi goster
    has_org = people[people["org_key"] != ""]
    companies = (
        has_org.groupby("org_key")
        .agg(
            organization=("organization", lambda s: s.value_counts().index[0]),
            n_people=("id", "count"),
            n_staff=("userType", lambda s: (s == "staff").sum()),
            n_attendee=("userType", lambda s: (s == "attendee").sum()),
            n_speaker=("userType", lambda s: (s == "speaker").sum()),
            positions=("position", lambda s: " | ".join(sorted({p for p in s if p})[:8])),
        )
        .reset_index()
        .sort_values("n_people", ascending=False)
    )
    # stand acan firma mi (en az bir staff varsa exhibitor sayiyoruz)
    companies["is_exhibitor"] = companies["n_staff"] > 0

    OUT_DIR.mkdir(exist_ok=True)
    people.to_csv(OUT_DIR / "people.csv", index=False, encoding="utf-8-sig")
    companies.to_csv(OUT_DIR / "companies.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(OUT_DIR / "scc_overview.xlsx", engine="openpyxl") as xw:
        people.to_excel(xw, sheet_name="people", index=False)
        companies.to_excel(xw, sheet_name="companies", index=False)

    print("\nuserType dagilimi:")
    print(people["userType"].value_counts().to_string())
    print(f"\nKurum sayisi: {len(companies)}  (exhibitor: {companies['is_exhibitor'].sum()})")
    print(f"Pozisyonu bos: {(people['position'] == '').sum()}, kurumu bos: {(people['organization'] == '').sum()}")
    print("\nEn kalabalik 15 kurum:")
    print(companies.head(15)[["organization", "n_people", "n_staff", "n_attendee", "n_speaker"]].to_string(index=False))
    print(f"\nCikti: {(OUT_DIR / 'scc_overview.xlsx').resolve()}")


if __name__ == "__main__":
    main()
