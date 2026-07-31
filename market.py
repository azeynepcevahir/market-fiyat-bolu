# -*- coding: utf-8 -*-
"""
market.py -- Bolu merkez market fiyat karsilastirma sisteminin cekirdegi.

Icerik:
  * API istemcisi   : marketfiyati.org.tr (nazik hiz sinirli, yeniden denemeli)
  * Normalizasyon   : gramaj ayristirma + birim fiyat hesabi
  * Veritabani      : SQLite sema ve yazma yardimcilari

Sadece Python standart kutuphanesi kullanir. pip ile kurulum GEREKMEZ.
"""

from __future__ import annotations

import json
import re
import sqlite3
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------------------

PROJE = Path(__file__).resolve().parent
DB_YOLU = PROJE / "fiyatlar.db"
SEPET_YOLU = PROJE / "sepet.txt"
BEYAZ_LISTE_YOLU = PROJE / "beyaz_liste.txt"

# Bolu merkez (Belediye Meydani civari)
BOLU_LAT = 40.7350
BOLU_LON = 31.6080
YARICAP_KM = 15

API = "https://api.marketfiyati.org.tr/api/v2"

# Sunucuyu yormamak icin. Bu degerleri DUSURMEYIN -- gelistirme sirasinda
# hizli ard arda istek atinca WAF tarafindan engellendik.
ISTEK_ARASI_SN = 2.0
DENEME_SAYISI = 3
GERI_CEKILME_SN = 8.0

SAYFA_BOYU = 24
# Anahtar kelime basina cekilecek en fazla sayfa. Yukseltmek TOKEN HARCAMAZ,
# sadece cekim suresini uzatir (sayfa basina ~2 sn). Sonuclar bittiginde
# zaten erken durulur, o yuzden yuksek tutmanin cezasi yok.
MAKS_SAYFA = 12  # ~288 urun/kelime

TARAYICI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def yaz(*parcalar) -> None:
    """Turkce karakterleri Windows konsolunda bozmadan yazar."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(*parcalar, flush=True)


# ---------------------------------------------------------------------------
# API istemcisi
# ---------------------------------------------------------------------------

_son_istek = [0.0]


class ApiHatasi(Exception):
    pass


def _istek(yol: str, govde: dict) -> object:
    """API'ye POST atar. Hiz sinirlar, hata halinde geri cekilerek tekrar dener."""
    url = f"{API}/{yol}"
    ham = json.dumps(govde, ensure_ascii=False).encode("utf-8")

    son_hata: Exception | None = None
    for deneme in range(1, DENEME_SAYISI + 1):
        bekle = ISTEK_ARASI_SN - (time.monotonic() - _son_istek[0])
        if bekle > 0:
            time.sleep(bekle)

        req = urllib.request.Request(
            url,
            data=ham,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": TARAYICI_UA,
                "Origin": "https://marketfiyati.org.tr",
                "Referer": "https://marketfiyati.org.tr/",
            },
        )
        try:
            baglam = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=30, context=baglam) as cevap:
                _son_istek[0] = time.monotonic()
                return json.loads(cevap.read().decode("utf-8"))
        except Exception as hata:  # noqa: BLE001 -- ag hatalarinin hepsini yut
            _son_istek[0] = time.monotonic()
            son_hata = hata
            if deneme < DENEME_SAYISI:
                sure = GERI_CEKILME_SN * deneme
                yaz(f"    ! istek basarisiz ({hata}); {sure:.0f} sn bekleyip tekrar denenecek")
                time.sleep(sure)

    raise ApiHatasi(f"{yol} istegi {DENEME_SAYISI} denemede basarisiz: {son_hata}")


def subeleri_getir() -> list[dict]:
    """Bolu merkeze en yakin market subelerini dondurur."""
    veri = _istek(
        "nearest",
        {"latitude": BOLU_LAT, "longitude": BOLU_LON, "distance": YARICAP_KM},
    )
    if not isinstance(veri, list):
        raise ApiHatasi("nearest beklenmeyen cevap dondurdu")
    return veri


def urun_ara(kelime: str, depo_kimlikleri: list[str], ana_kategori: str | None,
             sayfa: int = 0) -> dict:
    """Verilen subelerde, istege bagli kategori filtresiyle urun arar."""
    govde: dict = {
        "keywords": kelime,
        "depots": depo_kimlikleri,
        "pages": sayfa,
        "size": SAYFA_BOYU,
    }
    if ana_kategori:
        govde["main_category"] = [ana_kategori]
    veri = _istek("search", govde)
    return veri if isinstance(veri, dict) else {}


