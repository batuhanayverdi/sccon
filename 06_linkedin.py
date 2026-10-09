# -*- coding: utf-8 -*-
"""
06_linkedin.py  -  Oncelikli kisilerin LinkedIn profillerinden headline, follower, about, deneyim ceker.

pip install playwright pandas
(Chromium zaten kuruluysa 'playwright install' gerekmez; degilse bir kez: playwright install chromium)

- Kendi LinkedIn hesabinla ELLE login olursun (cookie koda yazilmaz). Oturum .linkedin_profile/ klasorunde kalir.
- Sira: 05 adimindaki priority'ye gore (en yuksek once). Varsayilan: priority >= 2.
- Her calistirmada en fazla MAX_PER_RUN profil. LinkedIn cok sayida otomatik ziyarette hesabi
  kisitlayabiliyor; gunde 1-2 tur yeterli. Yarida kalirsa tekrar calistir, cekilenleri atlar.
- Cikti: data/raw/linkedin/<id>.json  +  data/linkedin.csv  (05 tekrar calisinca rapora eklenir)
"""

import json
import random
import re
import time
from urllib.parse import unquote
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

from scc_common import DATA, HERE, RAW, print

MIN_PRIORITY = 2
MAX_PER_RUN = 80
REFETCH_OLD = True    # eski surumle cekilip experience'i eksik kalanlari, yeniler bittikten sonra BIR KEZ daha ac
SCRAPE_VERSION = 4
WAIT_RANGE = (3, 7)        # profiller arasi rastgele bekleme (sn)
USER_DATA_DIR = str(HERE / ".linkedin_profile")
OUT_DIR = RAW / "linkedin"
PEOPLE_CACHE = DATA / "llm_cache" / "people_v1.jsonl"   # 05'in cache'i (priority icin)


def parse_count(txt: str) -> int | None:
    """'1,234' / '1.234' / '12K' / '1,2 Mio.' -> int"""
    m = re.match(r"([\d.,]+)\s*([KkMm])?", txt.strip())
    if not m:
        return None
    num, suf = m.group(1), (m.group(2) or "").lower()
    if suf:
        val = float(num.replace(",", "."))
        return int(val * (1_000 if suf == "k" else 1_000_000))
    return int(re.sub(r"[^\d]", "", num) or 0)


SKIP_LINE = re.compile(r"^(\(?(he|she|they|er|sie)/|·|• ?\d|1st|2nd|3rd|\d+(st|nd|rd|th)\b|"
                       r"contact info|kontaktinfo|verified|verifiziert|premium)", re.I)


def find_headline(page, main_text: str, name: str = "") -> str:
    """Isim satirindan sonraki ilk anlamli satir = headline. Class isimlerine bagli degil."""
    if not name and page is not None:
        try:
            name = page.locator("h1").first.inner_text(timeout=3000).strip()
        except Exception:
            return ""
    lines = [l.strip() for l in main_text.splitlines() if l.strip()]
    idx = next((i for i, l in enumerate(lines) if name and (l == name or l.startswith(name))), None)
    if idx is None:
        return ""
    for l in lines[idx + 1: idx + 6]:
        if l != name and len(l) > 3 and not SKIP_LINE.match(l):
            return l[:300]
    return ""


HEADINGS = {
    "about": ["About", "Info", "Über mich"],
    "experience": ["Experience", "Berufserfahrung", "Erfahrung"],
}
ALL_HEADINGS = {"About", "Info", "Über mich", "Experience", "Berufserfahrung", "Erfahrung", "Activity",
                "Aktivitäten", "Education", "Ausbildung", "Skills", "Kenntnisse", "Featured", "Im Fokus",
                "Highlights", "Licenses & certifications", "Bescheinigungen und Zertifikate", "Languages",
                "Sprachen", "Interests", "Interessen", "Recommendations", "Empfehlungen", "Volunteering",
                "Ehrenamt", "Projects", "Projekte", "Publications", "Publikationen", "Honors & awards",
                "Auszeichnungen", "Resources", "Ressourcen", "Analytics", "Analysen", "Services",
                "Dienstleistungen", "People also viewed", "Andere Mitglieder sahen sich auch an"}


FOOTER_MARKERS = {"Talent Solutions", "Community Guidelines", "Community-Richtlinien", "Careers", "Karriere"}


def strip_footer(lines: list[str]) -> list[str]:
    """Sayfanin altindaki LinkedIn footer'ini ('About · Accessibility · Talent Solutions ...') kes.
    Yoksa profilinde About olmayan kisilerde footer'daki 'About' linki About bolumu saniliyor."""
    for i, l in enumerate(lines):
        if l in ("Accessibility", "Barrierefreiheit") and any(m in FOOTER_MARKERS for m in lines[i + 1:i + 4]):
            cut = i - 1 if i > 0 and lines[i - 1] in ("About", "Info") else i
            return lines[:cut]
        if l.startswith("LinkedIn Corporation ©"):
            return lines[:i]
    return lines


