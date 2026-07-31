# -*- coding: utf-8 -*-
"""
rapor.py -- karsilastirma tablosu + "hangi urun hangi markette" dagitimi.

Kullanim:
    py rapor.py                 son cekimden rapor uretir
    py rapor.py --market 3      en fazla 3 markete ugra (varsayilan 2)
    py rapor.py --yol           HTML dosyasinin nereye yazildigini soyler

Cikti:
    * terminal ozeti
    * OneDrive/Alisveris/Alisveris-Listesi.html  (telefondan acilir)
"""

from __future__ import annotations

import html
import sys
from collections import defaultdict
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path

import market
from market import yaz

# ---------------------------------------------------------------------------
# Karar parametreleri -- burayi kendinize gore ayarlayin
# ---------------------------------------------------------------------------

# Bir markete ugramanin size maliyeti (yakit + zaman + "madem geldim" alimi).
# Bu sayiyi yukseltirseniz sistem sizi daha az markete gonderir.
ZIYARET_MALIYETI = 25.0

# En fazla kac markete ugramaya razisiniz.
MAKS_MARKET = 2

# Secilen market kombinasyonu, listenizin en az bu kadarini karsilamali.
MIN_KAPSAM = 0.80

# Bir market o gun cekilemezse (site coktu, ag kesildi, is atlandi) elimizdeki
# son fiyati kullaniriz -- ama kac gunluk oldugunu her yerde soyleyerek.
# Bunsuz, tek bir basarisiz cekim o marketi listeden tamamen dusuruyordu.
GECMIS_GUN = 7

MARKET_ADLARI = {
    "bim": "BİM", "sok": "ŞOK", "a101": "A101", "migros": "Migros",
    "carrefour": "CarrefourSA", "tarim_kredi": "Tarım Kredi", "hakmar": "Hakmar",
    # marketfiyati'de yok, kendi sitelerinden otomatik cekiliyor
    "ozdilek": "Özdilek",           # py ozdilek.py
    "bizimtoptan": "Bizim Toptan",  # py bizimtoptan.py
}


def market_adi(kod: str) -> str:
    """API marketleri + elle_marketler.txt'te tanimli olanlar."""
    if kod in MARKET_ADLARI:
        return MARKET_ADLARI[kod]
    return market.elle_marketleri_oku().get(kod, (kod or "?").title())


def para(deger: float | None) -> str:
    if deger is None:
        return "-"
    metin = f"{deger:,.2f}"
    return metin.replace(",", "\x00").replace(".", ",").replace("\x00", ".") + " TL"


def birim_metni(deger: float | None, birim: str | None) -> str:
    if deger is None or not birim:
        return "-"
    return f"{para(deger)}/{birim}"


# ---------------------------------------------------------------------------
# Veri yukleme
# ---------------------------------------------------------------------------

def son_tarih(baglanti) -> str | None:
    satir = baglanti.execute("SELECT MAX(tarih) AS t FROM fiyat").fetchone()
    return satir["t"] if satir else None


