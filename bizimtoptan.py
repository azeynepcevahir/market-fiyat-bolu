# -*- coding: utf-8 -*-
"""
bizimtoptan.py -- Bizim Toptan fiyatlarini ceker.

Bizim Toptan marketfiyati.org.tr'de yok. Ozdilek'in aksine bir API'ye
ihtiyac yok: site sunucu tarafinda render ediliyor ve her urun kartinda
"data-enhanced-productclick" niteliginde JSON gomulu geliyor (ad, marka,
kategori, fiyat). Duz HTTP + JSON okumak yeterli.

Bolu Merkez subesi var (Sumer Mah. Alaca Sok. No:27) ama fiyatlar magazaya
gore degismiyor gorunuyor -- toptanci mantigi, ulke geneli tek liste.

TOPTANCI OLDUGU ICIN IKI OZEL DURUM:
  * Coklu paket: "Gofret 36 g 36'li" -> gercek miktar 36 x 36 g = 1296 g.
    Duz ayristirici 36 g okur ve birim fiyati 40 kat sisirirdi.
  * Miktar indirimi: kartlarda "30 Adet uzeri ..." ikinci fiyat var.
    Gomulu JSON'da olmadigi icin kendiliginden eleniyor.

Kullanim:
    py bizimtoptan.py
    py bizimtoptan.py --sinir 300
"""

from __future__ import annotations

import html
import json
import re
import ssl
import sys
import time
import urllib.request
from datetime import date

import market
from market import yaz

KOK = "https://www.bizimtoptan.com.tr"
MARKET_KODU = "bizimtoptan"
DEPO = "bizimtoptan-bolu"

KATEGORILER = [
    "temel-gida", "sivi-yag-margarin", "atistirmalik", "icecek", "dondurma",
    "unlu-mamuller", "sarkuteri-kahvaltilik", "et-urunleri-ve-sarkuteri",
    "bebek-urunleri", "temizlik", "kisisel-bakim", "kazandiran-urunler",
]

ISTEK_ARASI_SN = 2.0
DENEME = 3
MAKS_SAYFA = 40

TARAYICI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_son_istek = [0.0]

# Nitelik ham HTML'de TEK tirnakla yaziliyor: data-...='{"item_id": ...}'
# (Tarayici DOM'unda cift tirnakli gorunuyor, yaniltici.) Iki bicimi de kabul et.
_RE_KART = re.compile(
    r"""data-enhanced-productclick\s*=\s*(?:'([^']+)'|"([^"]+)")""", re.S)

# "36 g 36'li" gibi coklu paketler: birim miktar x paket adedi
_RE_COKLU_PAKET = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|gr?|lt|l|ml|cl)\b[^0-9]{0,12}?(\d+)\s*['’]?\s*l[iıuü]\b",
    re.IGNORECASE,
)


def _istek(yol: str) -> str:
    url = yol if yol.startswith("http") else KOK + yol
    son_hata = None
    for deneme in range(1, DENEME + 1):
        bekle = ISTEK_ARASI_SN - (time.monotonic() - _son_istek[0])
        if bekle > 0:
            time.sleep(bekle)
        istek = urllib.request.Request(url, headers={
            "User-Agent": TARAYICI_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9",
        })
        try:
            with urllib.request.urlopen(istek, timeout=30,
                                        context=ssl.create_default_context()) as c:
                _son_istek[0] = time.monotonic()
                return c.read().decode("utf-8", "replace")
        except Exception as hata:      # noqa: BLE001
            _son_istek[0] = time.monotonic()
            son_hata = hata
            if deneme < DENEME:
                time.sleep(4 * deneme)
    raise RuntimeError(f"Bizim Toptan istegi basarisiz: {son_hata}")