# ---------------------------------------------------------------------------
# Normalizasyon
# ---------------------------------------------------------------------------

# Ham birim -> (taban birim, carpan)
_BIRIMLER = {
    "kg": ("kg", 1.0), "kilogram": ("kg", 1.0), "kilo": ("kg", 1.0),
    "gr": ("kg", 0.001), "g": ("kg", 0.001), "gram": ("kg", 0.001),
    "lt": ("lt", 1.0), "l": ("lt", 1.0), "litre": ("lt", 1.0),
    "ml": ("lt", 0.001), "mililitre": ("lt", 0.001), "cl": ("lt", 0.01),
    "adet": ("adet", 1.0), "ad": ("adet", 1.0), "tane": ("adet", 1.0),
}

_RE_MIKTAR = re.compile(r"([\d]+(?:[.,][\d]+)?)\s*([A-Za-zİIŞĞÜÖÇışğüöç]+)")
_RE_COKLU = re.compile(
    r"(\d+)\s*[xX*]\s*([\d]+(?:[.,][\d]+)?)\s*(ml|gr|g|lt|l|kg|cl)\b", re.IGNORECASE
)
_RE_LI = re.compile(r"(\d+)\s*['’]?\s*(?:li|lı|lu|lü)\b", re.IGNORECASE)
_RE_ADET = re.compile(r"(\d+)\s*adet\b", re.IGNORECASE)


def _sayi(metin: str) -> float | None:
    try:
        return float(metin.replace(",", "."))
    except ValueError:
        return None


def _birim_coz(sayi_metni: str, birim_metni: str) -> tuple[float, str] | None:
    deger = _sayi(sayi_metni)
    if deger is None or deger <= 0:
        return None
    anahtar = kucult(birim_metni)
    if anahtar not in _BIRIMLER:
        return None
    taban, carpan = _BIRIMLER[anahtar]
    return deger * carpan, taban


def coz_miktar(baslik: str, ham_gramaj: str | None,
               kategori: str | None = None) -> tuple[float, str] | None:
    """
    Urun basligi ve API'nin verdigi gramajdan (miktar, taban_birim) uretir.
    Taban birimler: kg, lt, adet.  Cozulemezse None doner.
    """
    baslik = baslik or ""

    # Yumurtada adet fiyati anlamlidir; "72 GR" gibi tekil agirliklar yaniltir.
    yumurta = (kategori or "").strip().lower() == "yumurta"

    if yumurta:
        for kalip in (_RE_ADET, _RE_LI):
            eslesme = kalip.search(baslik)
            if eslesme:
                sayi = _sayi(eslesme.group(1))
                if sayi:
                    return sayi, "adet"

    # "5 x 200 ml" gibi coklu paketler
    eslesme = _RE_COKLU.search(baslik)
    if eslesme:
        adet = _sayi(eslesme.group(1))
        tekil = _birim_coz(eslesme.group(2), eslesme.group(3))
        if adet and tekil:
            return tekil[0] * adet, tekil[1]

    # API'nin verdigi gramaj (en guvenilir kaynak)
    if ham_gramaj:
        eslesme = _RE_MIKTAR.search(ham_gramaj)
        if eslesme:
            sonuc = _birim_coz(eslesme.group(1), eslesme.group(2))
            if sonuc:
                return sonuc

    # "12'li" / "30 Adet"
    for kalip in (_RE_ADET, _RE_LI):
        eslesme = kalip.search(baslik)
        if eslesme:
            sayi = _sayi(eslesme.group(1))
            if sayi:
                return sayi, "adet"

    # Son care: basliktaki ilk miktar ifadesi
    for eslesme in _RE_MIKTAR.finditer(baslik):
        sonuc = _birim_coz(eslesme.group(1), eslesme.group(2))
        if sonuc:
            return sonuc

    return None


_TR_KUCUK = str.maketrans("IİĞÜŞÖÇ", "iiğüşöç")


def kucult(metin: str) -> str:
    """Turkce'ye uygun kucuk harfe cevirme (I -> i, İ -> i)."""
    return (metin or "").translate(_TR_KUCUK).lower()


