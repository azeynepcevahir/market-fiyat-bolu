# -*- coding: utf-8 -*-
"""
uygulama.py -- tarayicidan calisan alisveris listesi arayuzu.

Kullanim:
    py uygulama.py

Tarayicida http://localhost:8777 acilir. Arama kutusuna yazip urunlere
tiklayarak listenizi kurarsiniz; "Hesapla" dediginizde hangi urunun hangi
markette alinacagi cikar ve OneDrive'a HTML olarak yazilir.

Sadece Python standart kutuphanesi kullanir. Sunucu yalnizca bu bilgisayardan
erisilebilir (127.0.0.1), disariya acik degildir.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import katalog
import market
import rapor
import topla
from market import yaz

ADRES = "127.0.0.1"
KAPI = 8777
LISTE_YOLU = market.PROJE / "listem.json"
FAVORI_YOLU = market.PROJE / "favoriler.json"


# ---------------------------------------------------------------------------
# Veri katmani
# ---------------------------------------------------------------------------

class Depo:
    """Veritabanini bir kez okur, bellekte tutar."""

    def __init__(self) -> None:
        self.yenile()

    def yenile(self) -> None:
        baglanti = market.veritabani()
        self.tarih = rapor.son_tarih(baglanti)
        self.teklifler = rapor.teklifleri_yukle(baglanti, self.tarih) if self.tarih else []
        self.sube_sayisi = baglanti.execute("SELECT COUNT(*) AS n FROM sube").fetchone()["n"]
        baglanti.close()

        # Urun bazinda ozet: kac markette var, en ucuz / en pahali
        ozet: dict[str, dict] = {}
        for t in self.teklifler:
            kayit = ozet.get(t["urun_id"])
            if kayit is None:
                kayit = ozet[t["urun_id"]] = {
                    "urun_id": t["urun_id"], "baslik": t["baslik"],
                    "marka": t["marka"], "gramaj": t["gramaj_ham"],
                    "grup": t["grup"], "kategori": t["ana_kategori"],
                    "birim": t["birim"], "miktar": t["miktar"],
                    "marketler": {}, "arama": market.sadelestir(t["baslik"]),
                }
            mevcut = kayit["marketler"].get(t["market"])
            if mevcut is None or t["fiyat"] < mevcut:
                kayit["marketler"][t["market"]] = t["fiyat"]

        # Marketlerin bildirdigi en son fiyat guncelleme damgasi
        damgalar = [t["guncelleme"] for t in self.teklifler if t["guncelleme"]]
        self.damga = max(damgalar) if damgalar else None

        self.urunler = list(ozet.values())
        for u in self.urunler:
            fiyatlar = list(u["marketler"].values())
            u["en_ucuz"] = min(fiyatlar) if fiyatlar else None
            u["en_pahali"] = max(fiyatlar) if fiyatlar else None
            u["fark"] = (u["en_pahali"] - u["en_ucuz"]) if fiyatlar else 0.0
            u["market_sayisi"] = len(fiyatlar)

    def ara(self, sorgu: str, sinir: int = 60) -> list[dict]:
        parcalar = [p for p in market.sadelestir(sorgu).split() if p]
        if not parcalar:
            return []

        bulunan = []
        for u in self.urunler:
            if all(p in u["arama"] for p in parcalar):
                bulunan.append(u)

        # Once cok markette bulunanlar (karsilastirilabilir olanlar),
        # sonra tasarruf potansiyeli buyuk olanlar.
        bulunan.sort(key=lambda u: (-u["market_sayisi"], -u["fark"]))
        return bulunan[:sinir]


# ---------------------------------------------------------------------------
# Fiyat cekimini arayuzden baslatma
# ---------------------------------------------------------------------------

class Ilerleme:
    """Arka planda calisan cekimin durumu ve ciktisi."""

    def __init__(self) -> None:
        self.kilit = threading.Lock()
        self.calisiyor = False
        self.bitti = False
        self.hata: str | None = None
        self.satirlar: list[str] = []

    def ekle(self, satir: str) -> None:
        with self.kilit:
            self.satirlar.append(satir)
            # Uzun cekimlerde bellek sismesin
            if len(self.satirlar) > 500:
                del self.satirlar[:200]

    def durum(self) -> dict:
        with self.kilit:
            return {
                "calisiyor": self.calisiyor,
                "bitti": self.bitti,
                "hata": self.hata,
                "satirlar": self.satirlar[-40:],
                "toplam_satir": len(self.satirlar),
            }


class _Yakala(io.TextIOBase):
    """topla.py'nin print ciktisini satir satir Ilerleme'ye aktarir."""

    def __init__(self, ilerleme: Ilerleme) -> None:
        self.ilerleme = ilerleme
        self.tampon = ""

    def write(self, metin: str) -> int:
        self.tampon += metin
        while "\n" in self.tampon:
            satir, _, self.tampon = self.tampon.partition("\n")
            if satir.strip():
                self.ilerleme.ekle(satir.rstrip())
        return len(metin)

    def writable(self) -> bool:
        return True


ILERLEME = Ilerleme()


def _cekimi_calistir(depo: "Depo", kapsam: str) -> None:
    try:
        with contextlib.redirect_stdout(_Yakala(ILERLEME)):
            if kapsam == "favori":
                kimlikler = favori_oku()
                kelimeler = topla.favori_kelimeleri(kimlikler)
                if not kelimeler:
                    raise RuntimeError(
                        "Favori yok ya da favorilerin arama kelimesi bilinmiyor. "
                        "Önce tam çekim yapın."
                    )
                print(f"{len(kimlikler)} favori -> {len(kelimeler)} arama kelimesi")
                topla.kelimelerle_topla(kelimeler)
            else:
                topla.topla()
        ILERLEME.ekle("")
        ILERLEME.ekle("Katalog yeniden okunuyor...")
        depo.yenile()
        ILERLEME.ekle(f"{len(depo.urunler)} urun bellege alindi.")
        # Telefondaki dosya da guncellensin
        with contextlib.redirect_stdout(_Yakala(ILERLEME)):
            katalog.uret()
    except Exception as hata:  # noqa: BLE001
        ILERLEME.hata = str(hata)
        ILERLEME.ekle(f"HATA: {hata}")
    finally:
        with ILERLEME.kilit:
            ILERLEME.calisiyor = False
            ILERLEME.bitti = True


def cekimi_baslat(depo: "Depo", kapsam: str = "hepsi") -> dict:
    with ILERLEME.kilit:
        if ILERLEME.calisiyor:
            return {"hata": "Çekim zaten sürüyor."}
        ILERLEME.calisiyor = True
        ILERLEME.bitti = False
        ILERLEME.hata = None
        ILERLEME.satirlar = []

    iplik = threading.Thread(target=_cekimi_calistir, args=(depo, kapsam), daemon=True)
    iplik.start()
    return {"tamam": True, "kapsam": kapsam}


def favori_oku() -> list[str]:
    if not FAVORI_YOLU.exists():
        return []
    try:
        veri = json.loads(FAVORI_YOLU.read_text(encoding="utf-8"))
        return [str(x) for x in veri] if isinstance(veri, list) else []
    except (ValueError, OSError):
        return []


def favori_yaz(kimlikler: list[str]) -> None:
    FAVORI_YOLU.write_text(
        json.dumps(kimlikler, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def liste_oku() -> list[dict]:
    if not LISTE_YOLU.exists():
        return []
    try:
        veri = json.loads(LISTE_YOLU.read_text(encoding="utf-8"))
        return veri if isinstance(veri, list) else []
    except (ValueError, OSError):
        return []


def liste_yaz(kalemler: list[dict]) -> None:
    LISTE_YOLU.write_text(
        json.dumps(kalemler, ensure_ascii=False, indent=1), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Hesaplama
# ---------------------------------------------------------------------------

def hesapla(depo: Depo, secimler: list[dict], maks_market: int) -> dict:
    kalemler = []
    for secim in secimler:
        urun_id = secim.get("urun_id")
        if not urun_id:
            continue
        secenekler, _ = rapor.urun_secenekleri(urun_id, depo.teklifler)
        temsilci = next((t for t in depo.teklifler if t["urun_id"] == urun_id), None)
        kalemler.append({
            "kelime": (temsilci or {}).get("baslik", urun_id),
            "adet": max(1, int(secim.get("adet") or 1)),
            "secenekler": secenekler,
            "cesitler": [],
        })

    if not kalemler:
        return {"hata": "Liste bos."}
    return rapor.dagitimi_coz(kalemler, maks_market)


def sonucu_ozetle(sonuc: dict) -> dict:
    """dagitimi_coz ciktisini tarayiciya gonderilebilir hale getirir."""
    if sonuc.get("hata"):
        return {"hata": sonuc["hata"]}

    markete_gore: dict[str, list] = {}
    for atama in sonuc["atamalar"]:
        markete_gore.setdefault(atama["market"], []).append({
            "baslik": atama["teklif"]["baslik"],
            "gramaj": atama["teklif"]["gramaj_ham"],
            "adet": atama["kalem"]["adet"],
            "fiyat": atama["teklif"]["fiyat"],
            "tutar": atama["tutar"],
            "birim_fiyat": atama["teklif"]["birim_fiyat"],
            "birim": atama["teklif"]["birim"],
        })

    tek = sonuc.get("tek_market")
    return {
        "marketler": [{"kod": m, "ad": rapor.market_adi(m),
                       "kalemler": markete_gore.get(m, []),
                       "ara_toplam": sum(k["tutar"] for k in markete_gore.get(m, []))}
                      for m in sonuc["marketler"] if markete_gore.get(m)],
        "sepet": sonuc["sepet"],
        "maliyet": sonuc["maliyet"],
        "ziyaret_maliyeti": rapor.ZIYARET_MALIYETI,
        "tasarruf": sonuc.get("tasarruf"),
        "tek_market": rapor.market_adi(tek["marketler"][0]) if tek else None,
        "tek_maliyet": tek["maliyet"] if tek else None,
        "kalem_sayisi": sonuc.get("kalem_sayisi", 0),
        "karsilanan": len(sonuc["atamalar"]),
        "eksikler": [k["kelime"] for k in sonuc.get("eksikler", [])],
        "bulunamayan": [k["kelime"] for k in sonuc.get("bulunamayan", [])],
        "kapsam_uyarisi": bool(sonuc.get("kapsam_uyarisi")),
    }


# ---------------------------------------------------------------------------
# Sayfa
# ---------------------------------------------------------------------------

SAYFA = r"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alışveriş Listesi</title><style>
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:#f6f7f9;
     color:#14181f;line-height:1.5}
header{background:#14181f;color:#fff;padding:12px 16px;position:sticky;top:0;z-index:10}
header h1{margin:0;font-size:17px}
header .bilgi{font-size:12px;opacity:.7;margin-top:2px}
.sarma{max-width:1100px;margin:0 auto;padding:16px;display:grid;gap:16px;
       grid-template-columns:1fr 380px}
@media(max-width:900px){.sarma{grid-template-columns:1fr}}
.kutu{background:#fff;border:1px solid #d9dee6;border-radius:10px;padding:14px}
.kutu h2{margin:0 0 10px;font-size:15px}
input[type=search],input[type=number],select{width:100%;padding:10px 12px;font-size:15px;
       border:1px solid #c8cfd9;border-radius:8px;font-family:inherit}
input[type=number]{width:64px;padding:5px 7px;font-size:13px;text-align:center}
.sonuclar{margin-top:12px;max-height:60vh;overflow-y:auto}
.satir{display:flex;gap:10px;align-items:flex-start;padding:9px 4px;
       border-bottom:1px solid #eceff3}
.satir:last-child{border-bottom:none}
.satir .bilgi{flex:1;min-width:0}
.satir .ad{font-size:14px}
.satir .alt{font-size:11px;color:#7b8494;margin-top:2px}
.fiyat{text-align:right;white-space:nowrap;font-size:13px}
.fiyat b{color:#0b7a3b}
button{border:none;border-radius:7px;padding:7px 12px;font-size:13px;cursor:pointer;
       font-family:inherit;font-weight:600}
.ekle{background:#0b7a3b;color:#fff}
.sil{background:transparent;color:#c0392b;padding:2px 6px;font-size:16px}
.yildiz{background:none;border:none;font-size:20px;cursor:pointer;padding:0 2px;
     color:#c2c9d3;line-height:1}
.yildiz.dolu{color:#f0a500}
.birincil{background:#14181f;color:#fff;width:100%;padding:11px;font-size:15px;margin-top:10px}
.birincil:disabled{background:#aab2bd;cursor:not-allowed}
.rozet{display:inline-block;padding:1px 6px;border-radius:99px;font-size:11px;
       background:#eef1f5;color:#5a6472;margin-right:4px}
.rozet.iyi{background:#e8f5ed;color:#0b7a3b}
.bos{color:#7b8494;font-size:13px;padding:14px 0;text-align:center}
.liste .satir{align-items:center}
.ozet{background:#e8f5ed;border:1px solid #b7e0c6;border-radius:8px;padding:12px;margin-top:12px}
.ozet .buyuk{font-size:22px;font-weight:700;color:#0b7a3b}
.ozet .kucuk{font-size:12px;color:#5a6472;margin-top:3px}
.market{margin-top:12px;border:1px solid #d9dee6;border-radius:8px;overflow:hidden}
.market h3{margin:0;background:#14181f;color:#fff;padding:8px 11px;font-size:13px;
           display:flex;justify-content:space-between}
.market .satir{padding:7px 11px;font-size:13px}
.uyari{background:#fff8e6;border:1px solid #f0d68a;border-radius:8px;padding:10px;
       margin-top:10px;font-size:12px}
.yol{font-size:11px;color:#7b8494;word-break:break-all;margin-top:8px}
.kucuk{font-size:12px;color:#5a6472;line-height:1.5}
code{background:#eef1f5;padding:1px 5px;border-radius:4px;font-size:11px}
#cekLog{background:#14181f;color:#c8d3e0;font-size:11px;line-height:1.45;padding:10px;
     border-radius:8px;max-height:220px;overflow:auto;margin:10px 0 0;white-space:pre-wrap;
     font-family:Consolas,monospace}
#cekLog:empty{display:none}
</style></head><body>
<header>
  <h1>Bolu Merkez &mdash; Alışveriş Listesi</h1>
  <div class="bilgi" id="ust">yükleniyor…</div>
</header>

<div class="sarma">
  <div class="kutu">
    <h2>Ürün ara</h2>
    <input type="search" id="q" placeholder="elma, zeytinyağı, mercimek…" autocomplete="off">
    <div class="sonuclar" id="sonuclar"><div class="bos">Aramak için yazın.</div></div>
  </div>

  <div>
    <div class="kutu">
      <h2>Listem (<span id="sayac">0</span>)</h2>
      <div class="liste" id="liste"><div class="bos">Liste boş.</div></div>
      <label style="font-size:12px;color:#5a6472;display:block;margin-top:10px">
        En fazla kaç markete uğrarsınız?
        <select id="maks">
          <option value="1">1 market</option>
          <option value="2" selected>2 market</option>
          <option value="3">3 market</option>
          <option value="4">4 market</option>
        </select>
      </label>
      <button class="birincil" id="hesapla">Hesapla</button>
    </div>

    <div class="kutu" style="margin-top:16px">
      <h2>Fiyatları güncelle</h2>
      <div class="kucuk">
        Bitince katalog yenilenir ve telefondaki <code>Market-Sepet.html</code> de
        güncellenir. Çekim sırasında arama ve sepet çalışmaya devam eder.
        İstekler arasında 2 saniye beklenir — sunucuyu yormamak için.
      </div>
      <button class="birincil" id="cekFavori">★ Sadece favorilerimi güncelle</button>
      <div class="kucuk" style="margin-top:4px" id="favBilgi"></div>
      <button class="birincil" id="cekBaslat"
              style="background:#3a4250">Tüm sepeti çek (13–15 dk)</button>
      <pre id="cekLog"></pre>
    </div>

    <div id="cikti"></div>
  </div>
</div>

<script>
let liste = [], favori = [];
const el = (s) => document.querySelector(s);
const para = (n) => (n == null ? "-" :
  n.toLocaleString("tr-TR", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " TL");

async function durum() {
  const d = await (await fetch("/api/durum")).json();
  el("#ust").textContent =
    `${d.urun_sayisi} ürün · ${d.sube_sayisi} şube · çekim ${d.tarih || "yok"}` +
    (d.damga ? ` · marketlerin son fiyat güncellemesi ${d.damga}` : "");
}

let zamanlayici = null;
el("#q").addEventListener("input", (e) => {
  clearTimeout(zamanlayici);
  const q = e.target.value.trim();
  if (q.length < 2) { el("#sonuclar").innerHTML = '<div class="bos">Aramak için yazın.</div>'; return; }
  zamanlayici = setTimeout(() => ara(q), 220);
});

async function ara(q) {
  const r = await (await fetch("/api/ara?q=" + encodeURIComponent(q))).json();
  if (!r.length) { el("#sonuclar").innerHTML = '<div class="bos">Sonuç yok.</div>'; return; }
  el("#sonuclar").innerHTML = r.map((u) => {
    const cok = u.market_sayisi > 1;
    const yildizli = favori.includes(u.urun_id);
    return `<div class="satir">
      <button class="yildiz ${yildizli ? "dolu" : ""}" data-y="${kacir(u.urun_id)}"
              title="Favorilere ekle">${yildizli ? "★" : "☆"}</button>
      <div class="bilgi">
        <div class="ad">${kacir(u.baslik)}</div>
        <div class="alt">
          <span class="rozet ${cok ? "iyi" : ""}">${u.market_sayisi} markette</span>
          ${u.gramaj ? kacir(u.gramaj) : ""} ${u.grup ? "· " + kacir(u.grup) : ""}
        </div>
      </div>
      <div class="fiyat"><b>${para(u.en_ucuz)}</b>
        ${cok ? `<div class="alt">fark ${para(u.fark)}</div>` : ""}</div>
      <button class="ekle" data-id="${kacir(u.urun_id)}"
              data-ad="${kacir(u.baslik)}">Ekle</button>
    </div>`;
  }).join("");
  el("#sonuclar").querySelectorAll(".ekle").forEach((b) => {
    b.onclick = () => eklePlan(b.dataset.id, b.dataset.ad);
  });
  el("#sonuclar").querySelectorAll(".yildiz").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.y;
      const yer = favori.indexOf(id);
      if (yer >= 0) favori.splice(yer, 1); else favori.push(id);
      b.classList.toggle("dolu");
      b.textContent = b.classList.contains("dolu") ? "★" : "☆";
      await favKaydet();
    };
  });
}

async function favKaydet() {
  el("#favBilgi").textContent = favori.length
    ? `${favori.length} favori ürün kayıtlı.`
    : "Henüz favori yok — arama sonuçlarındaki ☆ ile ekleyin.";
  await fetch("/api/favori", {method: "POST", headers: {"Content-Type": "application/json"},
                              body: JSON.stringify(favori)});
}

function kacir(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function eklePlan(id, ad) {
  if (liste.some((k) => k.urun_id === id)) return;
  liste.push({urun_id: id, baslik: ad, adet: 1});
  cizListe(); kaydet();
}

function cizListe() {
  el("#sayac").textContent = liste.length;
  el("#hesapla").disabled = liste.length === 0;
  if (!liste.length) { el("#liste").innerHTML = '<div class="bos">Liste boş.</div>'; return; }
  el("#liste").innerHTML = liste.map((k, i) => `<div class="satir">
      <div class="bilgi"><div class="ad">${kacir(k.baslik)}</div></div>
      <input type="number" min="1" max="99" value="${k.adet}" data-i="${i}">
      <button class="sil" data-i="${i}">&times;</button>
    </div>`).join("");
  el("#liste").querySelectorAll("input[type=number]").forEach((g) => {
    g.onchange = () => { liste[g.dataset.i].adet = Math.max(1, +g.value || 1); kaydet(); };
  });
  el("#liste").querySelectorAll(".sil").forEach((b) => {
    b.onclick = () => { liste.splice(+b.dataset.i, 1); cizListe(); kaydet(); };
  });
}

async function kaydet() {
  await fetch("/api/liste", {method: "POST", headers: {"Content-Type": "application/json"},
                             body: JSON.stringify(liste)});
}

el("#hesapla").onclick = async () => {
  el("#hesapla").disabled = true;
  el("#hesapla").textContent = "Hesaplanıyor…";
  const r = await (await fetch("/api/hesapla", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({kalemler: liste, maks_market: +el("#maks").value})
  })).json();
  el("#hesapla").disabled = false;
  el("#hesapla").textContent = "Hesapla";
  ciz(r);
};

function ciz(r) {
  if (r.hata) { el("#cikti").innerHTML = `<div class="kutu uyari">${kacir(r.hata)}</div>`; return; }
  let h = '<div class="kutu"><h2>Sonuç</h2><div class="ozet">';
  if (r.tek_market == null) {
    h += `<div class="buyuk">${para(r.maliyet)}</div>
          <div class="kucuk">Tek marketle liste tamamlanmıyor, kıyas yapılmadı.</div>`;
  } else if (r.tasarruf > 0.5) {
    h += `<div class="buyuk">${para(r.tasarruf)} tasarruf</div>
          <div class="kucuk">Tek markete (${kacir(r.tek_market)}) gitseydiniz
          ${para(r.tek_maliyet)} → bu dağılımla ${para(r.maliyet)}
          (${para(r.ziyaret_maliyeti)}/market ziyaret maliyeti dahil)</div>`;
  } else {
    h += `<div class="buyuk">Tek markete gidin</div>
          <div class="kucuk">Gezmek yakıt ve zamana değmiyor. Sistemin dürüst cevabı bu.</div>`;
  }
  h += `<div class="kucuk">Sepet ${para(r.sepet)} · ${r.karsilanan}/${r.kalem_sayisi} kalem karşılandı</div></div>`;

  for (const m of r.marketler) {
    h += `<div class="market"><h3><span>${kacir(m.ad)}</span>
          <span>${m.kalemler.length} kalem · ${para(m.ara_toplam)}</span></h3>`;
    for (const k of m.kalemler) {
      h += `<div class="satir"><div class="bilgi"><div class="ad">${kacir(k.baslik)}${
             k.adet > 1 ? " ×" + k.adet : ""}</div>
             <div class="alt">${k.gramaj ? kacir(k.gramaj) : ""}${
               k.birim_fiyat ? " · " + para(k.birim_fiyat) + "/" + kacir(k.birim) : ""}</div></div>
             <div class="fiyat"><b>${para(k.tutar)}</b></div></div>`;
    }
    h += "</div>";
  }

  if (r.eksikler.length || r.bulunamayan.length) {
    h += '<div class="uyari"><b>Bu listede yok:</b><br>';
    r.eksikler.forEach((k) => h += "• " + kacir(k) + " — seçilen marketlerde yok<br>");
    r.bulunamayan.forEach((k) => h += "• " + kacir(k) + " — fiyat bulunamadı<br>");
    h += "</div>";
  }
  if (r.kapsam_uyarisi) {
    h += '<div class="uyari">Hiçbir market kombinasyonu listenin yeterli kısmını karşılayamadı; en geniş kapsamlı plan gösteriliyor.</div>';
  }
  h += `<button class="birincil" id="disaAktar">Telefona gönder (OneDrive'a yaz)</button>
        <div class="yol" id="yol"></div></div>`;
  el("#cikti").innerHTML = h;
  el("#disaAktar").onclick = async () => {
    const c = await (await fetch("/api/html", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({kalemler: liste, maks_market: +el("#maks").value})
    })).json();
    el("#yol").textContent = c.yol ? "Yazıldı: " + c.yol : (c.hata || "");
  };
}

/* ---------- fiyat cekimi ---------- */
let cekZaman = null;

async function cekBaslat(kapsam, onay) {
  if (!confirm(onay)) return;
  el("#cekBaslat").disabled = el("#cekFavori").disabled = true;
  const r = await (await fetch("/api/cekim", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({kapsam: kapsam})
  })).json();
  if (r.hata) {
    alert(r.hata);
    el("#cekBaslat").disabled = el("#cekFavori").disabled = false;
    return;
  }
  cekIzle();
}

el("#cekBaslat").onclick = () => cekBaslat("hepsi",
  "Tüm sepet çekilecek, 13–15 dakika sürer. Başlatılsın mı?");

el("#cekFavori").onclick = () => {
  if (!favori.length) {
    alert("Henüz favoriniz yok. Arama sonuçlarında ürünün yanındaki ☆ işaretine tıklayın.");
    return;
  }
  cekBaslat("favori",
    `${favori.length} favori ürünün fiyatı güncellenecek. Genellikle 1–3 dakika sürer. Başlatılsın mı?`);
};

async function cekIzle() {
  const d = await (await fetch("/api/cekim")).json();
  const log = el("#cekLog");
  log.textContent = (d.satirlar || []).join("\n");
  log.scrollTop = log.scrollHeight;

  if (d.calisiyor) {
    el("#cekBaslat").disabled = el("#cekFavori").disabled = true;
    el("#cekBaslat").textContent = `Çekiliyor… (${d.toplam_satir} satır)`;
    clearTimeout(cekZaman);
    cekZaman = setTimeout(cekIzle, 2000);
    return;
  }

  el("#cekBaslat").disabled = el("#cekFavori").disabled = false;
  el("#cekBaslat").textContent = "Tüm sepeti çek (13–15 dk)";
  if (d.bitti) {
    await durum();
    if (!d.hata) log.textContent += "\n\nBitti. Sayfayı yenilemenize gerek yok.";
  }
}

(async () => {
  await durum();
  liste = await (await fetch("/api/liste")).json();
  favori = await (await fetch("/api/favori")).json();
  cizListe();
  el("#favBilgi").textContent = favori.length
    ? `${favori.length} favori ürün kayıtlı.`
    : "Henüz favori yok — arama sonuçlarındaki ☆ ile ekleyin.";
  // Sunucu yeniden baslatildiysa ya da baska sekmeden cekim baslatildiysa yakala
  const d = await (await fetch("/api/cekim")).json();
  if (d.calisiyor) cekIzle();
})();
</script></body></html>"""