def section_from_text(text: str, key: str, limit: int) -> str:
    """Sayfa metninde 'About'/'Experience' basligini bulur, bir sonraki bilinen basliga kadar alir.
    HTML class/id'lerine bagli degil; LinkedIn arayuzu Ingilizce ya da Almanca olabilir."""
    lines = strip_footer([l.strip() for l in text.splitlines() if l.strip()])
    for i, l in enumerate(lines):
        if l in HEADINGS[key]:
            out = []
            for m in lines[i + 1:]:
                if not out and m in HEADINGS[key]:   # baslik iki kez yazilmis olabilir
                    continue
                if m in ALL_HEADINGS:
                    break
                if not out or m != out[-1]:   # LinkedIn bazi satirlari iki kez yaziyor
                    out.append(m)
            return "\n".join(out)[:limit]
    return ""


def scrape(page, url: str) -> dict:
    page.goto(url, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    if any(k in page.url for k in ("/checkpoint", "/authwall", "/login")):
        raise PermissionError(f"LinkedIn engelledi/login istedi: {page.url}")
    # Experience, uzun "Activity" bolumunun altinda ve ancak oraya inilince yukleniyor:
    # sayfanin sonuna kadar adim adim in
    for _ in range(8):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(700)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1500)

    try:
        main = page.locator("main").first.inner_text(timeout=15_000)
    except Exception:  # bazen <main> gec geliyor ya da hic yok -> tum sayfa metni
        main = page.locator("body").inner_text(timeout=15_000)
    fol = re.search(r"([\d.,]+\s*[KkMm]?)\s+(?:followers|Follower)", main)
    con = re.search(r"(500\+|[\d.,]+)\s+(?:connections|Kontakte)", main)

    headline = find_headline(page, main)

    return {
        "li_followers": parse_count(fol.group(1)) if fol else None,
        "li_connections": con.group(1) if con else "",
        "li_headline": headline,
        "li_about": section_from_text(main, "about", 1500),
        "li_experience": section_from_text(main, "experience", 1200),
        "li_final_url": page.url,
        "li_raw": main[:30000],
        "v": SCRAPE_VERSION,   # ham metin: ayristirma bozuksa sayfayi tekrar acmadan duzeltebilelim
    }


