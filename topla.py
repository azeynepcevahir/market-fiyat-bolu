# -*- coding: utf-8 -*-
"""
topla.py -- Bolu merkez subelerinden fiyatlari ceker, SQLite'a yazar.

Kullanim:
    py topla.py                     sepet.txt'teki her seyi ceker
    py topla.py --grup Meyve Sebze  sadece belirtilen gruplari ceker
    py topla.py --kesfet elma domates
                                    kelimelerin hangi kategoride gectigini yazar
                                    (sepet.txt'e dogru kategori adi yazmak icin)

Cekim yavastir: sunucuyu yormamak icin her istek arasinda 2 saniye beklenir.
Tam sepet ~90 kelime x ~2 sayfa ~= 6-8 dakika surer. Bu normaldir.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date

import market
from market import yaz


def _subeleri_hazirla(baglanti) -> list[str]:
    yaz("Bolu merkez subeleri aliniyor...")
    subeler = market.subeleri_getir()
    market.subeleri_yaz(baglanti, subeler)

    sayim = Counter(s.get("marketName") for s in subeler)
    ozet = ", ".join(f"{ad}:{adet}" for ad, adet in sorted(sayim.items()))
    yaz(f"  {len(subeler)} sube bulundu  ({ozet})")
    return [s["id"] for s in subeler if s.get("id")]


def kesfet(kelimeler: list[str]) -> None:
    """Kategori filtresi olmadan arar, hangi ana kategorilerin dondugunu yazar."""
    baglanti = market.veritabani()
    depolar = _subeleri_hazirla(baglanti)

    for kelime in kelimeler:
        yaz(f"\n'{kelime}' icin kategoriler:")
        try:
            cevap = market.urun_ara(kelime, depolar, None, sayfa=0)
        except market.ApiHatasi as hata:
            yaz(f"  ! {hata}")
            continue

        sayim = Counter()
        for urun in cevap.get("content") or []:
            sayim[urun.get("main_category") or "(bos)"] += 1

        if not sayim:
            yaz("  sonuc yok")
        for kategori, adet in sayim.most_common():
            yaz(f"  {adet:3d}  {kategori}")

    baglanti.close()


def topla(secili_gruplar: list[str] | None = None) -> None:
    baglanti = market.veritabani()
    depolar = _subeleri_hazirla(baglanti)
    if not depolar:
        yaz("Sube bulunamadi, cekim yapilamiyor.")
        return

    sepet = market.sepet_oku()
    if secili_gruplar:
        istenen = {market.kucult(g) for g in secili_gruplar}
        sepet = [s for s in sepet if market.kucult(s[0]) in istenen]
        if not sepet:
            yaz("Belirtilen grup sepet.txt icinde bulunamadi.")
            return

    bugun = date.today().isoformat()
    toplam_urun = toplam_fiyat = 0
    bos_gruplar: list[str] = []

    for grup, kategori, kelimeler in sepet:
        yaz(f"\n[{grup}]  kategori='{kategori or 'filtresiz'}'  "
            f"{len(kelimeler)} kelime")
        grup_urun = 0

        for kelime in kelimeler:
            bulunan = 0
            for sayfa in range(market.MAKS_SAYFA):
                try:
                    cevap = market.urun_ara(kelime, depolar, kategori or None, sayfa)
                except market.ApiHatasi as hata:
                    yaz(f"  ! '{kelime}' atlandi: {hata}")
                    break

                icerik = cevap.get("content") or []
                if not icerik:
                    break

                urun_sayisi, fiyat_sayisi = market.urun_ve_fiyat_yaz(
                    baglanti, icerik, kelime, grup, bugun
                )
                toplam_urun += urun_sayisi
                toplam_fiyat += fiyat_sayisi
                bulunan += urun_sayisi

                if len(icerik) < market.SAYFA_BOYU:
                    break

            grup_urun += bulunan
            yaz(f"  {kelime:<24} {bulunan:3d} urun")

        if grup_urun == 0:
            bos_gruplar.append(f"{grup} (kategori='{kategori}')")

    yaz(f"\n{'=' * 58}")
    yaz(f"Toplam {toplam_urun} urun kaydi, {toplam_fiyat} fiyat kaydi yazildi.")

    if bos_gruplar:
        yaz("\nDIKKAT -- su gruplardan hic urun gelmedi:")
        for satir in bos_gruplar:
            yaz(f"  - {satir}")
        yaz("  Muhtemelen kategori adi yanlis. Dogrusunu ogrenmek icin:")
        yaz("      py topla.py --kesfet <o gruptaki bir kelime>")

    _adaylari_yaz(baglanti, bugun)
    baglanti.close()
    yaz("\nBitti.  Rapor icin:  py rapor.py")


def kelimelerle_topla(kelimeler: list[str], grup: str = "Favori") -> int:
    """
    Sadece verilen anahtar kelimeleri ceker. Favorileri guncellemek icin
    kullanilir: tum sepeti taramak yerine yalnizca ilgili aramalari yapar,
    boylece 13 dakika yerine 1-2 dakika surer.
    """
    baglanti = market.veritabani()
    depolar = _subeleri_hazirla(baglanti)
    if not depolar:
        yaz("Sube bulunamadi.")
        baglanti.close()
        return 0

    bugun = date.today().isoformat()
    toplam = 0

    yaz(f"\n{len(kelimeler)} kelime guncellenecek")
    for kelime in kelimeler:
        bulunan = 0
        for sayfa in range(market.MAKS_SAYFA):
            try:
                cevap = market.urun_ara(kelime, depolar, None, sayfa)
            except market.ApiHatasi as hata:
                yaz(f"  ! '{kelime}' atlandi: {hata}")
                break
            icerik = cevap.get("content") or []
            if not icerik:
                break
            urun_sayisi, _ = market.urun_ve_fiyat_yaz(
                baglanti, icerik, kelime, None, bugun
            )
            bulunan += urun_sayisi
            if len(icerik) < market.SAYFA_BOYU:
                break
        toplam += bulunan
        yaz(f"  {kelime[:30]:<30} {bulunan:3d} urun")

    yaz(f"\nToplam {toplam} urun kaydi guncellendi.")
    baglanti.close()
    return toplam


def favori_kelimeleri(urun_kimlikleri: list[str]) -> list[str]:
    """Verilen urunlerin hangi arama kelimeleriyle bulundugunu dondurur."""
    if not urun_kimlikleri:
        return []
    baglanti = market.veritabani()
    yer = ",".join("?" * len(urun_kimlikleri))
    satirlar = baglanti.execute(
        f"SELECT DISTINCT kelime FROM urun_kelime WHERE urun_id IN ({yer})",
        urun_kimlikleri,
    ).fetchall()
    baglanti.close()
    return sorted({s["kelime"] for s in satirlar if s["kelime"]})


# ---------------------------------------------------------------------------
# Tum katalog taramasi
# ---------------------------------------------------------------------------

# API'de "hepsini ver" diye bir uc nokta yok; arama kelimesi sart. Bu tohumlar
# genis kategorileri acar, sonrasinda her cevabin facetMap.brand alanindan
# cikan marka isimleri yeni kelime olarak kuyruga eklenir. Boylece katalog
# genisleyerek taranir.
TOHUM_KELIMELER = (
    "su", "süt", "yağ", "un", "et", "çay", "kahve", "kek", "sabun", "kağıt",
    "bebek", "meyve", "sebze", "kahvaltılık", "makarna", "pirinç", "konserve",
    "baharat", "şeker", "tuz", "salça", "peynir", "yoğurt", "tavuk", "balık",
    "ekmek", "çikolata", "bisküvi", "cips", "gazoz", "meşrubat", "deterjan",
    "şampuan", "diş", "tıraş", "ped", "bez", "mama", "kuruyemiş", "zeytin",
    "bal", "reçel", "dondurma", "yumurta", "bakliyat", "sos", "krema",
    "temizlik", "parfüm", "vitamin", "atıştırmalık", "hazır yemek", "turşu",
    "sirke", "pekmez", "gofret", "sakız", "meyve suyu", "maden suyu", "ayran",
)

MAKS_SAYFA_HEPSI = 20   # katalog taramasinda kelime basina sayfa siniri


def _taranmis_kelimeler(baglanti) -> set[str]:
    return {s["kelime"] for s in baglanti.execute("SELECT kelime FROM tarama")}


def hepsini_topla(istek_siniri: int | None = None, sifirla: bool = False) -> None:
    """
    Katalogu genisleyerek tarar. Yarida kesilirse tekrar calistirildiginda
    kaldigi yerden devam eder (taranan kelimeler veritabaninda tutulur).
    """
    baglanti = market.veritabani()
    depolar = _subeleri_hazirla(baglanti)
    if not depolar:
        yaz("Sube bulunamadi.")
        return

    if sifirla:
        baglanti.execute("DELETE FROM tarama")
        baglanti.commit()
        yaz("Tarama gecmisi sifirlandi.")

    bugun = date.today().isoformat()
    islenmis = _taranmis_kelimeler(baglanti)

    kuyruk: list[str] = []
    kuyrukta = set(islenmis)
    for kelime in TOHUM_KELIMELER:
        if kelime not in kuyrukta:
            kuyruk.append(kelime)
            kuyrukta.add(kelime)

    if islenmis:
        yaz(f"Onceki taramadan {len(islenmis)} kelime islenmis, devam ediliyor.")

    istek = 0
    toplam_urun = 0
    kategoriler: Counter = Counter()

    while kuyruk:
        if istek_siniri and istek >= istek_siniri:
            yaz(f"\nIstek siniri ({istek_siniri}) doldu. Kalan kuyruk: {len(kuyruk)}")
            yaz("Devam etmek icin ayni komutu tekrar calistirin.")
            break

        kelime = kuyruk.pop(0)
        bulunan = 0

        for sayfa in range(MAKS_SAYFA_HEPSI):
            if istek_siniri and istek >= istek_siniri:
                break
            try:
                cevap = market.urun_ara(kelime, depolar, None, sayfa)
                istek += 1
            except market.ApiHatasi as hata:
                yaz(f"  ! '{kelime}' atlandi: {hata}")
                break

            icerik = cevap.get("content") or []
            if not icerik:
                break

            urun_sayisi, _ = market.urun_ve_fiyat_yaz(
                baglanti, icerik, kelime, None, bugun
            )
            bulunan += urun_sayisi
            toplam_urun += urun_sayisi
            for urun in icerik:
                kategoriler[urun.get("main_category") or "?"] += 1

            # Yeni marka isimleri = yeni arama kelimeleri
            if sayfa == 0:
                for oge in (cevap.get("facetMap") or {}).get("brand") or []:
                    marka = (oge.get("name") or "").strip()
                    if marka and len(marka) > 1 and marka.lower() not in kuyrukta:
                        kuyruk.append(marka)
                        kuyrukta.add(marka.lower())

            if len(icerik) < market.SAYFA_BOYU:
                break

        baglanti.execute(
            "INSERT OR REPLACE INTO tarama (kelime, tarih, urun_sayisi) VALUES (?, ?, ?)",
            (kelime, bugun, bulunan),
        )
        baglanti.commit()

        yaz(f"  [{len(kuyrukta) - len(kuyruk):>4}/{len(kuyrukta):<4}] "
            f"{kelime[:28]:<28} {bulunan:3d} urun   (kuyruk {len(kuyruk)})")

    benzersiz = baglanti.execute(
        "SELECT COUNT(*) AS n FROM urun WHERE urun_id IN "
        "(SELECT urun_id FROM fiyat WHERE tarih = ?)", (bugun,)
    ).fetchone()["n"]

    yaz(f"\n{'=' * 58}")
    yaz(f"{istek} istek atildi, {toplam_urun} urun kaydi yazildi.")
    yaz(f"Bugun fiyati olan benzersiz urun: {benzersiz}")
    yaz(f"\nEn cok urun gelen kategoriler:")
    for ad, adet in kategoriler.most_common(15):
        yaz(f"  {adet:5d}  {ad}")

    _adaylari_yaz(baglanti, bugun)
    baglanti.close()
    yaz("\nBitti.  Sayfayi uretmek icin:  py katalog.py")


def _adaylari_yaz(baglanti, bugun: str) -> None:
    """
    Temizlik / kisisel bakim urunlerini onay bekleyen aday listesi olarak yazar.
    Bu urunler siz beyaz_liste.txt'e tasimadan raporda ONERILMEZ.
    """
    satirlar = baglanti.execute(
        """
        SELECT u.urun_id, u.baslik, u.marka, u.ana_kategori, u.gramaj_ham,
               MIN(f.fiyat) AS en_ucuz,
               COUNT(DISTINCT f.market) AS market_sayisi
        FROM urun u
        JOIN fiyat f ON f.urun_id = u.urun_id AND f.tarih = ?
        GROUP BY u.urun_id
        ORDER BY u.ana_kategori, u.baslik
        """,
        (bugun,),
    ).fetchall()

    adaylar = [s for s in satirlar if market.beyaz_liste_gerekir(s["ana_kategori"])]
    if not adaylar:
        return

    # Tek markette bulunan urunun karsilastirilacak rakibi yoktur; onaylasaniz
    # da raporda fiyat kiyasi cikmaz. O yuzden cok markette olanlar basa.
    adaylar.sort(key=lambda s: (-s["market_sayisi"], s["baslik"]))

    onayli = market.beyaz_liste_oku()
    yol = market.PROJE / "beyaz_liste_adaylari.txt"

    # Hassas/bebek/parfumsuz ipucu tasiyanlari basa al. Bu bir ELEME degil --
    # liste uzun oldugunda ise yarayacaklari once gormeniz icin siralama.
    isaretli = [s for s in adaylar if market.hassas_ipucu_var(s["baslik"])]
    digerleri = [s for s in adaylar if not market.hassas_ipucu_var(s["baslik"])]

    metin = [
        "# ONAY BEKLEYEN TEMIZLIK / KISISEL BAKIM URUNLERI",
        "#",
        "# Bu dosya her cekimde YENIDEN yazilir, buraya not almayin.",
        "#",
        "# Kullaniminiza uygun olanlarin satirini KOPYALAYIP beyaz_liste.txt",
        "# dosyasina yapistirin. Sadece oradaki urunler raporda karsilastirilir.",
        "#",
        "#   [+] = zaten beyaz listede",
        "#   [*] = basliginda hassas/bebek/parfumsuz gibi bir ipucu var",
        "#         (SADECE siralama ipucu -- urunun size uygun oldugunun",
        "#          garantisi DEGILDIR, etiketi kendiniz kontrol edin)",
        "#",
        "# Cok markette bulunanlar basta. '1 markette' yazanlarin",
        "# karsilastirilacak rakibi yoktur; onaylasaniz da fiyat kiyasi cikmaz.",
        "#",
        f"# {len(adaylar)} aday ({len(isaretli)} ipuclu), {date.today().isoformat()}",
        "",
    ]

    for baslik_metni, kume in (("# --- ipucu tasiyanlar ---", isaretli),
                               ("# --- digerleri ---", digerleri)):
        if not kume:
            continue
        metin.append("")
        metin.append(baslik_metni)
        for s in kume:
            if s["urun_id"] in onayli:
                isaret = "[+]"
            elif market.hassas_ipucu_var(s["baslik"]):
                isaret = "[*]"
            else:
                isaret = "[ ]"
            metin.append(
                f"{isaret} {s['urun_id']} | {s['baslik']} | {s['marka'] or '-'} | "
                f"{s['gramaj_ham'] or '-'} | en ucuz {s['en_ucuz']:.2f} TL | "
                f"{s['market_sayisi']} markette"
            )

    yol.write_text("\n".join(metin) + "\n", encoding="utf-8")
    yaz(f"\n{len(adaylar)} temizlik/bakim urunu onayiniza sunuldu:")
    yaz(f"  {yol.name}  ->  uygun olanlari beyaz_liste.txt'e kopyalayin")


def main() -> None:
    argumanlar = sys.argv[1:]

    if argumanlar and argumanlar[0] == "--kesfet":
        kelimeler = argumanlar[1:]
        if not kelimeler:
            yaz("Kullanim: py topla.py --kesfet elma domates")
            return
        kesfet(kelimeler)
        return

    if argumanlar and argumanlar[0] == "--adaylar":
        # Cekim yapmadan, mevcut veriden onay listesini yeniden uretir.
        # beyaz_liste.txt'e ekleme yaptiktan sonra [+] isaretlerini
        # tazelemek icin kullanisli.
        baglanti = market.veritabani()
        satir = baglanti.execute("SELECT MAX(tarih) AS t FROM fiyat").fetchone()
        if not satir or not satir["t"]:
            yaz("Veritabaninda fiyat yok. Once:  py topla.py")
            return
        _adaylari_yaz(baglanti, satir["t"])
        baglanti.close()
        return

    if argumanlar and argumanlar[0] == "--hepsi":
        sinir = None
        if "--sinir" in argumanlar:
            try:
                sinir = int(argumanlar[argumanlar.index("--sinir") + 1])
            except (IndexError, ValueError):
                yaz("--sinir sonrasi bir sayi bekleniyor.")
                return
        hepsini_topla(istek_siniri=sinir, sifirla="--sifirla" in argumanlar)
        return

    if argumanlar and argumanlar[0] == "--kelime":
        if len(argumanlar) < 2:
            yaz("Kullanim: py topla.py --kelime elma muz")
            return
        kelimelerle_topla(argumanlar[1:])
        return

    if argumanlar and argumanlar[0] == "--grup":
        topla(argumanlar[1:])
        return

    topla()


if __name__ == "__main__":
    main()
