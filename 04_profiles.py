# -*- coding: utf-8 -*-
"""
04_profiles.py  -  Herkesin profil detaylarini ceker (LinkedIn, interests, sessions...).
Her profil data/raw/profiles/<id>.json olarak cache'lenir; tekrar calistirinca sadece eksikleri ceker.
~4.100 kisi icin 30-40 dk surer; istedigin an durdurup sonra devam edebilirsin.

  python 04_profiles.py            # herkes (PyCharm Run icin varsayilan)
  python 04_profiles.py --probe    # sadece 1 profil ceker, yapisini gosterir
  python 04_profiles.py --ids baska.csv
"""

import argparse
import json
import time

import pandas as pd

from scc_common import BACKEND, COMMON_PARAMS, DATA, RAW, TOPIC, get_token, make_session, my_user_id, print, request_json

SLEEP = 0.3


def fetch_profile(s, me: str, target: str) -> dict:
    url = f"{BACKEND}/rest/seriesoftopicsuser/topic/{TOPIC}/profile/{me}/targetProfile/{target}"
    return request_json(s, "GET", url, params=COMMON_PARAMS)


def target_ids(ids_file: str | None) -> list[str]:
    """Varsayilan: herkes. Once shortlist'tekiler ve speaker'lar gelir, yarida kesilirse en onemliler hazir olur."""
    people = pd.read_csv(DATA / "people.csv")
    if ids_file:
        df = pd.read_excel(ids_file) if ids_file.endswith("xlsx") else pd.read_csv(ids_file)
        return list(dict.fromkeys(df["id"].dropna().astype(str)))
    first = []
    if (DATA / "shortlist.csv").exists():
        first += pd.read_csv(DATA / "shortlist.csv")["id"].astype(str).tolist()
    first += people.loc[people["userType"] == "speaker", "id"].astype(str).tolist()
    ids = list(dict.fromkeys(first + people["id"].astype(str).tolist()))
    print(f"Hedef: {len(ids)} kisi (once shortlist + speaker'lar)")
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--ids", help="'id' kolonu olan csv/xlsx (varsayilan: data/shortlist.csv + speaker'lar)")
    args = ap.parse_args()

    token = get_token()
    s, me = make_session(token), my_user_id(token)
    out_dir = RAW / "profiles"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.probe:
        people = pd.read_csv(DATA / "people.csv")
        js = fetch_profile(s, me, people.iloc[0]["id"])
        (DATA / "probe_profile.json").write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Anahtarlar:", list(js.keys()) if isinstance(js, dict) else type(js).__name__)
        return

    ids = target_ids(args.ids)
    todo = [p for p in ids if not (out_dir / f"{p}.json").exists()]
    print(f"Toplam {len(ids)} kisi, {len(ids) - len(todo)} zaten var, {len(todo)} cekilecek.")
    for i, pid in enumerate(todo, 1):
        try:
            js = fetch_profile(s, me, pid)
            (out_dir / f"{pid}.json").write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")
            p = js.get("profile", {})
            print(f"[{i}/{len(todo)}] {p.get('firstName', '')} {p.get('lastName', '')} | "
                  f"LI: {'var' if p.get('linkedIn') else '-'} | interests: {len(p.get('interests') or [])}")
        except Exception as e:
            print(f"[{i}/{len(todo)}] {pid[:12]}... HATA: {e}")
        time.sleep(SLEEP)
    print("Bitti.")


if __name__ == "__main__":
    main()