_RE_TEMIZ = re.compile(r"[^\w\s]", re.UNICODE)


def isim_belirteci(baslik: str, marka: str | None) -> str:
    """
    Urun basligini karsilastirma anahtarina cevirir.

    Marka ve miktar ifadeleri atilir, kalan kelimeler alfabetik siralanir.
    "Yerli" gibi ayirt edici kelimeler KORUNUR -- cunku BIM'de
    "Saban Kirmizi Mercimek 1 Kg" 46 TL iken "Saban Yerli Kirmizi Mercimek 1 Kg"
    89,5 TL; bunlar ayni urun degildir.
    """
    metin = kucult(baslik)
    if marka:
        for parca in kucult(marka).split():
            metin = re.sub(rf"\b{re.escape(parca)}\b", " ", metin)

    metin = _RE_MIKTAR.sub(" ", metin)
    metin = _RE_TEMIZ.sub(" ", metin)

    atilacak = {"gr", "kg", "lt", "ml", "cl", "adet", "li", "lı", "lu", "lü",
                "boy", "paket", "pk", "x"}
    kelimeler = sorted({k for k in metin.split() if k and k not in atilacak and len(k) > 1})
    return " ".join(kelimeler)


# NFKD "ı" harfini ayristirmaz (birlesik isareti yoktur), o yuzden elle katliyoruz.
# Bunsuz alisveris.txt'e "salatalik" yazinca "salatalık" ile eslesmez.
_TR_DUZ = str.maketrans("ıİIğĞüÜşŞöÖçÇ", "iiigguussoocc")


def sadelestir(metin: str) -> str:
    """Turkce harf farklarini eleyen kaba karsilastirma metni ('salatalık' -> 'salatalik')."""
    duz = (metin or "").translate(_TR_DUZ).lower()
    ayrisik = unicodedata.normalize("NFKD", duz)
    return "".join(k for k in ayrisik if not unicodedata.combining(k))


# ---------------------------------------------------------------------------
# Veritabani
# ---------------------------------------------------------------------------

