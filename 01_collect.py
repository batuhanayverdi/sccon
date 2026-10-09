# -*- coding: utf-8 -*-
"""
01_collect.py  -  Smart Country Convention (Corussoft Event Guide) ham veri toplama

pip install requests

Token'i koda YAZMA. Calistirmadan once ortam degiskeni olarak ver:
  cmd:        set SCC_TOKEN=eyJ...
  PowerShell: $env:SCC_TOKEN="eyJ..."
(Verilmezse script gizli giris ile sorar.)

Kullanim:
  python 01_collect.py --probe attendees        # 3 kayit ceker, yapiyi data/probe_attendees.json'a yazar
  python 01_collect.py --probe x --filter "entity_pers"   # istedigin filterlist'i dene
  python 01_collect.py attendees speakers       # tam toplama (kaldigi yerden devam eder)
  python 01_collect.py --fresh attendees sessions exhibitors
        # GUNCELLEME: eski sayfalari data/raw/<ad>_<tarih>/ altina yedekler ve hepsini bastan ceker.
        # Gerekli, cunku sayfalar alfabetik ve offset'li: yeni kayit gelince tum sayfalar kayar,
        # eski sayfa dosyalari cache'ten okunursa yeni kisiler hic gorunmez.
"""

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import functools

import requests

# her print aninda ekrana dussun (PyCharm/Windows'ta buffer'da beklemesin)
print = functools.partial(print, flush=True)

URL ="https://live.messebackend.aws.corussoft.de/webservice/search"
TOPIC = "2022_SCC"
PAGE_SIZE = 100          # sunucu daha azini donerse script ona uyum saglar
SLEEP = 0.7              # istekler arasi bekleme (sn), sunucuyu yormamak icin
MAX_PAGES = 2000
RAW_DIR = Path("data/raw")

# attendees dogrulandi; digerleri tahmin -> --probe ile ya da ilgili sayfanin
# Network istegindeki filterlist degeriyle dogrulayacagiz
ENTITIES = {
    "attendees": "entity_sotu, sotucbt_ALL",
    "speakers": "entity_pers",
    "sessions": "entity_evtd",
    "exhibitors": "entity_orga",
}


def get_token() -> str:
    tok = os.environ.get("SCC_TOKEN", "").strip()
    token_file = Path(__file__).parent / "scc_token.txt"
    if tok:
        print("Token SCC_TOKEN ortam degiskeninden alindi.")
    elif token_file.exists():
        tok = token_file.read_text(encoding="utf-8").strip()
        print(f"Token {token_file.name} dosyasindan alindi.")
    else:
        # getpass Windows/PyCharm terminalinde yapistirmayi algilamayip takilabiliyor,
        # o yuzden normal input kullaniyoruz (token ekranda gorunur).
        print(f"Token bulunamadi. Ya {token_file.name} dosyasi olustur, ya da buraya yapistir.")
        tok = input("beconnectiontoken: ").strip()
    if not tok:
        sys.exit("Token yok.")
    print(f"Token uzunlugu: {len(tok)} karakter (beklenen ~300+)")
    return tok


def make_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "beconnectiontoken": token,
        "ec-client": "EventGuide/2.26.2-11515[52]",
        "ec-client-branding": TOPIC,
        "origin": "https://online.smartcountry.berlin",
        "referer": "https://online.smartcountry.berlin/",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"),
    })
    return s


def fetch(s: requests.Session, filterlist: str, start: int, n: int) -> dict:
    data = {
        "topic": TOPIC,
        "os": "web",
        "appUrl": "https://online.smartcountry.berlin",
        "lang": "en",
        "apiVersion": "52",
        "timezoneOffset": "0",
        "filterlist": filterlist,
        "startresultrow": str(start),
        "numresultrows": str(n),
        "order": "lexic",
    }
    for attempt in range(4):
        print(f"  -> istek gonderiliyor (start={start}, n={n}, deneme {attempt + 1})...")
        t0 = time.time()
        try:
            r = s.post(URL, data=data, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f"  !! baglanti hatasi: {e}")
            time.sleep(5)
            continue
        print(f"  <- HTTP {r.status_code}, {len(r.content)} byte, {time.time() - t0:.1f}s")
        if r.status_code in (401, 403):
            sys.exit(f"HTTP {r.status_code}: token gecersiz/suresi dolmus. Yeniden login olup yeni token al.")
        if r.status_code == 429 or r.status_code >= 500:
            wait = 5 * (attempt + 1)
            print(f"  HTTP {r.status_code}, {wait}s bekleyip tekrar deniyorum...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Tekrar denemeler basarisiz.")


