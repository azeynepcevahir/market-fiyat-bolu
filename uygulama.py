# -*- coding: utf-8 -*-
"""
uygulama.py -- alisveris sayfasini sunar ve fiyat cekimini calistirir.

    py uygulama.py

Tarayicida http://localhost:8777 acilir.

Sunulan sayfa, katalog.py'nin urettigi sayfanin TA KENDISIDIR -- ayri bir
arayuz yoktur. Sayfa acilirken /api/durum'u yoklar; cevap alirsa arkasinda
sunucu oldugunu anlar ve "Guncelle" sekmesini gosterir. Ayni dosya telefonda
file:// ile acildiginda o yoklama basarisiz olur, sekme gizli kalir ve sayfa
salt alisveris modunda calisir.

Boylece tek bir arayuz vardir, iki ayri kopya degil.

Sunucu yalnizca 127.0.0.1'e baglanir; agdaki baska cihazlar erisemez.
Sadece Python standart kutuphanesi kullanir.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import katalog
import market
import rapor
import topla
from market import yaz

ADRES = "127.0.0.1"
KAPI = 8777
FAVORI_YOLU = market.PROJE / "favoriler.json"


# ---------------------------------------------------------------------------
# Durum bilgisi
# ---------------------------------------------------------------------------

def durum_bilgisi() -> dict:
    """Sayfa basligindaki ozet: kac urun, kac sube, fiyatlar ne kadar taze."""
    baglanti = market.veritabani()
    try:
        tarih = rapor.son_tarih(baglanti)
        sube_sayisi = baglanti.execute("SELECT COUNT(*) AS n FROM sube").fetchone()["n"]
        if not tarih:
            return {"tarih": None, "urun_sayisi": 0, "sube_sayisi": sube_sayisi,
                    "damga": None}

        satir = baglanti.execute(
            "SELECT COUNT(DISTINCT urun_id) AS n, MAX(guncelleme) AS damga "
            "FROM fiyat WHERE tarih = ?", (tarih,)
        ).fetchone()
        return {
            "tarih": tarih,
            "urun_sayisi": satir["n"],
            "sube_sayisi": sube_sayisi,
            "damga": satir["damga"],
        }
    finally:
        baglanti.close()


# ---------------------------------------------------------------------------
# Favoriler
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Elle fiyat girisi (File, Ozdilek gibi API'de olmayan marketler)
# ---------------------------------------------------------------------------

def elle_listele() -> list[dict]:
    baglanti = market.veritabani()
    try:
        market.elle_ice_aktar(baglanti)
        satirlar = baglanti.execute(
            """
            SELECT e.urun_id, e.market, e.fiyat, e.tarih,
                   u.baslik, u.gramaj_ham, u.miktar, u.birim
            FROM elle_fiyat e JOIN urun u ON u.urun_id = e.urun_id
            ORDER BY e.tarih DESC, u.baslik
            """
        ).fetchall()
        bugun = date.today()
        cikti = []
        for s in satirlar:
            try:
                yas = (bugun - date.fromisoformat(s["tarih"])).days
            except ValueError:
                yas = 0
            cikti.append({
                "urun_id": s["urun_id"], "market": s["market"],
                "market_adi": rapor.market_adi(s["market"]),
                "fiyat": s["fiyat"], "tarih": s["tarih"], "yas_gun": yas,
                "baslik": s["baslik"], "gramaj": s["gramaj_ham"],
                "birim_fiyat": (s["fiyat"] / s["miktar"]) if s["miktar"] else None,
                "birim": s["birim"],
            })
        return cikti
    finally:
        baglanti.close()


def elle_kaydet(veri: dict) -> dict:
    """
    Iki kullanim:
      * urun_id verilirse  -> katalogdaki urune fiyat eklenir
      * baslik verilirse   -> katalogda olmayan urun once tanimlanir
    """
    market_kodu = (veri.get("market") or "file").strip().lower()
    if market_kodu not in market.ELLE_MARKETLER:
        return {"hata": f"Bilinmeyen market: {market_kodu}"}

    try:
        fiyat = float(str(veri.get("fiyat")).replace(",", "."))
    except (TypeError, ValueError):
        return {"hata": "Geçerli bir fiyat girin."}
    if fiyat <= 0:
        return {"hata": "Fiyat sıfırdan büyük olmalı."}

    baglanti = market.veritabani()
    try:
        urun_id = (veri.get("urun_id") or "").strip()
        if not urun_id:
            try:
                urun_id = market.elle_urun_ekle(
                    baglanti,
                    veri.get("baslik") or "",
                    veri.get("marka") or "",
                    veri.get("gramaj") or "",
                )
            except ValueError as hata:
                return {"hata": str(hata)}
        else:
            var = baglanti.execute(
                "SELECT 1 FROM urun WHERE urun_id = ?", (urun_id,)
            ).fetchone()
            if not var:
                return {"hata": "Ürün bulunamadı."}

        market.elle_fiyat_yaz(baglanti, urun_id, market_kodu, fiyat)
        adet = market.elle_disa_aktar(baglanti)
        return {"tamam": True, "urun_id": urun_id, "kayit_sayisi": adet}
    finally:
        baglanti.close()


def elle_sil(veri: dict) -> dict:
    urun_id = (veri.get("urun_id") or "").strip()
    market_kodu = (veri.get("market") or "").strip().lower()
    if not urun_id or not market_kodu:
        return {"hata": "Eksik bilgi."}
    baglanti = market.veritabani()
    try:
        market.elle_fiyat_sil(baglanti, urun_id, market_kodu)
        market.elle_disa_aktar(baglanti)
        return {"tamam": True}
    finally:
        baglanti.close()


# ---------------------------------------------------------------------------
# Fiyat cekimi (arka planda)
# ---------------------------------------------------------------------------

class Ilerleme:
    """Calisan cekimin durumu ve ciktisi."""

    def __init__(self) -> None:
        self.kilit = threading.Lock()
        self.calisiyor = False
        self.bitti = False
        self.hata: str | None = None
        self.satirlar: list[str] = []

    def ekle(self, satir: str) -> None:
        with self.kilit:
            self.satirlar.append(satir)
            if len(self.satirlar) > 500:      # uzun cekimde bellek sismesin
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


def _cekimi_calistir(kapsam: str) -> None:
    try:
        with contextlib.redirect_stdout(_Yakala(ILERLEME)):
            if kapsam == "favori":
                kimlikler = favori_oku()
                kelimeler = topla.favori_kelimeleri(kimlikler)
                if not kelimeler:
                    raise RuntimeError(
                        "Favorilerin arama kelimesi bilinmiyor. Önce tam çekim yapın."
                    )
                print(f"{len(kimlikler)} favori -> {len(kelimeler)} arama kelimesi")
                topla.kelimelerle_topla(kelimeler)
            else:
                topla.topla()

            # Telefondaki kopya da guncellensin
            print("")
            print("Alisveris sayfasi yeniden uretiliyor...")
            katalog.uret()
    except Exception as hata:  # noqa: BLE001
        ILERLEME.hata = str(hata)
        ILERLEME.ekle(f"HATA: {hata}")
    finally:
        with ILERLEME.kilit:
            ILERLEME.calisiyor = False
            ILERLEME.bitti = True


def cekimi_baslat(kapsam: str = "hepsi") -> dict:
    with ILERLEME.kilit:
        if ILERLEME.calisiyor:
            return {"hata": "Çekim zaten sürüyor."}
        ILERLEME.calisiyor = True
        ILERLEME.bitti = False
        ILERLEME.hata = None
        ILERLEME.satirlar = []

    threading.Thread(target=_cekimi_calistir, args=(kapsam,), daemon=True).start()
    return {"tamam": True, "kapsam": kapsam}


# ---------------------------------------------------------------------------
# Sunucu
# ---------------------------------------------------------------------------

class Sunucu(BaseHTTPRequestHandler):

    def log_message(self, bicim, *args):   # sessiz calis
        pass

    def _gonder(self, veri, tur: str = "application/json", kod: int = 200) -> None:
        govde = (json.dumps(veri, ensure_ascii=False) if tur == "application/json"
                 else veri).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", f"{tur}; charset=utf-8")
        self.send_header("Content-Length", str(len(govde)))
        # Kod guncellendiginde tarayici eski sayfayi onbellekten gostermesin.
        self.send_header("Cache-Control", "no-store, must-revalidate")
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
        yol = urlparse(self.path).path

        if yol == "/":
            icerik = katalog.sayfa_html()
            if icerik is None:
                self._gonder(
                    "<h1>Veri yok</h1><p>Once calistirin: <code>py topla.py</code></p>",
                    "text/html",
                )
            else:
                self._gonder(icerik, "text/html")

        elif yol == "/api/durum":
            self._gonder(durum_bilgisi())

        elif yol == "/api/cekim":
            self._gonder(ILERLEME.durum())

        elif yol == "/api/favori":
            self._gonder(favori_oku())

        elif yol == "/api/elle":
            self._gonder(elle_listele())

        else:
            self._gonder({"hata": "bulunamadi"}, kod=404)

    def do_POST(self) -> None:
        yol = urlparse(self.path).path
        veri = self._govde_oku()

        if yol == "/api/favori":
            favori_yaz([str(x) for x in veri] if isinstance(veri, list) else [])
            self._gonder({"tamam": True})

        elif yol == "/api/cekim":
            kapsam = (veri or {}).get("kapsam")
            self._gonder(cekimi_baslat("favori" if kapsam == "favori" else "hepsi"))

        elif yol == "/api/elle":
            self._gonder(elle_kaydet(veri or {}))

        elif yol == "/api/elle/sil":
            self._gonder(elle_sil(veri or {}))

        else:
            self._gonder({"hata": "bulunamadi"}, kod=404)


def main() -> None:
    bilgi = durum_bilgisi()
    if not bilgi["tarih"]:
        yaz("Veritabaninda fiyat yok. Once calistirin:  py topla.py")
        return

    sunucu = ThreadingHTTPServer((ADRES, KAPI), Sunucu)
    adres = f"http://{ADRES}:{KAPI}"

    yaz(f"{bilgi['urun_sayisi']} urun, {bilgi['sube_sayisi']} sube, "
        f"fiyat tarihi {bilgi['tarih']}")
    yaz(f"Arayuz hazir:  {adres}")
    yaz("Kapatmak icin Ctrl+C")

    # --tarayicisiz: disaridan baslatilirken fazladan pencere acilmasin
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