SEMA = """
CREATE TABLE IF NOT EXISTS sube (
    depo_id    TEXT PRIMARY KEY,
    market     TEXT NOT NULL,
    ad         TEXT,
    enlem      REAL,
    boylam     REAL,
    mesafe_m   REAL
);

CREATE TABLE IF NOT EXISTS urun (
    urun_id        TEXT PRIMARY KEY,
    baslik         TEXT NOT NULL,
    marka          TEXT,
    ana_kategori   TEXT,
    gramaj_ham     TEXT,
    miktar         REAL,
    birim          TEXT,
    isim_anahtari  TEXT,
    arama_kelimesi TEXT,
    grup           TEXT
);

CREATE TABLE IF NOT EXISTS fiyat (
    tarih       TEXT NOT NULL,
    urun_id     TEXT NOT NULL,
    depo_id     TEXT NOT NULL,
    market      TEXT NOT NULL,
    fiyat       REAL NOT NULL,
    birim_fiyat REAL,
    indirim     INTEGER DEFAULT 0,
    promosyon   TEXT,
    -- API'nin bildirdigi son guncelleme damgasi ("29.07.2026 09:27").
    -- Fiyatin ne kadar taze oldugunu bundan anlariz.
    guncelleme  TEXT,
    PRIMARY KEY (tarih, urun_id, depo_id)
);

-- Bir urun birden fazla arama kelimesiyle bulunabilir ("Soke Un 5 Kg" hem
-- "un" hem "irmik" aramasinda cikiyor). Bunu urun tablosunda tek sutunda
-- tutmak, sonraki kelimenin oncekini ezmesine ve o kalemin raporda
-- "bulunamadi" gorunmesine yol aciyordu. Iliskiyi ayri tabloda tutuyoruz.
CREATE TABLE IF NOT EXISTS urun_kelime (
    urun_id TEXT NOT NULL,
    kelime  TEXT NOT NULL,
    grup    TEXT,
    PRIMARY KEY (urun_id, kelime)
);

-- Tum katalog taramasinda hangi kelimelerin islendigi. Tarama saatler
-- surebildigi icin yarida kesilirse kaldigi yerden devam etsin diye tutulur.
CREATE TABLE IF NOT EXISTS tarama (
    kelime      TEXT PRIMARY KEY,
    tarih       TEXT,
    urun_sayisi INTEGER
);

-- Elle girilen fiyatlar (File, Ozdilek gibi API'de olmayan marketler).
--
-- Ayri tabloda tutuluyor cunku gunluk cekim 'fiyat' tablosunu tarihe gore
-- yeniler; elle girilen fiyat oradaysa ertesi gun kaybolurdu. Burada
-- urun+market basina TEK kayit durur ve her raporda tasinir. 'tarih'
-- kacinci gun girildigini soyler, boylece eskiyen fiyatlar isaretlenebilir.
CREATE TABLE IF NOT EXISTS elle_fiyat (
    urun_id TEXT NOT NULL,
    market  TEXT NOT NULL,
    fiyat   REAL NOT NULL,
    tarih   TEXT NOT NULL,
    PRIMARY KEY (urun_id, market)
);

-- ISTATISTIK ---------------------------------------------------------
--
-- Ham 'fiyat' tablosu gunde ~16.600 satir buyuyor (~7 MB). Yil sonunda
-- 2,5 GB olurdu. O yuzden ham veri 45 gunle sinirlanip uzun vadeli
-- istatistik su iki kucuk tabloda tutuluyor:
--
--   gunluk_endeks : grup+market basina gunluk medyan birim fiyat
--                   (~55 grup x 8 market = gunde ~440 satir)
--   takip_fiyat   : favori urunlerin gunluk fiyati, tam degeriyle
--                   (~30 urun x 8 market = gunde ~240 satir)
--
-- Boylece "su kategori bu ay ne kadar zamlandi" ve "aldigim urunun fiyati
-- nasil degisti" sorulari yillar sonra bile cevaplanabilir.

CREATE TABLE IF NOT EXISTS gunluk_endeks (
    tarih        TEXT NOT NULL,
    market       TEXT NOT NULL,
    grup         TEXT NOT NULL,
    urun_sayisi  INTEGER,
    medyan_birim REAL,
    ortalama     REAL,
    PRIMARY KEY (tarih, market, grup)
);

CREATE TABLE IF NOT EXISTS takip_fiyat (
    tarih   TEXT NOT NULL,
    urun_id TEXT NOT NULL,
    market  TEXT NOT NULL,
    fiyat   REAL NOT NULL,
    PRIMARY KEY (tarih, urun_id, market)
);

CREATE INDEX IF NOT EXISTS idx_endeks_tarih ON gunluk_endeks (tarih);
CREATE INDEX IF NOT EXISTS idx_takip_urun   ON takip_fiyat (urun_id);
CREATE INDEX IF NOT EXISTS idx_kelime ON urun_kelime (kelime);
CREATE INDEX IF NOT EXISTS idx_fiyat_tarih ON fiyat (tarih);
CREATE INDEX IF NOT EXISTS idx_fiyat_urun  ON fiyat (urun_id);
CREATE INDEX IF NOT EXISTS idx_urun_grup   ON urun (grup);
"""


def veritabani(yol: Path = DB_YOLU) -> sqlite3.Connection:
    baglanti = sqlite3.connect(yol)
    baglanti.row_factory = sqlite3.Row
    baglanti.executescript(SEMA)
    _sutunlari_tamamla(baglanti)
    return baglanti


def _sutunlari_tamamla(baglanti: sqlite3.Connection) -> None:
    """
    Eski veritabanlarina sonradan eklenen sutunlari ekler.
    CREATE TABLE IF NOT EXISTS mevcut tabloyu degistirmez, o yuzden gerekli.
    """
    eklenecek = {
        "fiyat": [("guncelleme", "TEXT")],
        # Urun fotografinin adresi. Resimler indirilmiyor, sadece adresleri
        # saklaniyor -- 19 bin resmi sayfaya gommek ~100 MB ederdi.
        "urun": [("resim", "TEXT")],
    }
    for tablo, sutunlar in eklenecek.items():
        mevcut = {s["name"] for s in baglanti.execute(f"PRAGMA table_info({tablo})")}
        for ad, tur in sutunlar:
            if ad not in mevcut:
                baglanti.execute(f"ALTER TABLE {tablo} ADD COLUMN {ad} {tur}")
    baglanti.commit()