def scrape_experience(page, url: str) -> tuple[str, str]:
    """Deneyimi LinkedIn'in ayri deneyim sayfasindan (…/details/experience/) alir.
    Ana profil sayfasinda experience uzun 'Activity' akisinin altinda kaliyor ve cogu zaman yuklenmiyor."""
    page.goto(url.rstrip("/") + "/details/experience/", timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    if any(k in page.url for k in ("/checkpoint", "/authwall", "/login")):
        raise PermissionError(f"LinkedIn engelledi/login istedi: {page.url}")
    for _ in range(3):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(600)
    try:
        txt = page.locator("main").first.inner_text(timeout=15_000)
    except Exception:
        txt = page.locator("body").inner_text(timeout=15_000)
    lines = strip_footer([l.strip() for l in txt.splitlines() if l.strip()])
    # sayfa "Experience"/"Berufserfahrung" basligiyla basliyor; oncesini at, tekrar eden satirlari birlestir
    start = next((i + 1 for i, l in enumerate(lines) if l in HEADINGS["experience"]), 0)
    out = []
    for l in lines[start:]:
        if l in HEADINGS["experience"] or (out and l == out[-1]):
            continue
        out.append(l)
    return "\n".join(out)[:1500], txt[:15000]


def logged_in(ctx) -> bool:
    return any(c["name"] == "li_at" and c["value"] for c in ctx.cookies("https://www.linkedin.com"))


def targets() -> list[tuple[str, str]]:
    prio = {}
    if PEOPLE_CACHE.exists():
        for line in PEOPLE_CACHE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                prio[r["id"]] = r["priority"]
    out = []
    for f in (RAW / "profiles").glob("*.json"):
        url = (json.loads(f.read_text(encoding="utf-8")).get("profile", {}).get("linkedIn") or "").strip()
        if "linkedin.com/in/" in url and prio.get(f.stem, 0) >= MIN_PRIORITY:
            url = unquote(url.split()[0].split("?")[0]).rstrip("/")   # "…/ UND" gibi copleri at
            out.append((prio[f.stem], f.stem, url if url.startswith("http") else "https://" + url))
    out.sort(reverse=True)
    return [(pid, url) for _, pid, url in out]


def needs_fetch(pid: str) -> bool:
    """Hic cekilmemis ya da eski surumle cekilmis (headline/about/experience bos kalan) profiller."""
    f = OUT_DIR / f"{pid}.json"
    if not f.exists():
        return True
    d = json.loads(f.read_text(encoding="utf-8"))
    # ham metni yok (ilk surum) ya da eski kaydirmayla cekilip experience bos kalmis
    return REFETCH_OLD and d.get("v", 1) < SCRAPE_VERSION and not d.get("li_experience")


def reparse_saved():
    """Kayitli ham metinden (li_raw) alanlari yeniden hesaplar. Ayristirma kodu duzelince
    profilleri tekrar acmadan eski kayitlar da duzelir."""
    names = {}
    pp = DATA / "people.csv"
    if pp.exists():
        names = dict(pd.read_csv(pp)[["id", "name"]].astype(str).values)
    n = 0
    for f in OUT_DIR.glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        raw = d.get("li_raw")
        if not raw:
            continue
        d["li_about"] = section_from_text(raw, "about", 1500)
        if not d.get("li_exp_raw"):   # ayri deneyim sayfasindan gelmediyse ana sayfadan dene
            d["li_experience"] = section_from_text(raw, "experience", 1200)
        d["li_headline"] = d.get("li_headline") or find_headline(None, raw, names.get(f.stem, ""))
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        n += 1
    if n:
        print(f"Kayitli {n} profilin ham metni yeniden ayristirildi.")


def write_csv():
    rows = [{"id": f.stem, **json.loads(f.read_text(encoding="utf-8"))} for f in OUT_DIR.glob("*.json")]
    df = pd.DataFrame(rows).drop(columns=["li_raw", "li_exp_raw", "v"], errors="ignore")
    for c in ("li_headline", "li_about", "li_experience"):
        if c in df:
            print(f"  {c} dolu: {int(df[c].fillna('').astype(bool).sum())}/{len(df)}")
    df.to_csv(DATA / "linkedin.csv", index=False, encoding="utf-8-sig")
    print(f"data/linkedin.csv: {len(rows)} profil")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reparse_saved()
    all_t = targets()
    new = [(p, u) for p, u in all_t if not (OUT_DIR / f"{p}.json").exists()]
    redo = [(p, u) for p, u in all_t if (OUT_DIR / f"{p}.json").exists() and needs_fetch(p)]
    todo = (new + redo)[:MAX_PER_RUN]   # once hic cekilmemisler, sonra eski surumle cekilenler
    print(f"Yeni: {len(new)} | eski surumle cekilmis, tekrar denenecek: {len(redo)}")
    print(f"priority>={MIN_PRIORITY} ve LinkedIn'i olan: {len(all_t)} | bu tur: {len(todo)}")
    if not todo:
        write_csv()
        return

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(USER_DATA_DIR, headless=False)
        page = ctx.new_page()
        page.goto("https://www.linkedin.com/feed/")
        page.wait_for_timeout(3000)
        # Login kontrolu: li_at cookie'si var mi? (URL kontrolu yaniltiyordu: login sayfasinin
        # adresinde de "session_redirect=...feed" geciyor)
        while not logged_in(ctx):
            print("\nLinkedIn'e login degilsin. Acilan Chromium penceresinde login ol")
            print("(gerekirse 2FA'yi tamamla), feed'i gorunce buraya donup ENTER'a bas.")
            input("ENTER... ")
        print("Login tamam, oturum .linkedin_profile klasorune kaydedildi (bir dahaki sefere sormaz).")

        for i, (pid, url) in enumerate(todo, 1):
            try:
                f = OUT_DIR / f"{pid}.json"
                old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
                if old.get("li_raw"):
                    data = old            # ana sayfa zaten var -> sadece deneyim sayfasini ac (1 ziyaret)
                else:
                    data = scrape(page, url)
                    time.sleep(random.uniform(*WAIT_RANGE))
                if not data.get("li_experience"):
                    data["li_experience"], data["li_exp_raw"] = scrape_experience(page, url)
                data["v"] = SCRAPE_VERSION
                f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                print(f"[{i}/{len(todo)}] {url.split('/in/')[-1][:28]:28} | fol: {data['li_followers']} | "
                      f"about: {'+' if data['li_about'] else '-'} exp: {'+' if data['li_experience'] else '-'} | "
                      f"{data['li_headline'][:45]}")
            except PermissionError as e:
                print(f"DURDU: {e}\nBir sure bekle, sonra tekrar dene.")
                break
            except Exception as e:
                print(f"[{i}/{len(todo)}] {url} HATA: {e}")
            time.sleep(random.uniform(*WAIT_RANGE))
        ctx.close()
    write_csv()


if __name__ == "__main__":
    main()