def teklifleri_yukle(baglanti, tarih: str, gecmis_gun: int = GECMIS_GUN) -> list[dict]:
    """
    Tekliflerin duz listesi: her (urun, market) icifin ELDEKI EN YENI fiyat,
    en fazla `gecmis_gun` gun geriye bakarak.

    Neden pencere: bir market o gun cekilemedigginde (ag kesintisi, sitenin
    coktugu bir gun) o marketin fiyati tamamen kayboluyordu -- kullanici
    marketin listede olmadigini goruyor, neden olmadigini bilmiyordu.
    Simdi dunku fiyat gosteriliyor, ama 'yas_gun' ile isaretli; arayuz
    kac gunluk oldugunu yaziyor.

    Beyaz liste gerektiren kategorilerde, onaylanmamis urunler ELENIR.
    """
    onayli = market.beyaz_liste_oku()

    baslangic = (date.fromisoformat(tarih) - timedelta(days=max(0, gecmis_gun))).isoformat()

    # Once her (urun, market) icin en yeni tarihi bul, sonra sadece o
    # satirlari cek. Pencereyi Python'da suzmek 100 bin satiri bosuna
    # tasirdi; bu haliyle is SQLite'ta kaliyor.
    baglanti.execute("DROP TABLE IF EXISTS temp.son_fiyat")
    baglanti.execute(
        """
        CREATE TEMP TABLE son_fiyat AS
        SELECT urun_id, market, MAX(tarih) AS tarih
        FROM fiyat WHERE tarih BETWEEN ? AND ?
        GROUP BY urun_id, market
        """,
        (baslangic, tarih),
    )
    baglanti.execute(
        "CREATE INDEX temp.son_fiyat_ix ON son_fiyat(urun_id, market, tarih)"
    )

    satirlar = baglanti.execute(
        """
        SELECT u.urun_id, u.baslik, u.marka, u.ana_kategori, u.gramaj_ham,
               u.miktar, u.birim, u.isim_anahtari, u.arama_kelimesi, u.grup, u.resim,
               f.market, f.fiyat, f.birim_fiyat, f.indirim, f.promosyon, f.guncelleme,
               f.tarih
        FROM fiyat f
        JOIN son_fiyat s ON s.urun_id = f.urun_id AND s.market = f.market
                        AND s.tarih = f.tarih
        JOIN urun u ON u.urun_id = f.urun_id
        """
    ).fetchall()
    baglanti.execute("DROP TABLE IF EXISTS temp.son_fiyat")

    bugun = date.fromisoformat(tarih)

    # Bir urunun TUM arama kelimeleri (urun tablosundaki tek sutun yetmiyor,
    # cunku ayni urun birden fazla kelimeyle bulunabiliyor).
    kelimeler: dict[str, set[str]] = defaultdict(set)
    for satir in baglanti.execute("SELECT urun_id, kelime FROM urun_kelime"):
        kelimeler[satir["urun_id"]].add(satir["kelime"])

    teklifler = []
    for s in satirlar:
        if market.beyaz_liste_gerekir(s["ana_kategori"]) and s["urun_id"] not in onayli:
            continue
        t = dict(s)
        t["kelimeler"] = kelimeler.get(s["urun_id"]) or (
            {s["arama_kelimesi"]} if s["arama_kelimesi"] else set()
        )
        try:
            t["yas_gun"] = (bugun - date.fromisoformat(s["tarih"])).days
        except (ValueError, TypeError):
            t["yas_gun"] = 0
        teklifler.append(t)

    teklifler.extend(_elle_teklifleri(baglanti, tarih))
    return teklifler


def _elle_teklifleri(baglanti, tarih: str) -> list[dict]:
    """
    Elle girilen fiyatlari (File, Ozdilek) teklif listesine katar.

    Bunlar gunluk cekimden bagimsiz durur; her raporda tasinirlar.
    Kac gun once girildikleri 'yas_gun' alaninda tasinir ki eskiyenler
    arayuzde isaretlenebilsin.
    """
    # Depoyla birlikte gelen yedegi her seferinde iceri al; boylece bos
    # veritabaniyla baslayan GitHub Actions calistirmasi da elle girilen
    # fiyatlari icerir.
    market.elle_ice_aktar(baglanti)

    bugun = date.fromisoformat(tarih)
    satirlar = baglanti.execute(
        """
        SELECT e.urun_id, e.market, e.fiyat, e.tarih,
               u.baslik, u.marka, u.ana_kategori, u.gramaj_ham,
               u.miktar, u.birim, u.isim_anahtari, u.arama_kelimesi, u.grup
        FROM elle_fiyat e
        JOIN urun u ON u.urun_id = e.urun_id
        """
    ).fetchall()

    teklifler = []
    for s in satirlar:
        try:
            yas = (bugun - date.fromisoformat(s["tarih"])).days
        except ValueError:
            yas = 0
        miktar = s["miktar"]
        teklifler.append({
            "urun_id": s["urun_id"], "baslik": s["baslik"], "marka": s["marka"],
            "ana_kategori": s["ana_kategori"], "gramaj_ham": s["gramaj_ham"],
            "miktar": miktar, "birim": s["birim"],
            "isim_anahtari": s["isim_anahtari"], "arama_kelimesi": s["arama_kelimesi"],
            "grup": s["grup"], "market": s["market"], "fiyat": s["fiyat"],
            "birim_fiyat": (s["fiyat"] / miktar) if miktar else None,
            "indirim": 0, "promosyon": None,
            "guncelleme": f"{s['tarih']} (elle)",
            "kelimeler": {s["arama_kelimesi"]} if s["arama_kelimesi"] else set(),
            "elle": True, "yas_gun": yas,
        })
    return teklifler