def subeleri_yaz(baglanti: sqlite3.Connection, subeler: list[dict]) -> int:
    satirlar = []
    for s in subeler:
        konum = s.get("location") or {}
        satirlar.append((
            s.get("id"),
            s.get("marketName"),
            s.get("sellerName"),
            konum.get("lat"),
            konum.get("lon"),
            s.get("distance"),
        ))
    baglanti.executemany(
        "INSERT OR REPLACE INTO sube (depo_id, market, ad, enlem, boylam, mesafe_m) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        satirlar,
    )
    baglanti.commit()
    return len(satirlar)


def urun_ve_fiyat_yaz(baglanti: sqlite3.Connection, urunler: list[dict],
                      arama_kelimesi: str, grup: str,
                      bugun: str | None = None) -> tuple[int, int]:
    """API'den gelen urun listesini normalize edip veritabanina yazar."""
    bugun = bugun or date.today().isoformat()
    urun_satirlari, fiyat_satirlari = [], []

    for urun in urunler:
        urun_id = urun.get("id")
        baslik = urun.get("baslik") or urun.get("title") or ""
        if not urun_id or not baslik:
            continue

        marka = urun.get("brand")
        kategori = urun.get("main_category")
        ham_gramaj = urun.get("refinedVolumeOrWeight")

        cozum = coz_miktar(baslik, ham_gramaj, kategori)
        miktar, birim = cozum if cozum else (None, None)

        # Tum katalog taramasinda sabit bir grup adi yok; her urun kendi
        # ana kategorisine yazilir ki arayuzdeki grup suzgeci anlamli kalsin.
        urun_grubu = grup or kategori or "Diğer"

        urun_satirlari.append((
            urun_id, baslik, marka, kategori, ham_gramaj,
            miktar, birim, isim_belirteci(baslik, marka), arama_kelimesi, urun_grubu,
            (urun.get("imageUrl") or "").strip() or None,
        ))

        for teklif in urun.get("productDepotInfoList") or []:
            fiyat = teklif.get("price")
            if fiyat is None:
                continue
            # Birim fiyati KENDIMIZ hesapliyoruz; API'nin unitPrice alani
            # bazen adet bazen kilo uzerinden geliyor ve tutarsiz.
            birim_fiyat = (fiyat / miktar) if (miktar and miktar > 0) else None
            fiyat_satirlari.append((
                bugun, urun_id, teklif.get("depotId"), teklif.get("marketAdi"),
                float(fiyat), birim_fiyat,
                1 if teklif.get("discount") else 0,
                teklif.get("promotionText"),
                teklif.get("indexTime"),
            ))

    baglanti.executemany(
        "INSERT OR REPLACE INTO urun (urun_id, baslik, marka, ana_kategori, gramaj_ham, "
        "miktar, birim, isim_anahtari, arama_kelimesi, grup, resim) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        urun_satirlari,
    )
    baglanti.executemany(
        "INSERT OR REPLACE INTO urun_kelime (urun_id, kelime, grup) VALUES (?, ?, ?)",
        [(s[0], arama_kelimesi, s[9]) for s in urun_satirlari],
    )
    baglanti.executemany(
        "INSERT OR REPLACE INTO fiyat (tarih, urun_id, depo_id, market, fiyat, "
        "birim_fiyat, indirim, promosyon, guncelleme) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        fiyat_satirlari,
    )
    baglanti.commit()
    return len(urun_satirlari), len(fiyat_satirlari)


# ---------------------------------------------------------------------------
# Sepet ve beyaz liste dosyalari
# ---------------------------------------------------------------------------

def sepet_oku(yol: Path = SEPET_YOLU) -> list[tuple[str, str, list[str]]]:
    """
    sepet.txt bicimi:
        grup adi | API ana kategorisi | kelime1, kelime2, ...
    '#' ile baslayan satirlar ve bos satirlar yok sayilir.
    """
    if not yol.exists():
        raise FileNotFoundError(f"{yol} bulunamadi")

    kayitlar = []
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#"):
            continue
        parcalar = [p.strip() for p in satir.split("|")]
        if len(parcalar) != 3:
            yaz(f"  ! sepet.txt satiri atlandi (3 alan bekleniyor): {satir}")
            continue
        grup, kategori, kelimeler = parcalar
        kelime_listesi = [k.strip() for k in kelimeler.split(",") if k.strip()]
        if kelime_listesi:
            kayitlar.append((grup, kategori or "", kelime_listesi))
    return kayitlar