# ---------------------------------------------------------------------------
# Sunucu
# ---------------------------------------------------------------------------

class Sunucu(BaseHTTPRequestHandler):
    depo: Depo = None  # main() dolduruyor

    def log_message(self, bicim, *args):  # sessiz calis
        pass

    def _gonder(self, veri, tur="application/json", kod=200) -> None:
        if tur == "application/json":
            govde = json.dumps(veri, ensure_ascii=False).encode("utf-8")
        else:
            govde = veri.encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", f"{tur}; charset=utf-8")
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def _govde_oku(self):
        uzunluk = int(self.headers.get("Content-Length") or 0)
        if not uzunluk:
            return None
        try:
            return json.loads(self.rfile.read(uzunluk).decode("utf-8"))
        except ValueError:
            return None

    def do_GET(self) -> None:
        parca = urlparse(self.path)

        if parca.path == "/":
            self._gonder(SAYFA, "text/html")

        elif parca.path == "/api/durum":
            self._gonder({
                "tarih": self.depo.tarih,
                "urun_sayisi": len(self.depo.urunler),
                "sube_sayisi": self.depo.sube_sayisi,
                "damga": self.depo.damga,
            })

        elif parca.path == "/api/ara":
            sorgu = (parse_qs(parca.query).get("q") or [""])[0]
            sonuc = [{
                "urun_id": u["urun_id"], "baslik": u["baslik"], "gramaj": u["gramaj"],
                "grup": u["grup"], "market_sayisi": u["market_sayisi"],
                "en_ucuz": u["en_ucuz"], "fark": u["fark"],
            } for u in self.depo.ara(sorgu)]
            self._gonder(sonuc)

        elif parca.path == "/api/liste":
            self._gonder(liste_oku())

        elif parca.path == "/api/cekim":
            self._gonder(ILERLEME.durum())

        elif parca.path == "/api/favori":
            self._gonder(favori_oku())

        else:
            self._gonder({"hata": "bulunamadi"}, kod=404)

    def do_POST(self) -> None:
        parca = urlparse(self.path)
        veri = self._govde_oku()

        if parca.path == "/api/liste":
            liste_yaz(veri if isinstance(veri, list) else [])
            self._gonder({"tamam": True})

        elif parca.path == "/api/favori":
            favori_yaz([str(x) for x in veri] if isinstance(veri, list) else [])
            self._gonder({"tamam": True})

        elif parca.path == "/api/cekim":
            kapsam = (veri or {}).get("kapsam", "hepsi")
            self._gonder(cekimi_baslat(self.depo,
                                       "favori" if kapsam == "favori" else "hepsi"))

        elif parca.path in ("/api/hesapla", "/api/html"):
            veri = veri or {}
            kalemler = veri.get("kalemler") or []
            maks = max(1, min(6, int(veri.get("maks_market") or rapor.MAKS_MARKET)))
            sonuc = hesapla(self.depo, kalemler, maks)

            if parca.path == "/api/hesapla":
                self._gonder(sonucu_ozetle(sonuc))
                return

            if sonuc.get("hata"):
                self._gonder({"hata": sonuc["hata"]})
                return

            gruplar = rapor.karsilastirma_gruplari(self.depo.teklifler)
            icerik = rapor.html_uret(self.depo.tarih, sonuc, gruplar,
                                     self.depo.sube_sayisi, maks)
            yol = rapor.cikti_yolu()
            yol.write_text(icerik, encoding="utf-8")
            self._gonder({"yol": str(yol)})

        else:
            self._gonder({"hata": "bulunamadi"}, kod=404)


def main() -> None:
    depo = Depo()
    if not depo.tarih:
        yaz("Veritabaninda fiyat yok. Once calistirin:  py topla.py")
        return

    Sunucu.depo = depo
    sunucu = ThreadingHTTPServer((ADRES, KAPI), Sunucu)
    adres = f"http://{ADRES}:{KAPI}"

    yaz(f"{len(depo.urunler)} urun, {depo.sube_sayisi} sube, fiyat tarihi {depo.tarih}")
    yaz(f"Arayuz hazir:  {adres}")
    yaz("Kapatmak icin Ctrl+C")

    # --tarayicisiz: disaridan (orn. onizleme paneli) baslatilirken
    # fazladan bir tarayici penceresi acilmasin.
    if "--tarayicisiz" not in sys.argv:
        try:
            webbrowser.open(adres)
        except Exception:
            pass

    try:
        sunucu.serve_forever()
    except KeyboardInterrupt:
        yaz("\nKapatiliyor.")
        sunucu.shutdown()


if __name__ == "__main__":
    main()