def market_bazinda_enucuz(teklifler: list[dict]) -> dict[tuple, dict]:
    """Ayni urun bir markette birden fazla subede olabilir; en ucuzunu tutar."""
    en_iyi: dict[tuple, dict] = {}
    for t in teklifler:
        anahtar = (t["urun_id"], t["market"])
        mevcut = en_iyi.get(anahtar)
        if mevcut is None or t["fiyat"] < mevcut["fiyat"]:
            en_iyi[anahtar] = t
    return en_iyi


# ---------------------------------------------------------------------------
# Karsilastirma gruplari (ayni marka + ayni gramaj)
# ---------------------------------------------------------------------------

def grup_anahtari(t: dict):
    """
    Bir teklifin karsilastirma grubu: ayni marka + ayni normalize isim +
    ayni gramaj. Miktar cozulemediyse urun kendi basina bir gruptur.
    """
    if not t["miktar"] or not t["birim"]:
        return ("urun", t["urun_id"])
    return (
        market.kucult(t["marka"] or ""),
        t["isim_anahtari"],
        round(float(t["miktar"]), 4),
        t["birim"],
    )


def urun_secenekleri(urun_id: str, teklifler: list[dict]) -> tuple[dict, list]:
    """
    Secilen urunun grubundaki (ayni marka, ayni gramaj) tekliflerin
    market bazinda en ucuzlari. Kullanicinin tikladigi urun ne ise
    karsilastirma tam olarak onun uzerinden yapilir.
    """
    hedef = next((t for t in teklifler if t["urun_id"] == urun_id), None)
    if hedef is None:
        return {}, []

    anahtar = grup_anahtari(hedef)
    secenekler: dict[str, dict] = {}
    for t in teklifler:
        if grup_anahtari(t) != anahtar:
            continue
        mevcut = secenekler.get(t["market"])
        if mevcut is None or t["fiyat"] < mevcut["fiyat"]:
            secenekler[t["market"]] = t
    return secenekler, []


def karsilastirma_gruplari(teklifler: list[dict]) -> list[dict]:
    """
    Marka, normalize isim, miktar ve birim birebir ayni olan urunleri
    tek grup sayar. En az 2 farkli markette bulunanlar dondurulur.
    """
    kovalar: dict[tuple, dict[str, dict]] = defaultdict(dict)

    for t in market_bazinda_enucuz(teklifler).values():
        if not t["miktar"] or not t["birim"]:
            continue
        anahtar = grup_anahtari(t)
        mevcut = kovalar[anahtar].get(t["market"])
        if mevcut is None or t["fiyat"] < mevcut["fiyat"]:
            kovalar[anahtar][t["market"]] = t

    gruplar = []
    for anahtar, market_teklifleri in kovalar.items():
        if len(market_teklifleri) < 2:
            continue
        sirali = sorted(market_teklifleri.values(), key=lambda t: t["fiyat"])
        ucuz, pahali = sirali[0], sirali[-1]
        gruplar.append({
            "baslik": ucuz["baslik"],
            "marka": ucuz["marka"],
            "gramaj": ucuz["gramaj_ham"] or f"{ucuz['miktar']:g} {ucuz['birim']}",
            "grup": ucuz["grup"],
            "birim": ucuz["birim"],
            "teklifler": sirali,
            "fark": pahali["fiyat"] - ucuz["fiyat"],
            "oran": ((pahali["fiyat"] - ucuz["fiyat"]) / pahali["fiyat"]
                     if pahali["fiyat"] else 0.0),
        })

    gruplar.sort(key=lambda g: g["fark"], reverse=True)
    return gruplar


# ---------------------------------------------------------------------------
# Alisveris listesi ve market dagitimi
# ---------------------------------------------------------------------------

def alisveris_oku(yol: Path | None = None) -> list[dict]:
    yol = yol or (market.PROJE / "alisveris.txt")
    if not yol.exists():
        return []

    kalemler = []
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#"):
            continue

        istenen: list[str] = []
        istenmeyen: list[str] = []
        if ">" in satir:
            satir, filtreler = (p.strip() for p in satir.split(">", 1))
            for parca in filtreler.split(","):
                parca = parca.strip()
                if not parca:
                    continue
                if parca.startswith("!"):
                    istenmeyen.append(parca[1:].strip())
                else:
                    istenen.append(parca)

        adet = 1
        bas, ayirac, son = satir.rpartition(" ")
        if ayirac and len(son) > 1 and son[0] in "xX" and son[1:].isdigit():
            adet = int(son[1:])
            satir = bas.strip()

        if satir:
            kalemler.append({
                "kelime": satir, "istenen": istenen,
                "istenmeyen": istenmeyen, "adet": adet,
            })
    return kalemler