def beyaz_liste_oku(yol: Path = BEYAZ_LISTE_YOLU) -> set[str]:
    """Onaylanmis hipoalerjenik urun kimliklerini dondurur."""
    if not yol.exists():
        return set()
    onayli = set()
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#"):
            continue
        onayli.add(satir.split("|")[0].strip())
    return onayli


# Temizlik / kisisel bakim urunleri icin onay listesi.
#
# Kapali (False): butun urunler digerleri gibi listelenir.
# Acik  (True) : sadece beyaz_liste.txt'te onayladiginiz urunler gorunur.
#
# Bu ozellik hipoalerjenik urunler icin eklenmisti: "hipoalerjenik" bilgisi
# API verisinde guvenilir degil (Bolu'da bu kelimenin gectigi sadece 3 urun
# var; gercekte uygun olanlar "bebek", "sensitive", "parfumsuz" gibi farkli
# kelimelerle etiketli). Kullanici istegi uzerine kapatildi -- artik temizlik
# urunleri de listeleniyor, uygunlugunu etiketten kendiniz kontrol edersiniz.
BEYAZ_LISTE_ZORUNLU = False


def beyaz_liste_gerekir(ana_kategori: str | None) -> bool:
    """Bu kategorideki urunler onay listesine tabi mi?"""
    if not BEYAZ_LISTE_ZORUNLU:
        return False
    metin = sadelestir(ana_kategori or "")
    return any(ipucu in metin for ipucu in
               ("temizlik", "bakim", "sabun", "banyo", "deterjan", "hijyen"))


# Basliginda bunlar gecen urunler, onay listesinde basa alinir ve
# yildizla isaretlenir. ELEME degil, sadece siralama amacli.
HASSAS_IPUCLARI = (
    "hipoalerjenik", "hypoallergenic", "sensitive", "hassas", "bebek",
    "parfumsuz", "kokusuz", "dermatolojik", "alerjen", "renklendirici icermez",
    "baby", "nemlendirici",
)


def hassas_ipucu_var(baslik: str) -> bool:
    metin = sadelestir(baslik or "")
    return any(ipucu in metin for ipucu in HASSAS_IPUCLARI)


# Ham fiyat kayitlarinin saklanma suresi. Bu suredem eskiler silinir;
# uzun vadeli istatistik gunluk_endeks ve takip_fiyat tablolarinda kalir.
HAM_VERI_GUN = 45


def istatistik_isle(baglanti: sqlite3.Connection, tarih: str,
                    takip_edilen: list[str] | None = None) -> dict:
    """
    O gunun fiyatlarindan gunluk ozetleri uretir ve eski ham veriyi budar.

    Her cekimin sonunda calisir. Ayni gun icin tekrar calisirsa ozet
    yeniden hesaplanir (INSERT OR REPLACE), mukerrer kayit olusmaz.
    """
    # --- grup + market bazinda medyan birim fiyat ---
    satirlar = baglanti.execute(
        """
        SELECT f.market AS market, u.grup AS grup, f.birim_fiyat AS bf
        FROM fiyat f JOIN urun u ON u.urun_id = f.urun_id
        WHERE f.tarih = ? AND f.birim_fiyat IS NOT NULL AND u.grup IS NOT NULL
        """,
        (tarih,),
    ).fetchall()

    kovalar: dict[tuple[str, str], list[float]] = {}
    for s in satirlar:
        kovalar.setdefault((s["market"], s["grup"]), []).append(s["bf"])

    endeks = []
    for (market_kodu, grup), degerler in kovalar.items():
        degerler.sort()
        orta = len(degerler) // 2
        medyan = (degerler[orta] if len(degerler) % 2
                  else (degerler[orta - 1] + degerler[orta]) / 2)
        endeks.append((tarih, market_kodu, grup, len(degerler), medyan,
                       sum(degerler) / len(degerler)))

    baglanti.executemany(
        "INSERT OR REPLACE INTO gunluk_endeks "
        "(tarih, market, grup, urun_sayisi, medyan_birim, ortalama) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        endeks,
    )

    # --- takip edilen (favori) urunlerin tam fiyati ---
    takip = 0
    if takip_edilen:
        yer = ",".join("?" * len(takip_edilen))
        kayitlar = baglanti.execute(
            f"""
            SELECT urun_id, market, MIN(fiyat) AS fiyat
            FROM fiyat WHERE tarih = ? AND urun_id IN ({yer})
            GROUP BY urun_id, market
            """,
            [tarih, *takip_edilen],
        ).fetchall()
        baglanti.executemany(
            "INSERT OR REPLACE INTO takip_fiyat (tarih, urun_id, market, fiyat) "
            "VALUES (?, ?, ?, ?)",
            [(tarih, k["urun_id"], k["market"], k["fiyat"]) for k in kayitlar],
        )
        takip = len(kayitlar)

    # --- eski ham veriyi buda ---
    silinen = baglanti.execute(
        "DELETE FROM fiyat WHERE tarih < date(?, ?)",
        (tarih, f"-{HAM_VERI_GUN} days"),
    ).rowcount

    baglanti.commit()
    return {"endeks": len(endeks), "takip": takip, "silinen": silinen}