def _sayfadaki_urunler(icerik: str) -> list[dict]:
    """Urun kartlarindaki gomulu JSON'lari cikarir."""
    urunler = []
    for tek, cift in _RE_KART.findall(icerik):
        try:
            veri = json.loads(html.unescape(tek or cift))
        except ValueError:
            continue
        ad = (veri.get("item_name") or "").strip()
        try:
            fiyat = float(str(veri.get("price")).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if not ad or fiyat <= 0:
            continue
        urunler.append({
            "kod": str(veri.get("item_id") or "").strip(),
            "ad": ad,
            "marka": (veri.get("item_brand") or "").strip().title() or None,
            "grup": (veri.get("item_category3") or veri.get("item_category")
                     or "Bizim Toptan").strip(),
            "fiyat": fiyat,
        })
    return urunler


"""
COKLU PAKETLER NEDEN ATLANIYOR
------------------------------
Gomulu JSON'daki "price" alani coklu paketlerde tutarsiz. Ayni gun,
ayni boy uc urun:

    Cappy Karisik Meyve 330 ml 12'li     38,01 TL
    Fuse Tea Mango      330 ml 12'li     45,00 TL
    Fuse Tea Karpuz     330 ml 12'li    480,00 TL

Ilk ikisi paket fiyati olamaz (12 x 330 ml icin cok dusuk); tek adet
fiyati olmalarina ragmen ad "12'li" diyor. Hangisinin ne oldugunu
ayirt edemedigimiz icin bu urunleri hic almiyoruz -- yanlis birim fiyat,
sistemin sizi yanlis markete gondermesi demek olurdu.

Tekli ambalajlarda boyle bir sorun yok (Cokokrem 400 g 109 TL,
makarna 500 g 33,50 TL gibi hepsi tutarli).

--coklu-dahil bayragiyla yine de alinabilir, ama onerilmez.
"""


def _coklu_mu(ad: str) -> bool:
    return bool(_RE_COKLU_PAKET.search(ad or ""))


def _miktar_coz(ad: str, grup: str):
    """
    Coklu paket alinacaksa (--coklu-dahil) gramaji dogru hesaplar:
    "Gofret 36 g 36'li" -> 36 x 36 g = 1.296 kg
    """
    eslesme = _RE_COKLU_PAKET.search(ad)
    if eslesme:
        tekil = market.coz_miktar(f"{eslesme.group(1)} {eslesme.group(2)}", None, grup)
        adet = int(eslesme.group(3))
        if tekil and adet > 1:
            return tekil[0] * adet, tekil[1]
    return market.coz_miktar(ad, None, grup)


def cek(istek_siniri: int | None = None, coklu_dahil: bool = False) -> dict:
    baglanti = market.veritabani()
    bugun = date.today().isoformat()

    baglanti.execute(
        "INSERT OR REPLACE INTO sube (depo_id, market, ad, enlem, boylam, mesafe_m) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (DEPO, MARKET_KODU, "Bizim Toptan Bolu Merkez", None, None, None),
    )
    baglanti.commit()

    gorulen: set[str] = set()
    yazilan = coklu_atlanan = gramajsiz = 0

    for kategori in KATEGORILER:
        if istek_siniri and yazilan >= istek_siniri:
            break
        kategori_sayisi = 0

        for sayfa in range(1, MAKS_SAYFA + 1):
            if istek_siniri and yazilan >= istek_siniri:
                break
            yol = f"/{kategori}" if sayfa == 1 else f"/{kategori}?page={sayfa}"
            try:
                icerik = _istek(yol)
            except RuntimeError as hata:
                yaz(f"  ! {kategori} sayfa {sayfa}: {hata}")
                break

            urunler = _sayfadaki_urunler(icerik)
            yeni = [u for u in urunler if u["kod"] and u["kod"] not in gorulen]
            if not yeni:
                break                      # sayfalar tekrar etmeye basladi

            urun_satirlari, fiyat_satirlari, kelime_satirlari = [], [], []
            for u in yeni:
                gorulen.add(u["kod"])
                if _coklu_mu(u["ad"]) and not coklu_dahil:
                    coklu_atlanan += 1     # fiyat semantigi guvenilmez, yukaridaki nota bak
                    continue
                cozum = _miktar_coz(u["ad"], u["grup"])
                miktar, birim = cozum if cozum else (None, None)
                if miktar is None:
                    gramajsiz += 1

                urun_id = f"bizimtoptan-{u['kod']}"
                ilk_kelime = market.kucult(u["ad"]).split()[0] if u["ad"] else ""
                urun_satirlari.append((
                    urun_id, u["ad"], u["marka"], u["grup"], None, miktar, birim,
                    market.isim_belirteci(u["ad"], u["marka"]), ilk_kelime, u["grup"],
                ))
                kelime_satirlari.append((urun_id, ilk_kelime, u["grup"]))
                fiyat_satirlari.append((
                    bugun, urun_id, DEPO, MARKET_KODU, u["fiyat"],
                    (u["fiyat"] / miktar) if miktar else None,
                    0, None, f"{bugun} (bizim toptan)",
                ))

            baglanti.executemany(
                "INSERT OR REPLACE INTO urun (urun_id, baslik, marka, ana_kategori, "
                "gramaj_ham, miktar, birim, isim_anahtari, arama_kelimesi, grup) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", urun_satirlari)
            baglanti.executemany(
                "INSERT OR REPLACE INTO urun_kelime (urun_id, kelime, grup) "
                "VALUES (?, ?, ?)", kelime_satirlari)
            baglanti.executemany(
                "INSERT OR REPLACE INTO fiyat (tarih, urun_id, depo_id, market, fiyat, "
                "birim_fiyat, indirim, promosyon, guncelleme) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", fiyat_satirlari)
            baglanti.commit()

            yazilan += len(urun_satirlari)
            kategori_sayisi += len(urun_satirlari)

        yaz(f"  {kategori:<28} {kategori_sayisi:4d} urun   (toplam {yazilan})")

    baglanti.close()
    return {"yazilan": yazilan, "coklu_atlanan": coklu_atlanan, "gramajsiz": gramajsiz}


def main() -> None:
    sinir = None
    if "--sinir" in sys.argv:
        try:
            sinir = int(sys.argv[sys.argv.index("--sinir") + 1])
        except (IndexError, ValueError):
            yaz("--sinir sonrasi bir sayi bekleniyor.")
            return

    coklu = "--coklu-dahil" in sys.argv
    yaz("Bizim Toptan cekiliyor...")
    s = cek(sinir, coklu)
    yaz(f"\n{s['yazilan']} urun yazildi.")
    if s["coklu_atlanan"]:
        yaz(f"{s['coklu_atlanan']} coklu paket ATLANDI -- sitedeki fiyatlari "
            f"tutarsiz (bazisi paket, bazisi tek adet fiyati veriyor).")
    if s["gramajsiz"]:
        yaz(f"{s['gramajsiz']} urunun gramaji cozulemedi; listede gorunur ama "
            f"birim fiyat karsilastirmasina giremez.")
    yaz("\nSayfayi uretmek icin:  py katalog.py")


if __name__ == "__main__":
    main()