def kalem_secenekleri(kalem: dict, teklifler: list[dict]) -> dict[str, dict]:
    """
    Bir alisveris kalemi icin her markette en iyi secenegi bulur.

    "En iyi" = en dusuk BIRIM fiyat. Boylece 250 gr'lik pahali paket yerine
    gercekten avantajli olan boy secilir. Optimizasyonda ise o urunun
    gercek etiket fiyati kullanilir.
    """
    # Kelime bazli eslestirme: "zeytin" yazdiginizda sepetteki
    # "siyah zeytin" / "yesil zeytin" kelimelerinin ikisi de tutar.
    # Kelime butunlugu arandigi icin "zeytin" -> "zeytinyagi" TUTMAZ,
    # ki zeytinyagi ayri bir kalem olarak kalsin.
    aranan = set(market.sadelestir(kalem["kelime"]).split())
    istenen = [market.sadelestir(k) for k in kalem["istenen"]]
    istenmeyen = [market.sadelestir(k) for k in kalem["istenmeyen"]]

    def kelime_uyar(t: dict) -> bool:
        return any(aranan <= set(market.sadelestir(k).split())
                   for k in (t.get("kelimeler") or ()))

    adaylar = []
    for t in teklifler:
        if not aranan or not kelime_uyar(t):
            continue
        baslik = market.sadelestir(t["baslik"])
        if istenen and not any(k in baslik for k in istenen):
            continue
        if any(k in baslik for k in istenmeyen):
            continue
        adaylar.append(t)

    def sira(t: dict) -> float:
        return t["birim_fiyat"] if t["birim_fiyat"] is not None else t["fiyat"]

    secenekler: dict[str, dict] = {}
    for t in adaylar:
        mevcut = secenekler.get(t["market"])
        if mevcut is None or sira(t) < sira(mevcut):
            secenekler[t["market"]] = t

    # Farkli cesitler (Golden elma / Starking elma gibi) -- raporda
    # alternatif olarak gosterilir ki yanlis cesit secildiginde fark edin.
    cesitler: list[dict] = []
    gorulen: set[str] = set()
    for t in sorted(adaylar, key=sira):
        anahtar = t["isim_anahtari"] or t["baslik"]
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        cesitler.append(t)
        if len(cesitler) >= 4:
            break

    return secenekler, cesitler


