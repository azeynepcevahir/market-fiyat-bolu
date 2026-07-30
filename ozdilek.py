# -*- coding: utf-8 -*-
"""
ozdilek.py -- Ozdilek Bolu magazasinin fiyatlarini ceker.

Ozdilek marketfiyati.org.tr'de yok; ama ozdilekteyim.com'un arkasindaki
SAP Commerce (Spartacus) REST API'si herkese acik ve magaza bazli calisiyor.
Bolu magazasinin anahtari "market-bolu-store" -- fiyatlar gercekten magazaya
gore degisiyor (ornegin karpuz Bolu'da 9,99, Bursa Gecit'te 11,95).

Cekilen urunler dogrudan ana katalogla ayni tablolara yazilir; marka + isim +
gramaj ayni oldugunda karsilastirma gruplari kendiliginden birlesir.

Kullanim:
    py ozdilek.py                tam katalogu ceker (~9.966 urun, ~4 dk)
    py ozdilek.py --sinir 500    ilk 500 urun (deneme icin)

Sadece Python standart kutuphanesi kullanir.
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

import market
from market import yaz

API = "https://api.ozdilekteyim.com/rest/v2"
MAGAZA = "market-bolu-store"      # Bolu magazasi; Bursa icin market-gecit-store
MARKET_KODU = "ozdilek"
DEPO = "ozdilek-bolu"

SAYFA_BOYU = 100
ISTEK_ARASI_SN = 1.5              # ticari bir site; nazik davraniyoruz
DENEME = 3

TARAYICI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_son_istek = [0.0]


def _istek(yol: str) -> dict:
    url = f"{API}/{MAGAZA}/{yol}"
    son_hata = None
    for deneme in range(1, DENEME + 1):
        bekle = ISTEK_ARASI_SN - (time.monotonic() - _son_istek[0])
        if bekle > 0:
            time.sleep(bekle)
        istek = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": TARAYICI_UA,
            "Referer": "https://www.ozdilekteyim.com/market",
        })
        try:
            with urllib.request.urlopen(istek, timeout=30,
                                        context=ssl.create_default_context()) as c:
                _son_istek[0] = time.monotonic()
                return json.loads(c.read().decode("utf-8"))
        except Exception as hata:      # noqa: BLE001
            _son_istek[0] = time.monotonic()
            son_hata = hata
            if deneme < DENEME:
                time.sleep(5 * deneme)
    raise RuntimeError(f"Ozdilek API hatasi: {son_hata}")


# "Elma Yesil Kg" gibi isimlerde miktar yok, sadece birim var. Gramaj
# cozulemezse birim fiyat hesaplanamaz ve urun karsilastirmaya giremez.
_RE_SAYILI = re.compile(r"\d\s*(kg|gr?|lt|l|ml|cl|adet)\b", re.IGNORECASE)


def _isim_duzelt(ad: str) -> str:
    if _RE_SAYILI.search(ad or ""):
        return ad
    if re.search(r"\bkg\.?\b", ad, re.IGNORECASE):
        return re.sub(r"\bkg\.?\b", "1 Kg", ad, count=1, flags=re.IGNORECASE)
    if re.search(r"\badet\.?\b", ad, re.IGNORECASE):
        return re.sub(r"\badet\.?\b", "1 Adet", ad, count=1, flags=re.IGNORECASE)
    return ad


def cek(istek_siniri: int | None = None) -> dict:
    baglanti = market.veritabani()
    bugun = date.today().isoformat()

    # Ozdilek'i sube tablosuna tek kayit olarak ekle (zincir basina tek kayit)
    baglanti.execute(
        "INSERT OR REPLACE INTO sube (depo_id, market, ad, enlem, boylam, mesafe_m) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (DEPO, MARKET_KODU, "Özdilek Bolu", None, None, None),
    )
    baglanti.commit()

    sayfa = 0
    toplam = 0
    yazilan = 0
    gramajsiz = 0

    while True:
        if istek_siniri and yazilan >= istek_siniri:
            break

        sorgu = urllib.parse.urlencode({
            "query": "", "pageSize": SAYFA_BOYU, "currentPage": sayfa,
            "fields": "FULL", "lang": "tr", "curr": "TRY",
        })
        veri = _istek(f"products/search?{sorgu}")
        urunler = veri.get("products") or []
        sayfalama = veri.get("pagination") or {}
        toplam = sayfalama.get("totalResults", 0)
        if not urunler:
            break

        urun_satirlari, fiyat_satirlari, kelime_satirlari = [], [], []
        for u in urunler:
            kod = u.get("code")
            ad = (u.get("name") or "").strip()
            fiyat = (u.get("price") or {}).get("value")
            if not kod or not ad or fiyat is None:
                continue

            marka = (u.get("brand") or "").strip() or None
            kategoriler = u.get("categories") or []
            grup = (kategoriler[0].get("name") if kategoriler else None) or "Özdilek"

            duzeltilmis = _isim_duzelt(ad)
            cozum = market.coz_miktar(duzeltilmis, None, grup)
            miktar, birim = cozum if cozum else (None, None)
            if miktar is None:
                gramajsiz += 1

            urun_id = f"ozdilek-{kod}"
            urun_satirlari.append((
                urun_id, ad, marka, grup, None, miktar, birim,
                market.isim_belirteci(duzeltilmis, marka),
                market.kucult(ad).split()[0] if ad else "", grup,
            ))
            kelime_satirlari.append((urun_id, market.kucult(ad).split()[0] if ad else "", grup))
            fiyat_satirlari.append((
                bugun, urun_id, DEPO, MARKET_KODU, float(fiyat),
                (float(fiyat) / miktar) if miktar else None,
                1 if u.get("hasDiscount") else 0,
                None, f"{bugun} (özdilek)",
            ))

        baglanti.executemany(
            "INSERT OR REPLACE INTO urun (urun_id, baslik, marka, ana_kategori, "
            "gramaj_ham, miktar, birim, isim_anahtari, arama_kelimesi, grup) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", urun_satirlari)
        baglanti.executemany(
            "INSERT OR REPLACE INTO urun_kelime (urun_id, kelime, grup) VALUES (?, ?, ?)",
            kelime_satirlari)
        baglanti.executemany(
            "INSERT OR REPLACE INTO fiyat (tarih, urun_id, depo_id, market, fiyat, "
            "birim_fiyat, indirim, promosyon, guncelleme) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", fiyat_satirlari)
        baglanti.commit()

        yazilan += len(urun_satirlari)
        yaz(f"  sayfa {sayfa + 1}/{sayfalama.get('totalPages', '?')}  "
            f"{yazilan}/{toplam} urun")

        sayfa += 1
        if sayfa >= (sayfalama.get("totalPages") or 0):
            break

    baglanti.close()
    return {"toplam": toplam, "yazilan": yazilan, "gramajsiz": gramajsiz}


def main() -> None:
    sinir = None
    if "--sinir" in sys.argv:
        try:
            sinir = int(sys.argv[sys.argv.index("--sinir") + 1])
        except (IndexError, ValueError):
            yaz("--sinir sonrasi bir sayi bekleniyor.")
            return

    yaz(f"Ozdilek Bolu magazasi cekiliyor ({MAGAZA})...")
    sonuc = cek(sinir)
    yaz(f"\n{sonuc['yazilan']} urun yazildi (magazada toplam {sonuc['toplam']}).")
    if sonuc["gramajsiz"]:
        yaz(f"{sonuc['gramajsiz']} urunun gramaji cozulemedi; bunlar birim fiyat "
            f"karsilastirmasina giremez ama listede gorunur.")
    yaz("\nSayfayi uretmek icin:  py katalog.py")


if __name__ == "__main__":
    main()