ELLE_MARKET_YOLU = PROJE / "elle_marketler.txt"

# Dosya yoksa ya da bozuksa kullanilacak varsayilanlar
_ELLE_VARSAYILAN = {
    "file": "File", "ozdilek": "Özdilek",
    "nuhmar": "Nuhmar", "basgimpa": "Başgimpa", "diger": "Diğer",
}


def elle_marketleri_oku(yol: Path = ELLE_MARKET_YOLU) -> dict[str, str]:
    """
    marketfiyati'de olmayan, fiyati elle girilen marketlerin listesi.
    Kullanici dosyadan duzenleyebilsin diye sabit kodlanmadi.
    """
    if not yol.exists():
        return dict(_ELLE_VARSAYILAN)

    marketler: dict[str, str] = {}
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "|" not in satir:
            continue
        kod, _, ad = satir.partition("|")
        kod, ad = kod.strip().lower(), ad.strip()
        if kod and ad:
            marketler[kod] = ad
    return marketler or dict(_ELLE_VARSAYILAN)


# Geriye donuk uyumluluk icin: modul yuklenirken bir kez okunur
ELLE_MARKETLER = elle_marketleri_oku()


def elle_urun_ekle(baglanti: sqlite3.Connection, baslik: str, marka: str,
                   gramaj: str, grup: str = "Elle eklenen") -> str:
    """
    Katalogda olmayan bir urunu (orn. File'a ozel marka) sisteme tanitir.
    Gramaj, API'den gelen urunlerle ayni ayristiriciyla cozulur ki
    karsilastirma kurallari birebir ayni sekilde islesin.
    """
    baslik = (baslik or "").strip()
    if not baslik:
        raise ValueError("Ürün adı boş olamaz")

    marka = (marka or "").strip()
    gramaj = (gramaj or "").strip()

    cozum = coz_miktar(baslik, gramaj or None, grup)
    miktar, birim = cozum if cozum else (None, None)

    # Ayni urunu iki kez eklemeyi onlemek icin icerikten turetilen kimlik
    imza = f"{kucult(marka)}|{isim_belirteci(baslik, marka)}|{miktar}|{birim}"
    urun_id = "elle-" + str(abs(hash(imza)) % (10 ** 10))

    baglanti.execute(
        "INSERT OR REPLACE INTO urun (urun_id, baslik, marka, ana_kategori, "
        "gramaj_ham, miktar, birim, isim_anahtari, arama_kelimesi, grup) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (urun_id, baslik, marka or None, grup, gramaj or None, miktar, birim,
         isim_belirteci(baslik, marka), kucult(baslik).split()[0] if baslik else "", grup),
    )
    baglanti.commit()
    return urun_id


def elle_fiyat_yaz(baglanti: sqlite3.Connection, urun_id: str, market: str,
                   fiyat: float, tarih: str | None = None) -> None:
    baglanti.execute(
        "INSERT OR REPLACE INTO elle_fiyat (urun_id, market, fiyat, tarih) "
        "VALUES (?, ?, ?, ?)",
        (urun_id, market, float(fiyat), tarih or date.today().isoformat()),
    )
    baglanti.commit()


ELLE_YEDEK_YOLU = PROJE / "elle_fiyatlar.json"