def dagitimi_coz(kalemler: list[dict], maks_market: int) -> dict:
    """
    Hangi markete ugranacagini ve her kalemin nereden alinacagini secer.

    Bu bir "tesis yerlesim" problemi: her kalemi en ucuzdan almak sizi
    6 markete gonderir ve yakit + zaman tasarrufu yer. Onun yerine
    ziyaret basina sabit maliyet ekleyip toplam gideri minimize ediyoruz.
    Market sayisi az oldugu icin tum alt kumeleri deneyip kesin en iyiyi
    buluyoruz -- yaklasik cozum degil.
    """
    kapsanan = [k for k in kalemler if k["secenekler"]]
    if not kapsanan:
        return {"hata": "Listedeki hicbir kalem icin fiyat bulunamadi."}

    marketler = sorted({m for k in kapsanan for m in k["secenekler"]})

    def kalem_tutari(kalem: dict, secim: dict) -> float:
        return secim["fiyat"] * kalem["adet"]

    genel_enucuz = {
        id(k): min((kalem_tutari(k, s) for s in k["secenekler"].values()))
        for k in kapsanan
    }

    en_iyi = None       # genel en iyi plan
    en_iyi_tek = None   # tek markete gidilseydi en iyisi (AYNI kurallarla)
    yedek = None        # kapsam esigini hicbir plan gecemezse kullanilir

    for boyut in range(1, min(maks_market, len(marketler)) + 1):
        for alt_kume in combinations(marketler, boyut):
            atamalar, eksikler = [], []
            toplam = 0.0

            for kalem in kapsanan:
                uygun = [(m, s) for m, s in kalem["secenekler"].items() if m in alt_kume]
                if not uygun:
                    eksikler.append(kalem)
                    toplam += genel_enucuz[id(kalem)]
                    continue
                secilen_market, secim = min(uygun, key=lambda p: kalem_tutari(kalem, p[1]))
                tutar = kalem_tutari(kalem, secim)
                toplam += tutar
                atamalar.append({
                    "kalem": kalem, "market": secilen_market,
                    "teklif": secim, "tutar": tutar,
                })

            kapsam = len(atamalar) / len(kapsanan)
            maliyet = toplam + boyut * ZIYARET_MALIYETI
            aday = {
                "marketler": list(alt_kume), "atamalar": atamalar,
                "eksikler": eksikler, "sepet": toplam, "maliyet": maliyet,
                "kapsam": kapsam,
            }

            if yedek is None or (kapsam, -maliyet) > (yedek["kapsam"], -yedek["maliyet"]):
                yedek = aday

            # Kapsam esigini gecemeyen planlar yarismaya girmez. Bu kural
            # TEK marketlik planlara da aynen uygulanir -- aksi halde
            # "tek market daha ucuz" diye yaniltici bir kiyas cikiyordu.
            if kapsam < MIN_KAPSAM:
                continue

            if en_iyi is None or maliyet < en_iyi["maliyet"]:
                en_iyi = aday
            if boyut == 1 and (en_iyi_tek is None or maliyet < en_iyi_tek["maliyet"]):
                en_iyi_tek = aday

    if en_iyi is None:
        en_iyi = yedek
        en_iyi["kapsam_uyarisi"] = True

    en_iyi["tek_market"] = en_iyi_tek
    en_iyi["tasarruf"] = (en_iyi_tek["maliyet"] - en_iyi["maliyet"]) if en_iyi_tek else None
    en_iyi["bulunamayan"] = [k for k in kalemler if not k["secenekler"]]
    en_iyi["kalem_sayisi"] = len(kapsanan)
    return en_iyi


# ---------------------------------------------------------------------------
# HTML cikti
# ---------------------------------------------------------------------------

STIL = """
*{box-sizing:border-box}
body{margin:0;padding:16px;font-family:-apple-system,'Segoe UI',Roboto,sans-serif;
     background:#f6f7f9;color:#14181f;line-height:1.5}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:16px;margin:28px 0 10px;padding-bottom:6px;border-bottom:2px solid #d9dee6}
h3{font-size:14px;margin:0 0 8px}
.ust{color:#5a6472;font-size:13px;margin-bottom:18px}
.ozet{background:#fff;border:1px solid #d9dee6;border-radius:10px;padding:14px;margin-bottom:8px}
.ozet .buyuk{font-size:26px;font-weight:700;color:#0b7a3b}
.ozet .kotu{color:#5a6472;text-decoration:line-through}
.kartlar{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.kart{background:#fff;border:1px solid #d9dee6;border-radius:10px;overflow:hidden}
.kart header{background:#14181f;color:#fff;padding:10px 12px;font-weight:600;
             display:flex;justify-content:space-between;align-items:center}
.kart header .adet{font-weight:400;font-size:12px;opacity:.75}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:7px 10px;text-align:left;border-bottom:1px solid #eceff3;vertical-align:top}
th{background:#f0f2f5;font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:#5a6472}
tr:last-child td{border-bottom:none}
td.sag,th.sag{text-align:right;white-space:nowrap}
.ucuz{color:#0b7a3b;font-weight:600}
.kucuk{font-size:11px;color:#7b8494}
.rozet{display:inline-block;padding:1px 6px;border-radius:99px;font-size:11px;
       background:#e8f5ed;color:#0b7a3b;font-weight:600}
.uyari{background:#fff8e6;border:1px solid #f0d68a;border-radius:10px;padding:12px;
       margin:14px 0;font-size:13px}
details{background:#fff;border:1px solid #d9dee6;border-radius:10px;margin-bottom:10px}
summary{padding:11px 14px;cursor:pointer;font-weight:600;font-size:14px}
details table{border-top:1px solid #eceff3}
.dip{margin-top:28px;font-size:12px;color:#7b8494;text-align:center}
@media(max-width:520px){body{padding:10px}td,th{padding:6px 8px}}
@media print{body{background:#fff}details{break-inside:avoid}summary{display:none}
             details[open] table{display:table}}
"""


