# -*- coding: utf-8 -*-
"""
11_site.py  -  SCC_Planner.html'i yayinlanabilir, sifre korumali ve telefonda offline calisan bir siteye cevirir.

Neden sifre: Cloudflare Access'in mail kodu yontemi kurumsal mail taramasi yuzunden calismiyor
(maildeki tek tikla giris linkini tarama robotu aciyor, kod tukeniyor). Bunun yerine sayfanin
tum icerigini burada sifreliyoruz. Yayindaki dosyada okunabilir hicbir kisisel veri yok;
sifre sadece kullanicinin tarayicisinda cozuluyor.

  data/site/index.html            -> sifre ekrani + sifrelenmis planlayici
  data/site/manifest.webmanifest  -> "Ana ekrana ekle" icin isim/ikon
  data/site/sw.js                 -> service worker: ilk acilistan sonra internet olmadan da calisir
  data/site/_headers              -> arama motorlarina kapali, guvenlik basliklari
  data/site/README.txt            -> yayinlama adimlari

Kullanim:
  python 11_site.py                 -> sifreyi sorar (ya da site_password.txt / SCC_SITE_PASSWORD kullanir)
  python 11_site.py "Parola123"     -> sifreyi parametre olarak alir
  python 11_site.py --offen         -> sifresiz surum (sadece Access gibi baska bir koruma varsa)

Gereksinim: pip install cryptography
Not: Sifreli surum https uzerinden calisir (tarayicinin crypto API'si sadece guvenli baglantida acik).
     Dosyayi cift tiklayip acmak icin 10_html.py ciktisini kullan.
"""

import base64
import hashlib
import os
import sys

from scc_common import DATA, HERE, print

SRC = DATA / "SCC_Planner.html"
SITE = DATA / "site"
ITERATIONS = 210000

MANIFEST = """{
  "name": "SCC 2026 Planung",
  "short_name": "SCC 2026",
  "start_url": "./index.html",
  "scope": "./",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#ffffff",
  "icons": [{"src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}]
}
"""

ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
<rect width="192" height="192" rx="28" fill="#1f3864"/>
<text x="96" y="86" font-family="Arial, Helvetica, sans-serif" font-size="52" font-weight="bold"
      fill="#ffffff" text-anchor="middle">SCC</text>
<text x="96" y="140" font-family="Arial, Helvetica, sans-serif" font-size="44"
      fill="#ffffff" text-anchor="middle">2026</text>
</svg>
"""

SW = """// Offline-Cache: beim ersten Aufruf speichern, danach ohne Netz nutzbar (Messe-WLAN ist unzuverlässig).
// Wichtig: der Worker liefert IMMER eine Antwort. Sonst zeigt Safari "Seite kann nicht geoeffnet werden".
const CACHE = "scc-planner-__VERSION__";
const FILES = ["./", "./index.html", "./manifest.webmanifest", "./icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    for (const f of FILES) { try { await c.add(f); } catch (err) {} }   // ein fehlendes File darf nicht alles kippen
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    const ks = await caches.keys();
    await Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});
function offlinePage() {
  return new Response("<!DOCTYPE html><meta charset=utf-8><meta name=viewport content=\\"width=device-width,initial-scale=1\\">"
    + "<body style=\\"font:15px Arial;padding:24px\\"><h1 style=font-size:18px>Keine Verbindung</h1>"
    + "<p>Die Seite ist auf diesem Gerät noch nicht gespeichert. Bitte einmal mit Internet öffnen.</p>"
    + "<p><a href=\\"./index.html\\">Erneut versuchen</a></p>",
    {status: 200, headers: {"Content-Type": "text/html; charset=utf-8"}});
}