def elle_disa_aktar(baglanti: sqlite3.Connection) -> int:
    """
    Elle girilen fiyatlari depoya girebilen bir dosyaya yazar.

    Veritabani (.gitignore'da) GitHub'a gitmiyor ve Actions her calistiginda
    sifirdan basliyor. Bu dosya olmasa elle girdiginiz File/Ozdilek fiyatlari
    yayindaki sayfada gorunmezdi. Kucuk bir JSON oldugu icin depoyu sismez.
    """
    satirlar = baglanti.execute(
        """
        SELECT e.urun_id, e.market, e.fiyat, e.tarih,
               u.baslik, u.marka, u.gramaj_ham, u.grup
        FROM elle_fiyat e JOIN urun u ON u.urun_id = e.urun_id
        ORDER BY e.urun_id, e.market
        """
    ).fetchall()

    kayitlar = [{
        "urun_id": s["urun_id"], "market": s["market"], "fiyat": s["fiyat"],
        "tarih": s["tarih"], "baslik": s["baslik"], "marka": s["marka"] or "",
        "gramaj": s["gramaj_ham"] or "", "grup": s["grup"] or "",
    } for s in satirlar]

    ELLE_YEDEK_YOLU.write_text(
        json.dumps(kayitlar, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return len(kayitlar)


def elle_ice_aktar(baglanti: sqlite3.Connection) -> int:
    """
    elle_fiyatlar.json'daki kayitlari veritabanina yazar.

    Katalogda olmayan urunler (File'a ozel markalar) burada yeniden
    olusturulur; boylece bos bir veritabaniyla baslayan GitHub Actions
    calistirmasi da elle girilen fiyatlari icerir.
    """
    if not ELLE_YEDEK_YOLU.exists():
        return 0
    try:
        kayitlar = json.loads(ELLE_YEDEK_YOLU.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return 0
    if not isinstance(kayitlar, list):
        return 0

    # Dosya, elle girilen fiyatlarin TEK dogru kaynagidir. Actions artik
    # veritabanini onbellekte sakladigi icin, burada silinen bir fiyat
    # dosyadan cikmis olsa bile onbellekteki kayitta kalirdi. O yuzden
    # dosyada olmayanlari temizliyoruz.
    gecerli = {(k.get("urun_id"), k.get("market") or "diger") for k in kayitlar}
    for satir in baglanti.execute("SELECT urun_id, market FROM elle_fiyat").fetchall():
        if (satir["urun_id"], satir["market"]) not in gecerli:
            baglanti.execute(
                "DELETE FROM elle_fiyat WHERE urun_id = ? AND market = ?",
                (satir["urun_id"], satir["market"]),
            )

    sayi = 0
    for k in kayitlar:
        urun_id = k.get("urun_id")
        if not urun_id or k.get("fiyat") is None:
            continue

        var = baglanti.execute(
            "SELECT 1 FROM urun WHERE urun_id = ?", (urun_id,)
        ).fetchone()
        if not var:
            # Sadece elle eklenmis urun -- tanimini yedekten geri kur
            baslik = k.get("baslik") or urun_id
            marka = k.get("marka") or ""
            gramaj = k.get("gramaj") or ""
            grup = k.get("grup") or "Elle eklenen"
            cozum = coz_miktar(baslik, gramaj or None, grup)
            miktar, birim = cozum if cozum else (None, None)
            baglanti.execute(
                "INSERT OR REPLACE INTO urun (urun_id, baslik, marka, ana_kategori, "
                "gramaj_ham, miktar, birim, isim_anahtari, arama_kelimesi, grup) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (urun_id, baslik, marka or None, grup, gramaj or None, miktar, birim,
                 isim_belirteci(baslik, marka),
                 kucult(baslik).split()[0] if baslik else "", grup),
            )

        baglanti.execute(
            "INSERT OR REPLACE INTO elle_fiyat (urun_id, market, fiyat, tarih) "
            "VALUES (?, ?, ?, ?)",
            (urun_id, k.get("market") or "diger", float(k["fiyat"]),
             k.get("tarih") or date.today().isoformat()),
        )
        sayi += 1

    baglanti.commit()
    return sayi


def elle_fiyat_sil(baglanti: sqlite3.Connection, urun_id: str, market: str) -> None:
    baglanti.execute(
        "DELETE FROM elle_fiyat WHERE urun_id = ? AND market = ?", (urun_id, market)
    )
    baglanti.commit()


def onedrive_koku() -> Path | None:
    """Proje dizininden yukari cikarak OneDrive kok klasorunu bulur."""
    for ust in PROJE.parents:
        if ust.name.lower().startswith("onedrive"):
            return ust
    return None