def _kacir(metin) -> str:
    return html.escape(str(metin if metin is not None else ""))


def html_uret(tarih: str, sonuc: dict, gruplar: list[dict],
              sube_sayisi: int, maks_market: int) -> str:
    p: list[str] = []
    ekle = p.append

    ekle(f"<!doctype html><html lang='tr'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Alışveriş Listesi {_kacir(tarih)}</title><style>{STIL}</style></head><body>")

    ekle(f"<h1>Bolu Merkez Alışveriş Listesi</h1>")
    ekle(f"<div class='ust'>Fiyat tarihi: <b>{_kacir(tarih)}</b> &middot; "
         f"{sube_sayisi} şube taranmış &middot; en fazla {maks_market} markete uğrama</div>")

    if sonuc.get("hata"):
        ekle(f"<div class='uyari'>{_kacir(sonuc['hata'])}</div>")
    else:
        tek = sonuc.get("tek_market")
        tasarruf = sonuc.get("tasarruf")
        ekle("<div class='ozet'>")
        if tek is None:
            ekle(f"<div class='buyuk'>{_kacir(para(sonuc['maliyet']))}</div>")
            ekle("<div class='kucuk'>Tek markete gidilse listenin çok büyük kısmı "
                 "eksik kalırdı, o yüzden kıyaslama yapılmadı.</div>")
        elif tasarruf and tasarruf > 0.5:
            ekle(f"<div class='buyuk'>{_kacir(para(tasarruf))} tasarruf</div>")
            ekle(f"<div class='kucuk'>Tek markete "
                 f"({_kacir(market_adi(tek['marketler'][0]))}) gitseydiniz "
                 f"<span class='kotu'>{_kacir(para(tek['maliyet']))}</span> &rarr; "
                 f"bu dağılımla <b>{_kacir(para(sonuc['maliyet']))}</b> "
                 f"(ziyaret maliyeti dahil, {_kacir(para(ZIYARET_MALIYETI))}/market)</div>")
        else:
            ekle(f"<div class='buyuk'>Tek markete gidin: "
                 f"{_kacir(market_adi(sonuc['marketler'][0]))}</div>")
            ekle("<div class='kucuk'>Bu hafta market gezmek yakıt ve zamana değmiyor. "
                 "Sistemin dürüst cevabı bu.</div>")
        ekle(f"<div class='kucuk' style='margin-top:6px'>Sepet tutarı "
             f"{_kacir(para(sonuc['sepet']))} &middot; "
             f"{len(sonuc['atamalar'])}/{sonuc.get('kalem_sayisi', 0)} kalem karşılandı</div>")
        if sonuc.get("kapsam_uyarisi"):
            ekle("<div class='kucuk' style='margin-top:6px;color:#a8710a'>Hiçbir market "
                 "kombinasyonu listenin yeterli kısmını karşılayamadı; en geniş kapsamlı "
                 "plan gösteriliyor.</div>")
        ekle("</div>")

        ekle("<h2>Markete göre liste</h2><div class='kartlar'>")
        markete_gore: dict[str, list[dict]] = defaultdict(list)
        for atama in sonuc["atamalar"]:
            markete_gore[atama["market"]].append(atama)

        for m in sorted(markete_gore, key=lambda x: -sum(a["tutar"] for a in markete_gore[x])):
            atamalar = sorted(markete_gore[m], key=lambda a: a["kalem"]["kelime"])
            ara_toplam = sum(a["tutar"] for a in atamalar)
            ekle(f"<div class='kart'><header><span>{_kacir(market_adi(m))}</span>"
                 f"<span class='adet'>{len(atamalar)} kalem &middot; "
                 f"{_kacir(para(ara_toplam))}</span></header><table>")
            for a in atamalar:
                t, kalem = a["teklif"], a["kalem"]
                carpan = f" &times;{kalem['adet']}" if kalem["adet"] > 1 else ""
                ekle(f"<tr><td>{_kacir(t['baslik'])}{carpan}"
                     f"<div class='kucuk'>{_kacir(kalem['kelime'])} &middot; "
                     f"{_kacir(birim_metni(t['birim_fiyat'], t['birim']))}</div>")

                digerleri = [c for c in kalem.get("cesitler", [])
                             if (c["isim_anahtari"] or c["baslik"])
                             != (t["isim_anahtari"] or t["baslik"])][:2]
                if digerleri:
                    parcalar = " &middot; ".join(
                        f"{_kacir(c['baslik'][:34])} "
                        f"({_kacir(market_adi(c['market']))} {_kacir(para(c['fiyat']))})"
                        for c in digerleri
                    )
                    ekle(f"<div class='kucuk' style='margin-top:3px;color:#9aa3b1'>"
                         f"diğer çeşit: {parcalar}</div>")

                ekle(f"</td><td class='sag ucuz'>{_kacir(para(a['tutar']))}</td></tr>")
            ekle("</table></div>")
        ekle("</div>")

        if sonuc.get("eksikler") or sonuc.get("bulunamayan"):
            ekle("<div class='uyari'><b>Bu listede yok:</b><br>")
            for k in sonuc.get("eksikler", []):
                ekle(f"&bull; {_kacir(k['kelime'])} &mdash; seçilen marketlerde yok, "
                     f"başka yerden alınacak<br>")
            for k in sonuc.get("bulunamayan", []):
                ekle(f"&bull; {_kacir(k['kelime'])} &mdash; hiçbir markette fiyat "
                     f"bulunamadı (yazım hatası olabilir)<br>")
            ekle("</div>")

    # ---- Karsilastirma tablosu ----
    ekle("<h2>Karşılaştırma tablosu</h2>")
    ekle("<div class='kucuk' style='margin-bottom:10px'>Aynı marka ve aynı gramajda, "
         "en az iki markette bulunan ürünler. Fark büyükten küçüğe sıralı.</div>")

    gruba_gore: dict[str, list[dict]] = defaultdict(list)
    for g in gruplar:
        gruba_gore[g["grup"] or "Diğer"].append(g)

    for grup_adi in sorted(gruba_gore, key=lambda a: -len(gruba_gore[a])):
        satirlar = gruba_gore[grup_adi][:40]
        ekle(f"<details><summary>{_kacir(grup_adi)} "
             f"<span class='kucuk'>({len(gruba_gore[grup_adi])} karşılaştırılabilir ürün)</span>"
             f"</summary><table><tr><th>Ürün</th><th>Gramaj</th>"
             f"<th class='sag'>En ucuz</th><th class='sag'>En pahalı</th>"
             f"<th class='sag'>Fark</th></tr>")
        for g in satirlar:
            ucuz, pahali = g["teklifler"][0], g["teklifler"][-1]
            ekle(f"<tr><td>{_kacir(g['baslik'])}</td>"
                 f"<td class='kucuk'>{_kacir(g['gramaj'])}</td>"
                 f"<td class='sag'><span class='rozet'>{_kacir(market_adi(ucuz['market']))}</span> "
                 f"<b>{_kacir(para(ucuz['fiyat']))}</b></td>"
                 f"<td class='sag kucuk'>{_kacir(market_adi(pahali['market']))} "
                 f"{_kacir(para(pahali['fiyat']))}</td>"
                 f"<td class='sag ucuz'>{_kacir(para(g['fark']))} "
                 f"<span class='kucuk'>%{g['oran'] * 100:.0f}</span></td></tr>")
        if len(gruba_gore[grup_adi]) > 40:
            ekle(f"<tr><td colspan='5' class='kucuk'>… ve "
                 f"{len(gruba_gore[grup_adi]) - 40} ürün daha</td></tr>")
        ekle("</table></details>")

    ekle(f"<div class='dip'>marketfiyati.org.tr verisiyle üretildi &middot; "
         f"oluşturma: {date.today().isoformat()}<br>"
         f"Fiyatlar mağaza rafından farklı olabilir. Temizlik ve kişisel bakım "
         f"ürünlerinde yalnızca beyaz_liste.txt'te onayladıklarınız gösterilir.</div>")
    ekle("</body></html>")
    return "".join(p)