def biggest_dict_list(obj) -> list:
    """Response icindeki en uzun 'dict listesi'ni bulur (sonuc listesi yapisini bilmeden)."""
    best = []
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            best = obj
        for x in obj:
            c = biggest_dict_list(x)
            if len(c) > len(best):
                best = c
    elif isinstance(obj, dict):
        for v in obj.values():
            c = biggest_dict_list(v)
            if len(c) > len(best):
                best = c
    return best


def probe(s, name: str, filterlist: str):
    js = fetch(s, filterlist, 0, 3)
    out = Path("data") / f"probe_{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"filterlist = {filterlist!r}")
    print("Ust seviye anahtarlar:", list(js.keys()) if isinstance(js, dict) else type(js).__name__)
    items = biggest_dict_list(js)
    print(f"Bulunan kayit sayisi (bu sayfada): {len(items)}")
    if items:
        print("Ilk kaydin anahtarlari:", list(items[0].keys()))
    print(f"Tam cikti: {out.resolve()}")


def backup_raw(name: str):
    """data/raw/<name> -> data/raw/<name>_<YYYYMMDD-HHMM> (sadece yeniden cekmeden once)."""
    src = RAW_DIR / name
    if src.exists() and any(src.glob("page_*.json")):
        dst = RAW_DIR / f"{name}_{datetime.now():%Y%m%d-%H%M}"
        shutil.move(str(src), str(dst))
        print(f"[{name}] eski sayfalar yedeklendi -> {dst}")


def collect(s, name: str, filterlist: str):
    out_dir = RAW_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    start, total, prev_first = 0, 0, None

    for _ in range(MAX_PAGES):
        f = out_dir / f"page_{start:06d}.json"
        if f.exists():
            js = json.loads(f.read_text(encoding="utf-8"))
            cached = True
        else:
            js = fetch(s, filterlist, start, PAGE_SIZE)
            f.write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")
            cached = False

        items = biggest_dict_list(js)
        if not items:
            if not cached:
                f.unlink()  # bos son sayfayi saklama
            break

        first = json.dumps(items[0], sort_keys=True)
        if first == prev_first:
            print("  Ayni sayfa tekrar geldi, sayfalama bitti sayiyorum.")
            break
        prev_first = first

        total += len(items)
        print(f"[{name}] start={start:>6}  +{len(items):>3}  toplam={total}{'  (cache)' if cached else ''}")
        start += len(items)

        if not cached:
            time.sleep(SLEEP)

    print(f"[{name}] bitti: {total} kayit -> {out_dir.resolve()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entities", nargs="*", default=["attendees"])
    ap.add_argument("--probe", metavar="NAME", help="3 kayitlik deneme istegi at")
    ap.add_argument("--filter", help="filterlist degerini elle ver")
    ap.add_argument("--fresh", action="store_true",
                    help="eski sayfalari yedekle ve bastan cek (guncelleme icin)")
    args = ap.parse_args()
    print("Script basladi.")

    s = make_session(get_token())

    if args.probe:
        fl = args.filter or ENTITIES.get(args.probe)
        if not fl:
            sys.exit(f"'{args.probe}' icin filterlist yok, --filter ile ver.")
        probe(s, args.probe, fl)
        return

    for name in args.entities:
        fl = args.filter or ENTITIES.get(name)
        if not fl:
            print(f"'{name}' bilinmiyor, atliyorum.")
            continue
        if args.fresh:
            backup_raw(name)
        collect(s, name, fl)


if __name__ == "__main__":
    main()