// Seite selbst: erst Netz (max. 5 s), sonst gespeicherte Kopie. So sieht das Team nach einem neuen
// Upload sofort die aktuelle Fassung und bleibt trotzdem ohne Netz arbeitsfähig.
async function pageFirstNet(req) {
  try {
    const res = await Promise.race([
      fetch(req, {cache: "no-store"}),
      new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 5000)),
    ]);
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put("./index.html", copy)).catch(() => {});
      return res;
    }
  } catch (err) {}
  const hit = await caches.match("./index.html", {ignoreSearch: true, ignoreVary: true});
  return hit || offlinePage();
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin || url.pathname.startsWith("/cdn-cgi/")) return;   // Login-/Systemwege nicht abfangen
  const isPage = req.mode === "navigate" || url.pathname === "/" || url.pathname.endsWith("/index.html");
  if (isPage) { e.respondWith(pageFirstNet(req)); return; }
  e.respondWith((async () => {
    const hit = await caches.match(req, {ignoreSearch: true, ignoreVary: true});
    if (hit) return hit;
    try {
      const res = await fetch(req);
      if (res && res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {}); }
      return res;
    } catch (err) {
      return offlinePage();
    }
  })());
});
"""

# --kein-sw modunda yayinlanan sw.js: eski worker'i ve onbellegi temizleyip kendini siler.
SW_UNINSTALL = """// Kill-Switch: entfernt den alten Offline-Worker und den Cache, danach lädt alles normal vom Server.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    const ks = await caches.keys();
    await Promise.all(ks.map(k => caches.delete(k)));
    await self.registration.unregister();
    const cs = await self.clients.matchAll({type: "window"});
    cs.forEach(c => c.navigate(c.url));
  })());
});
"""

HEADERS = """/*
  X-Robots-Tag: noindex, nofollow
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
/sw.js
  Cache-Control: no-cache
/index.html
  Cache-Control: no-cache
"""

SW_REGISTER = ('<script>if("serviceWorker" in navigator && window.isSecureContext)'
               'addEventListener("load",()=>navigator.serviceWorker.register("sw.js").catch(()=>{}));</script>')

# Offline-Kopie aus: einen evtl. vorhandenen alten Service Worker entfernen, damit er nichts mehr abfaengt.
SW_KILL = ('<script>if("serviceWorker" in navigator)navigator.serviceWorker.getRegistrations()'
           '.then(rs=>rs.forEach(r=>r.unregister())).catch(()=>{});'
           'if(window.caches)caches.keys().then(ks=>ks.forEach(k=>caches.delete(k))).catch(()=>{});</script>')

HEAD_INJECT = ('<link rel="manifest" href="manifest.webmanifest">\n'
               '<meta name="apple-mobile-web-app-capable" content="yes">\n'
               '<meta name="apple-mobile-web-app-title" content="SCC 2026">\n'
               '<link rel="apple-touch-icon" href="icon.svg">\n' + SW_REGISTER + "\n")

# ---------------------------------------------------------------- sifre ekrani
SHELL = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>SCC 2026 – Planung</title>
__HEAD__
<style>
  html,body{margin:0;height:100%;background:#fff;color:#222;
            font:15px/1.5 Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%}
  .wrap{min-height:100%;display:flex;align-items:center;justify-content:center;padding:24px;box-sizing:border-box}
  .box{width:100%;max-width:320px}
  h1{font-size:18px;margin:0 0 4px}
  p{color:#555;margin:0 0 16px}
  input{width:100%;box-sizing:border-box;font-size:16px;padding:10px;border:1px solid #bbb;border-radius:4px}
  button{width:100%;margin-top:10px;font-size:16px;padding:10px;border:1px solid #1f3864;border-radius:4px;
         background:#1f3864;color:#fff;cursor:pointer}
  button[disabled]{opacity:.6;cursor:default}
  .msg{margin-top:12px;font-size:13px;min-height:18px}
  .err{color:#b00020}
  .hint{margin-top:20px;font-size:12px;color:#888}
</style>
</head>
<body>
<div class="wrap"><div class="box">
  <h1>SCC 2026 – Planung</h1>
  <p>Interne Arbeitsdatei von Univention. Bitte das Passwort vom Team eingeben.</p>
  <form id="f">
    <input type="password" id="pw" placeholder="Passwort" autocomplete="current-password"
           autocapitalize="none" autocorrect="off" spellcheck="false">
    <button type="submit" id="go">Öffnen</button>
  </form>
  <div class="msg" id="msg"></div>
  <div class="hint">Nach dem ersten Öffnen: Teilen &gt; Zum Home-Bildschirm. Danach läuft die Seite auch ohne Netz.</div>
</div></div>
<script id="payload" type="text/plain">__DATA__</script>
<script>
const CFG = {salt:"__SALT__", iv:"__IV__", iter:__ITER__};
const LSKEY = "scc2026-pw";
const msg = document.getElementById("msg");
const pw  = document.getElementById("pw");
const go  = document.getElementById("go");

function bytes(s){ const b = atob(s), a = new Uint8Array(b.length);
  for(let i=0;i<b.length;i++) a[i] = b.charCodeAt(i); return a; }

async function decrypt(pass){
  const enc = new TextEncoder();
  const base = await crypto.subtle.importKey("raw", enc.encode(pass), "PBKDF2", false, ["deriveKey"]);
  const key  = await crypto.subtle.deriveKey(
    {name:"PBKDF2", salt:bytes(CFG.salt), iterations:CFG.iter, hash:"SHA-256"},
    base, {name:"AES-GCM", length:256}, false, ["decrypt"]);
  const data = bytes(document.getElementById("payload").textContent.trim());
  const plain = await crypto.subtle.decrypt({name:"AES-GCM", iv:bytes(CFG.iv)}, key, data);
  return new TextDecoder().decode(plain);
}

function show(html){ document.open(); document.write(html); document.close(); }

async function tryPass(pass, remember){
  msg.className = "msg"; msg.textContent = "Wird geöffnet …";
  go.disabled = true;
  try{
    const html = await decrypt(pass);
    if(remember){ try{ localStorage.setItem(LSKEY, pass); }catch(e){} }
    show(html);
  }catch(e){
    try{ localStorage.removeItem(LSKEY); }catch(e2){}
    msg.className = "msg err"; msg.textContent = "Passwort stimmt nicht.";
    go.disabled = false; pw.value = ""; pw.focus();
  }
}

document.getElementById("f").addEventListener("submit", e => {
  e.preventDefault();
  const v = pw.value.trim();
  if(v) tryPass(v, true);
});

if(!window.crypto || !crypto.subtle){
  msg.className = "msg err";
  msg.textContent = "Diese Seite muss über https geöffnet werden.";
  go.disabled = true;
}else{
  let saved = null;
  try{ saved = localStorage.getItem(LSKEY); }catch(e){}
  if(saved) tryPass(saved, false); else pw.focus();
}
</script>
</body>
</html>
"""

README = """SCC Planner als Website (iPhone, iPad, Laptop)
=============================================

Die Seite ist passwortgeschützt: der gesamte Inhalt liegt verschlüsselt auf dem Server (AES-256-GCM).
Ohne Passwort ist in der ausgelieferten Datei kein Name und kein Termin lesbar. Entschlüsselt wird
ausschließlich im Browser der Nutzer:innen.

Veröffentlichen
---------------
1. Den Inhalt von data/site (nicht den Ordner selbst) als ZIP packen.
2. Cloudflare > Compute > Workers & Pages > Worker auswählen > New deployment > ZIP hochladen.
3. Die URL bleibt gleich, bestehende Markierungen der Kolleg:innen bleiben erhalten.

Falls Cloudflare Access noch aktiv ist
--------------------------------------
Access und Passwort zusammen sind doppelte Arbeit für die Kolleg:innen. Access abschalten:
Worker > Access > Manage access > Access deaktivieren bzw. entfernen.

Weitergabe an das Team
----------------------
  Link: <URL>
  Passwort: <Passwort, getrennt vom Link schicken, z.B. per Chat>
  Einmal öffnen, Passwort eingeben, dann Teilen > "Zum Home-Bildschirm".
  Danach keine Passwortabfrage mehr, und die Seite funktioniert auch ohne Netz.

Aktualisieren
-------------
09 und 10 laufen lassen, dann 11_site.py mit demselben Passwort, danach neu hochladen.
Markierungen und Notizen liegen im Browser des jeweiligen Geräts und bleiben erhalten.
Ein neues Passwort heißt nur: alle geben es einmal neu ein, die Notizen bleiben trotzdem.
"""


def get_password(argv) -> str:
    if {"--offen", "--open", "--no-password"} & set(argv):
        return ""
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        return args[0].strip()
    env = os.environ.get("SCC_SITE_PASSWORD", "").strip()
    if env:
        print("Passwort aus SCC_SITE_PASSWORD.")
        return env
    f = HERE / "site_password.txt"
    if f.exists():
        print(f"Passwort aus {f.name}.")
        return f.read_text(encoding="utf-8").strip()
    print("Passwort fuer die Website (leer lassen = ohne Passwort veroeffentlichen):")
    return input("Passwort: ").strip()


def encrypt(html: str, password: str, head: str) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise SystemExit("Eksik paket. Bir kez calistir:  pip install cryptography")
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS, 32)
    blob = AESGCM(key).encrypt(iv, html.encode("utf-8"), None)
    b64 = base64.b64encode
    return (SHELL.replace("__HEAD__", head)
                 .replace("__SALT__", b64(salt).decode())
                 .replace("__IV__", b64(iv).decode())
                 .replace("__ITER__", str(ITERATIONS))
                 .replace("__DATA__", b64(blob).decode()))


def main():
    if not SRC.exists():
        raise SystemExit(f"{SRC} yok. Once 10_html.py calistir.")
    SITE.mkdir(parents=True, exist_ok=True)

    # --kein-sw: offline kaydi olmadan. Sayfa her acilista sunucudan gelir, telefonda takilan
    # bir service worker ihtimali tamamen ortadan kalkar. Internet yoksa sayfa acilmaz.
    use_sw = not ({"--kein-sw", "--no-sw", "--kein-offline"} & set(sys.argv))
    head = HEAD_INJECT if use_sw else HEAD_INJECT.replace(SW_REGISTER + "\n", SW_KILL + "\n")

    html = SRC.read_text(encoding="utf-8")
    if "manifest.webmanifest" not in html:
        html = html.replace("</head>", head + "</head>", 1)

    password = get_password(sys.argv)
    if password:
        page = encrypt(html, password, head)
        print(f"Icerik sifrelendi (AES-256-GCM, PBKDF2 {ITERATIONS} tur).")
    else:
        page = html
        print("!! Sifresiz: linki olan herkes butun verileri gorur.")

    version = hashlib.sha1(page.encode("utf-8")).hexdigest()[:10]
    (SITE / "index.html").write_text(page, encoding="utf-8")
    (SITE / "manifest.webmanifest").write_text(MANIFEST, encoding="utf-8")
    (SITE / "icon.svg").write_text(ICON, encoding="utf-8")
    if use_sw:
        (SITE / "sw.js").write_text(SW.replace("__VERSION__", version), encoding="utf-8")
    else:
        # sw.js bleibt liegen, aber als Kill-Switch: sonst behalten alte Geraete ihren alten Worker.
        (SITE / "sw.js").write_text(SW_UNINSTALL, encoding="utf-8")
        print("Offline-Kopie aus: Seite laedt immer vom Server, alte Service Worker werden entfernt.")
    (SITE / "_headers").write_text(HEADERS, encoding="utf-8")
    (SITE / "README.txt").write_text(README, encoding="utf-8")
    (SITE / "staticwebapp.config.json").unlink(missing_ok=True)   # Azure ornegi artik gereksiz

    size = (SITE / "index.html").stat().st_size / 1e6
    print(f"Site hazir: {SITE}  (index.html {size:.1f} MB, Version {version})")
    print("Sonraki adim: data/site icindekileri zip'le, Cloudflare'de New deployment ile yukle.")


if __name__ == "__main__":
    main()