def cikti_yolu() -> Path:
    kok = market.onedrive_koku()
    klasor = (kok / "Alisveris") if kok else (market.PROJE / "cikti")
    klasor.mkdir(parents=True, exist_ok=True)
    return klasor / "Alisveris-Listesi.html"


# ---------------------------------------------------------------------------

def main() -> None:
    argumanlar = sys.argv[1:]

    if "--yol" in argumanlar:
        yaz(str(cikti_yolu()))
        return

    maks_market = MAKS_MARKET
    if "--market" in argumanlar:
        try:
            maks_market = int(argumanlar[argumanlar.index("--market") + 1])
        except (IndexError, ValueError):
            yaz("--market sonrasi bir sayi bekleniyor. Ornek: py rapor.py --market 3")
            return

    baglanti = market.veritabani()
    tarih = son_tarih(baglanti)
    if not tarih:
        yaz("Veritabaninda fiyat yok. Once calistirin:  py topla.py")
        return

    teklifler = teklifleri_yukle(baglanti, tarih)
    sube_sayisi = baglanti.execute("SELECT COUNT(*) AS n FROM sube").fetchone()["n"]
    yaz(f"Fiyat tarihi {tarih} -- {len(teklifler)} teklif, {sube_sayisi} sube")

    gruplar = karsilastirma_gruplari(teklifler)
    yaz(f"Karsilastirilabilir urun grubu: {len(gruplar)}")

    kalemler = alisveris_oku()
    for kalem in kalemler:
        kalem["secenekler"], kalem["cesitler"] = kalem_secenekleri(kalem, teklifler)

    sonuc = dagitimi_coz(kalemler, maks_market) if kalemler else {
        "hata": "alisveris.txt bos. Market dagitimi icin oraya urun ekleyin."
    }

    # ---- terminal ozeti ----
    if sonuc.get("hata"):
        yaz(f"\n! {sonuc['hata']}")
    else:
        yaz(f"\n{'=' * 58}")
        yaz(f"Ugranacak market: {', '.join(market_adi(m) for m in sonuc['marketler'])}")
        yaz(f"Sepet {para(sonuc['sepet'])}  +  ziyaret "
            f"{para(len(sonuc['marketler']) * ZIYARET_MALIYETI)}"
            f"  =  {para(sonuc['maliyet'])}")
        tek = sonuc.get("tek_market")
        tasarruf = sonuc.get("tasarruf")
        if tek is None:
            yaz("Tek marketle liste tamamlanmiyor, kiyas yapilmadi.")
        elif tasarruf and tasarruf > 0.5:
            yaz(f"Tek market ({market_adi(tek['marketler'][0])}): {para(tek['maliyet'])}"
                f"   ->  tasarruf {para(tasarruf)}")
        else:
            yaz("Tek market yeterli -- gezmeye degmiyor.")
        yaz(f"{'=' * 58}")

        markete_gore: dict[str, list] = defaultdict(list)
        for atama in sonuc["atamalar"]:
            markete_gore[atama["market"]].append(atama)
        for m, atamalar in markete_gore.items():
            yaz(f"\n-- {market_adi(m)} ({len(atamalar)} kalem) --")
            for a in sorted(atamalar, key=lambda x: x["kalem"]["kelime"]):
                yaz(f"   {a['teklif']['baslik'][:46]:<46} {para(a['tutar']):>12}")

        eksikler = sonuc.get("eksikler") or []
        bulunamayan = sonuc.get("bulunamayan") or []
        if eksikler or bulunamayan:
            yaz("\n-- bu listede yok --")
            for k in eksikler:
                yaz(f"   {k['kelime']:<46} secilen marketlerde yok")
            for k in bulunamayan:
                yaz(f"   {k['kelime']:<46} hic fiyat bulunamadi")

    icerik = html_uret(tarih, sonuc, gruplar, sube_sayisi, maks_market)
    yol = cikti_yolu()
    yol.write_text(icerik, encoding="utf-8")

    yaz(f"\nHTML yazildi:\n  {yol}")
    # Tarayiciya yapistirilabilir adres. Sadece klasor adini yazmak
    # (onedrive/...) ise yaramaz -- tarayici onu internet adresi sanar.
    yaz(f"\nTarayiciya yapistirin:\n  {yol.as_uri()}")
    if market.onedrive_koku():
        yaz("\nTelefondan: OneDrive uygulamasi -> Alisveris -> Alisveris-Listesi.html")

    if "--ac" in sys.argv:
        import webbrowser
        webbrowser.open(yol.as_uri())
        yaz("\nTarayicida aciliyor...")

    baglanti.close()


if __name__ == "__main__":
    main()
