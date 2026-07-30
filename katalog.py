# -*- coding: utf-8 -*-
"""
katalog.py -- tek dosyalik, sunucusuz alisveris sitesi uretir.

Tum urun katalogunu ve hesaplama mantigini HTML'in ICINE gomer. Ortaya cikan
dosya telefonda, cevrimdisi, hicbir kurulum olmadan calisir: arama yaparsiniz,
sepete eklersiniz, "Hesapla" dersiniz, hangi urunu hangi marketten alacaginiz
cikar. Sepet tarayicida saklanir, dosyayi kapatip acsaniz da durur.

Kullanim:
    py katalog.py          uretir
    py katalog.py --ac     uretip tarayicida acar

Cikti:  OneDrive\\Alisveris\\Market-Sepet.html
"""

from __future__ import annotations

import json
import re
import sys

import market
import rapor
from market import yaz

# Yumurtada adet kadar BOY da onemli: M boy (53-62 gr) ile L boy (63-72 gr)
# ayni urun degildir. Bazi urunler harfle ("M Boy"), bazilari gram araligiyla
# ("53-62 Gr") yaziyor; ikisini de ayni olceye ceviriyoruz.
_RE_GRAM_ARALIK = re.compile(r"(\d{2})\s*[-–]\s*(\d{2})\s*gr", re.IGNORECASE)
_RE_HARF_BOY = re.compile(r"\b(xxl|xl|[sml])\s*boy\b", re.IGNORECASE)


def boy_coz(baslik: str) -> str:
    """Yumurta boyunu tek harfe indirger. Bulamazsa bos doner."""
    eslesme = _RE_GRAM_ARALIK.search(baslik or "")
    if eslesme:
        alt = int(eslesme.group(1))
        if alt >= 73:
            return "XL"
        if alt >= 63:
            return "L"
        if alt >= 53:
            return "M"
        if alt >= 43:
            return "S"
    eslesme = _RE_HARF_BOY.search(baslik or "")
    if eslesme:
        return eslesme.group(1).upper()
    return ""


# Urunu "farkli bir sey" yapan nitelikler. Organik yumurta normal yumurtayla
# muadil sayilamaz -- fiyat farkinin sebebi zaten budur. Bu nitelikler
# tutmuyorsa iki urun ayni gramajda olsa bile karsilastirilmaz.
NITELIKLER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("organik", ("organik", "bio ", "biyo")),
    ("gezen", ("gezen", "free range", "freerange", "serbest gezen", "dolasan")),
    ("koy", ("koy yumurta", "koy tipi")),
    ("omega", ("omega",)),
    ("a-sinifi", ("a sinifi", "sinif a", "a class")),
    ("glutensiz", ("glutensiz", "gluten icermez")),
    ("laktozsuz", ("laktozsuz", "laktoz icermez")),
    ("sekersiz", ("sekersiz", "seker ilavesiz", "seker ilaveli degil")),
    ("tuzsuz", ("tuzsuz",)),
    ("light", ("light", "diyet", "az yagli", "yarim yagli")),
    ("tamyagli", ("tam yagli",)),
    ("tuzlu", ("tuzlu",)),
)


def nitelik_coz(baslik: str) -> str:
    """Basliktaki ayirt edici nitelikleri sabit siralı bir etikete cevirir."""
    metin = market.sadelestir(baslik or "")
    bulunan = [etiket for etiket, ipuclari in NITELIKLER
               if any(ipucu in metin for ipucu in ipuclari)]
    return "+".join(bulunan)


ENDEKS_GUN = 90       # zaman serisinde gosterilecek en fazla gun
ENDEKS_GRUP = 24      # zaman serisine girecek grup sayisi (en cok urunlu)


def istatistik_verisi() -> dict:
    """
    Zaman serisi ozetlerini sayfaya gomulecek kompakt bicime cevirir.

    Ham fiyat gecmisi gomulmez -- cok buyuk olurdu. Onun yerine gunluk
    medyan birim fiyat serileri konur: hem market genelinde, hem de en
    cok urunlu gruplar icin. Bu, "su kategori bu ay ne kadar zamlandi"
    sorusunu birkac kilobayta sigdiriyor.
    """
    baglanti = market.veritabani()
    try:
        gunler = [s["tarih"] for s in baglanti.execute(
            "SELECT DISTINCT tarih FROM gunluk_endeks ORDER BY tarih DESC LIMIT ?",
            (ENDEKS_GUN,))]
        gunler.reverse()
        if not gunler:
            return {"gunler": [], "market": {}, "grup": {}, "takip": {}}

        yer = ",".join("?" * len(gunler))
        satirlar = baglanti.execute(
            f"""SELECT tarih, market, grup, urun_sayisi, medyan_birim
                FROM gunluk_endeks WHERE tarih IN ({yer})""", gunler).fetchall()

        # En cok urunlu gruplar
        agirlik: dict[str, int] = {}
        for s in satirlar:
            agirlik[s["grup"]] = agirlik.get(s["grup"], 0) + (s["urun_sayisi"] or 0)
        secili = sorted(agirlik, key=lambda g: -agirlik[g])[:ENDEKS_GRUP]

        gun_yeri = {t: i for i, t in enumerate(gunler)}
        market_seri: dict[str, list] = {}
        grup_seri: dict[str, dict[str, list]] = {}

        # Market geneli: gunluk medyanlarin medyani
        havuz: dict[tuple[str, str], list[float]] = {}
        for s in satirlar:
            if s["medyan_birim"] is None:
                continue
            havuz.setdefault((s["tarih"], s["market"]), []).append(s["medyan_birim"])
            if s["grup"] in secili:
                d = grup_seri.setdefault(s["grup"], {})
                dizi = d.setdefault(s["market"], [None] * len(gunler))
                dizi[gun_yeri[s["tarih"]]] = round(s["medyan_birim"], 2)

        for (t, m), degerler in havuz.items():
            degerler.sort()
            orta = len(degerler) // 2
            medyan = (degerler[orta] if len(degerler) % 2
                      else (degerler[orta - 1] + degerler[orta]) / 2)
            market_seri.setdefault(m, [None] * len(gunler))[gun_yeri[t]] = round(medyan, 2)

        # Favori urunlerin fiyat gecmisi
        takip: dict[str, dict[str, list]] = {}
        for s in baglanti.execute(
            f"SELECT tarih, urun_id, market, fiyat FROM takip_fiyat WHERE tarih IN ({yer})",
            gunler,
        ):
            d = takip.setdefault(s["urun_id"], {})
            dizi = d.setdefault(s["market"], [None] * len(gunler))
            dizi[gun_yeri[s["tarih"]]] = round(s["fiyat"], 2)

        return {"gunler": gunler, "market": market_seri,
                "grup": grup_seri, "takip": takip}
    finally:
        baglanti.close()


def veriyi_hazirla() -> dict:
    """Katalogu tarayiciya gomulecek kompakt bicime cevirir."""
    baglanti = market.veritabani()
    tarih = rapor.son_tarih(baglanti)
    if not tarih:
        baglanti.close()
        return {}

    teklifler = rapor.teklifleri_yukle(baglanti, tarih)
    sube_sayisi = baglanti.execute("SELECT COUNT(*) AS n FROM sube").fetchone()["n"]
    baglanti.close()

    # Market kodlari -> indeks (dosya boyutunu kucultmek icin)
    market_kodlari = sorted({t["market"] for t in teklifler})
    market_indeksi = {kod: i for i, kod in enumerate(market_kodlari)}

    # Urun bazinda topla: her markette en ucuz fiyat
    urunler: dict[str, dict] = {}
    for t in teklifler:
        kayit = urunler.get(t["urun_id"])
        if kayit is None:
            kayit = urunler[t["urun_id"]] = {
                "urun_id": t["urun_id"],
                "baslik": t["baslik"],
                "marka": t["marka"] or "",
                "gramaj": t["gramaj_ham"] or "",
                "grup": t["grup"] or "",
                "birim": t["birim"] or "",
                "miktar": t["miktar"],
                "gid": rapor.grup_anahtari(t),
                "fiyatlar": {},
            }
        mevcut = kayit["fiyatlar"].get(t["market"])
        if mevcut is None or t["fiyat"] < mevcut:
            kayit["fiyatlar"][t["market"]] = t["fiyat"]

    # Grup anahtarlarini kisa sayilara cevir
    grup_indeksi: dict = {}
    for kayit in urunler.values():
        anahtar = kayit["gid"]
        if anahtar not in grup_indeksi:
            grup_indeksi[anahtar] = len(grup_indeksi)

    satirlar = []
    for kayit in urunler.values():
        teklif_listesi = sorted(
            ([market_indeksi[m], round(f, 2)] for m, f in kayit["fiyatlar"].items()),
            key=lambda p: p[1],
        )
        satirlar.append([
            kayit["baslik"],
            kayit["gramaj"],
            kayit["grup"],
            grup_indeksi[kayit["gid"]],
            kayit["birim"],
            round(kayit["miktar"], 4) if kayit["miktar"] else 0,
            teklif_listesi,
            boy_coz(kayit["baslik"]),
            nitelik_coz(kayit["baslik"]),
            kayit["urun_id"],   # sunucuya favori bildirirken gerekiyor
        ])

    # Cok markette bulunanlar aramada one ciksin
    satirlar.sort(key=lambda s: (-len(s[6]), s[0]))

    # Elle girilen fiyatlarin giris tarihleri -- sayfada "ne zaman girdim"
    # bilgisini gosterebilmek icin. Anahtar: "urun_id|market"
    baglanti2 = market.veritabani()
    try:
        elle_tarih = {
            f"{s['urun_id']}|{s['market']}": s["tarih"]
            for s in baglanti2.execute("SELECT urun_id, market, tarih FROM elle_fiyat")
        }
    finally:
        baglanti2.close()

    return {
        "tarih": tarih,
        "ist": istatistik_verisi(),
        "elle_tarih": elle_tarih,
        "sube_sayisi": sube_sayisi,
        "marketler": market_kodlari,
        "market_adlari": [rapor.market_adi(k) for k in market_kodlari],
        "elle_marketler": market.elle_marketleri_oku(),
        "ziyaret_maliyeti": rapor.ZIYARET_MALIYETI,
        "min_kapsam": rapor.MIN_KAPSAM,
        "urunler": satirlar,
    }


SAYFA = r"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Sepeti &mdash; Bolu Merkez</title><style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:#f4f6f8;
     color:#14181f;line-height:1.5;padding-bottom:78px}
header{background:#14181f;color:#fff;padding:11px 14px;position:sticky;top:0;z-index:20}
header .baslik{font-size:16px;font-weight:600}
header .bilgi{font-size:11px;opacity:.65}
.sekmeler{display:flex;background:#1f242e;position:sticky;top:53px;z-index:19}
.sekmeler button{flex:1;background:none;border:none;color:#9aa3b1;padding:11px 4px;
     font-size:13px;font-weight:600;font-family:inherit;cursor:pointer;border-bottom:2px solid transparent}
.sekmeler button.etkin{color:#fff;border-bottom-color:#0b7a3b}
.sayfa{display:none;padding:12px;max-width:900px;margin:0 auto}
.sayfa.etkin{display:block}
input[type=search]{width:100%;padding:12px 14px;font-size:16px;border:1px solid #c8cfd9;
     border-radius:9px;font-family:inherit;background:#fff}
select{padding:8px 10px;font-size:14px;border:1px solid #c8cfd9;border-radius:8px;
     font-family:inherit;background:#fff}
.kart{background:#fff;border:1px solid #dde2e9;border-radius:10px;margin-top:10px;overflow:hidden}
.urun{display:flex;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid #eef1f4}
.urun:last-child{border-bottom:none}
.urun .bilgi{flex:1;min-width:0}
.urun .ad{font-size:14px;line-height:1.35}
.urun .alt{font-size:11px;color:#7b8494;margin-top:3px}
.urun .fiyat{text-align:right;white-space:nowrap}
.urun .fiyat b{color:#0b7a3b;font-size:15px}
.rozet{display:inline-block;padding:1px 7px;border-radius:99px;font-size:10px;font-weight:600;
     background:#eef1f5;color:#5a6472;margin-right:4px}
.rozet.iyi{background:#e6f4ec;color:#0b7a3b}
.rozet.firsat{background:#fdecea;color:#b3261e}
button.ekle{background:#0b7a3b;color:#fff;border:none;border-radius:8px;padding:9px 14px;
     font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;min-width:64px}
button.ekle.eklendi{background:#dfe4ea;color:#5a6472}
button.sil{background:none;border:none;color:#b3261e;font-size:22px;cursor:pointer;padding:0 6px}
button.yildiz{background:none;border:none;font-size:21px;cursor:pointer;padding:0 2px;
     color:#c2c9d3;line-height:1}
button.yildiz.dolu{color:#f0a500}
.adet{display:flex;align-items:center;gap:6px}
.adet button{width:30px;height:30px;border-radius:7px;border:1px solid #c8cfd9;background:#fff;
     font-size:17px;cursor:pointer;font-family:inherit;line-height:1}
.adet span{min-width:22px;text-align:center;font-size:14px;font-weight:600}
.bos{text-align:center;color:#7b8494;font-size:14px;padding:36px 16px}
.altbar{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #dde2e9;
     padding:9px 12px;display:flex;gap:10px;align-items:center;z-index:25;
     box-shadow:0 -2px 10px rgba(0,0,0,.06)}
.altbar .say{flex:1;font-size:13px;color:#5a6472}
.altbar button{background:#14181f;color:#fff;border:none;border-radius:9px;padding:12px 22px;
     font-size:15px;font-weight:600;cursor:pointer;font-family:inherit}
.altbar button:disabled{background:#aeb6c0}
.ozet{background:#e6f4ec;border:1px solid #b3ddc4;border-radius:10px;padding:14px;text-align:center}
.ozet .buyuk{font-size:27px;font-weight:700;color:#0b7a3b;line-height:1.2}
.ozet .kucuk{font-size:12px;color:#4a5561;margin-top:5px}
.ozet.duz{background:#eef1f5;border-color:#d5dbe3}
.ozet.duz .buyuk{color:#14181f;font-size:20px}
.market h3{margin:0;background:#14181f;color:#fff;padding:9px 12px;font-size:13px;
     display:flex;justify-content:space-between;align-items:center}
.uyari{background:#fff7e3;border:1px solid #eed490;border-radius:9px;padding:11px;
     font-size:12.5px;margin-top:10px}
.satirlar{max-height:none}
.ayar{display:flex;gap:10px;align-items:center;font-size:13px;color:#5a6472;margin-top:10px;
     flex-wrap:wrap}
.dip{text-align:center;font-size:11px;color:#8b93a0;padding:18px 12px 4px}
.kucuk{font-size:12px;color:#5a6472;line-height:1.5}
.birincil{background:#14181f;color:#fff;border:none;border-radius:9px;padding:12px;
     font-size:15px;font-weight:600;cursor:pointer;font-family:inherit;width:100%;margin-top:10px}
.birincil:disabled{background:#aeb6c0;cursor:not-allowed}
#cekLog{background:#14181f;color:#c8d3e0;font-size:11px;line-height:1.45;padding:10px;
     border-radius:8px;max-height:260px;overflow:auto;margin:12px 0 0;white-space:pre-wrap;
     font-family:Consolas,monospace}
#cekLog:empty{display:none}
@media print{.sekmeler,.altbar,header{display:none}.sayfa{display:block!important}
     body{padding:0;background:#fff}#sayfa-ara,#sayfa-firsat{display:none!important}}
</style></head><body>

<header>
  <div class="baslik">Market Sepeti &mdash; Bolu Merkez</div>
  <div class="bilgi" id="ust"></div>
</header>

<div class="sekmeler">
  <button data-s="ara" class="etkin">Ara</button>
  <button data-s="favori">★ <span id="favSayi">0</span></button>
  <button data-s="sepet">Sepet (<span id="rozetSayi">0</span>)</button>
  <button data-s="sonuc">Sonuç</button>
  <button data-s="firsat">Fırsat</button>
  <button data-s="istatistik">📊</button>
  <button data-s="elle">✎ Elle<span id="elleRozet"></span></button>
  <button data-s="guncelle" id="sekmeGuncelle" style="display:none">⟳ Güncelle</button>
</div>

<div class="sayfa etkin" id="sayfa-ara">
  <input type="search" id="q" placeholder="elma, zeytinyağı, mercimek…" autocomplete="off">
  <div class="ayar">
    <label>Grup:
      <select id="grupSuz"><option value="">hepsi</option></select>
    </label>
    <label>Sırala: <select id="sirala" class="siraSecim"></select></label>
    <label title="İşaretlerseniz sadece en az iki markette bulunan ürünler listelenir.
Yumurta gibi her marketin kendi markasını sattığı ürünlerde bu neredeyse hiçbir şey bırakmaz.">
      <input type="checkbox" id="sadeceCok"> sadece 2+ markette olanlar</label>
  </div>
  <div id="sonuclar"><div class="bos">Ürün aramak için yukarıya yazın.</div></div>
</div>

<div class="sayfa" id="sayfa-favori">
  <div class="ayar" id="favAraclar" style="display:none">
    <button class="ekle" id="favHepsi">Hepsini sepete ekle</button>
    <button class="ekle" id="favTemizle"
            style="background:#dfe4ea;color:#5a6472">Favorileri temizle</button>
    <label>Sırala: <select id="favSirala" class="siraSecim"></select></label>
  </div>
  <div id="favoriListe"></div>
</div>

<div class="sayfa" id="sayfa-sepet">
  <div id="sepetListe"><div class="bos">Sepetiniz boş.<br>“Ara” sekmesinden ürün ekleyin.</div></div>
</div>

<div class="sayfa" id="sayfa-sonuc">
  <div class="ayar">
    <label>En fazla kaç markete uğrarsınız?
      <select id="maks">
        <option value="1">1</option><option value="2" selected>2</option>
        <option value="3">3</option><option value="4">4</option>
      </select>
    </label>
    <label>Ziyaret maliyeti:
      <select id="ziyaret">
        <option value="0">0 TL</option><option value="15">15 TL</option>
        <option value="25" selected>25 TL</option><option value="40">40 TL</option>
        <option value="60">60 TL</option>
      </select>
    </label>
    <label title="Aynı marka bulunamazsa, aynı gramajdaki başka markaları da değerlendirir.
Yumurta gibi her marketin kendi markasını sattığı ürünlerde bu olmadan karşılaştırma yapılamıyor.">
      <input type="checkbox" id="markaFark" checked> aynı gramajda farklı markaları da değerlendir</label>
  </div>
  <div id="sonucIcerik"><div class="bos">Sepete ürün ekleyip “Hesapla” deyin.</div></div>
</div>

<div class="sayfa" id="sayfa-firsat">
  <div class="ayar">
    <label>Sırala: <select id="firsatSirala" class="siraSecim"></select></label>
    <label>Grup: <select id="firsatGrup"><option value="">hepsi</option></select></label>
  </div>
  <div class="bos" style="padding:10px 0;text-align:left;font-size:12.5px">
    En az iki markette bulunan ürünler. Uç farklara (%70 üstü) şüpheyle bakın;
    farklı çeşit veya veri hatası olabilir.
  </div>
  <div id="firsatListe"></div>
</div>

<div class="sayfa" id="sayfa-istatistik">
  <div id="istIcerik"></div>
</div>

<div class="sayfa" id="sayfa-elle">
  <div class="kart" style="padding:14px">
    <h3 style="margin:0 0 8px;font-size:15px">File / Özdilek fiyatı gir</h3>
    <div class="kucuk" id="elleDurum"></div>

    <div class="ayar" style="margin-top:10px">
      <label>Market: <select id="elleMarket"></select></label>
    </div>

    <div style="margin-top:14px">
      <b style="font-size:13px">1) Favorilerim</b>
      <div class="kucuk">Düzenli aldıklarınız. Markette bu listeyi açıp fiyatları yazın.</div>
      <div id="elleFavoriler"></div>
    </div>

    <div style="margin-top:16px">
      <b style="font-size:13px">2) Katalogdan başka bir ürün ara</b>
      <div class="kucuk">Ulusal markalar (Sütaş, Ülker, Torku…) zaten katalogda.</div>
      <input type="search" id="elleAra" placeholder="ürün ara…" autocomplete="off"
             style="margin-top:6px">
      <div id="elleSonuc"></div>
    </div>

    <details style="margin-top:14px;border:none">
      <summary style="padding:8px 0;font-size:13px">
        3) Katalogda olmayan ürün ekle (File'a özel markalar)</summary>
      <input type="text" id="elleBaslik" placeholder="Ürün adı — örn. Dost Süt 1 L">
      <div class="ayar" style="margin-top:6px">
        <input type="text" id="elleMarka" placeholder="Marka" style="flex:1">
        <input type="text" id="elleGramaj" placeholder="Gramaj — 1 L" style="flex:1">
        <input type="text" id="elleFiyat2" inputmode="decimal" placeholder="Fiyat" style="width:90px">
      </div>
      <button class="birincil" id="elleYeniEkle">Yeni ürün olarak ekle</button>
    </details>

    <details style="margin-top:14px;border:none">
      <summary style="padding:8px 0;font-size:13px">
        4) Dosyadan toplu aktar (txt)</summary>

      <div class="kucuk">
        Fiyatları bir metin dosyasına yazıp topluca aktarabilirsiniz.
        Dosya seçin ya da içeriğini aşağıya yapıştırın.
      </div>

      <details style="margin:8px 0;border:none">
        <summary style="padding:6px 0;font-size:12.5px">Dosya nasıl yazılır?</summary>
        <div class="kucuk" style="margin-bottom:6px">
          Her satır bir ürün: <b>ürün adı | fiyat</b><br>
          Köşeli parantez o satırdan sonrasının hangi markete ait olduğunu belirler.<br>
          <code>#</code> ile başlayan satırlar not olarak atlanır.
        </div>
<pre style="background:#f4f6f8;color:#14181f;border:1px solid #dde2e9;padding:10px;
     border-radius:8px;font-size:11.5px;white-space:pre-wrap;margin:0"># 28 Temmuz, File Bolu merkez
[file]
Sütaş Tam Yağlı Süt 1 L | 42,50
Yudum Riviera Zeytinyağı 1 Lt | 219,90
Torku Tam Buğday Un 5 Kg | 135

[ozdilek]
Sütaş Tam Yağlı Süt 1 L | 44,00

# Tarih belirtmek isterseniz (yazmazsanız bugün sayılır):
[tarih: 2026-07-28]
[nuhmar]
Piyale Burgu Makarna 500 Gr | 17,50</pre>
        <div class="kucuk" style="margin-top:6px">
          <b>Ayırıcı:</b> <code>|</code> kullanın. Noktalı virgül ve sekme de kabul edilir.<br>
          <b>Fiyat:</b> <code>42,50</code> ya da <code>42.50</code> — ikisi de olur, TL yazmanıza gerek yok.<br>
          <b>Market kodları:</b> <span id="elleKodlar"></span><br>
          <b>Ürün adı:</b> katalogdaki adla birebir aynı olmak zorunda değil; yazdığınız
          kelimelerin hepsi geçen ürün bulunur. Bulunamazsa yeni ürün olarak eklenir,
          gramajı adından çözülür (bu yüzden <i>1 L</i>, <i>500 Gr</i> gibi bir miktar yazın).
        </div>
      </details>

      <input type="file" id="elleDosya" accept=".txt,.csv,text/plain"
             style="font-size:13px;margin:6px 0">
      <textarea id="elleToplu" rows="6" placeholder="[file]&#10;Ürün adı | fiyat"
        style="width:100%;font-family:Consolas,monospace;font-size:12px;
               border:1px solid #c8cfd9;border-radius:8px;padding:8px"></textarea>
      <button class="birincil" id="elleOnizle" style="background:#3a4250">Önizle</button>
      <div id="elleOnizleme"></div>
    </details>

    <div id="elleBekleyen" style="margin-top:16px"></div>
    <div id="elleKayitli" style="margin-top:16px"></div>

    <details id="elleAktarKutu" style="margin-top:14px;border:none;display:none">
      <summary style="padding:8px 0;font-size:13px">Telefondan gelen girişleri içeri al</summary>
      <div class="kucuk">Telefonda “Kopyala” dediğiniz metni buraya yapıştırın.</div>
      <textarea id="elleYapistir" rows="4" placeholder="[{...}]"
        style="width:100%;margin-top:6px;font-family:Consolas,monospace;font-size:11px;
               border:1px solid #c8cfd9;border-radius:8px;padding:8px"></textarea>
      <button class="birincil" id="elleIceAl">İçeri al</button>
    </details>
  </div>
</div>

<div class="sayfa" id="sayfa-guncelle">
  <div class="kart" style="padding:14px">
    <h3 style="margin:0 0 8px;font-size:15px">Fiyatları güncelle</h3>
    <div class="kucuk">
      Marketlerden güncel fiyatları çeker. Bitince bu sayfa ve telefonunuzdaki
      kopya birlikte yenilenir. Çekim sürerken arama ve sepet çalışmaya devam eder.
    </div>
    <button class="birincil" id="cekFavori">★ Sadece favorilerimi güncelle</button>
    <div class="kucuk" id="favBilgi" style="margin:4px 0 10px"></div>
    <button class="birincil" id="cekHepsi" style="background:#3a4250">
      Tüm sepeti çek (13–15 dk)</button>
    <pre id="cekLog"></pre>
  </div>
</div>

<div class="altbar">
  <div class="say" id="altSay">Sepet boş</div>
  <button id="hesapla" disabled>Hesapla</button>
</div>

<div class="dip">
  marketfiyati.org.tr verisiyle üretildi &middot; fiyatlar mağaza rafından farklı olabilir
</div>

<script id="veri" type="application/json">__VERI__</script>
<script>
const D = JSON.parse(document.getElementById("veri").textContent);
const MARKET = D.market_adlari;
// market kodu -> gorunen ad (istatistik serilerinde kod kullaniliyor)
const MARKET_KOD = {};
(D.marketler || []).forEach((k, i) => { MARKET_KOD[k] = D.market_adlari[i]; });
// urun dizisi:
// [0 baslik, 1 gramaj, 2 grup, 3 gid, 4 birim, 5 miktar,
//  6 [[marketIdx, fiyat], ...], 7 boy (S/M/L/XL), 8 nitelik (organik+gezen...)]
const U = D.urunler;
const BOY_ADI = {S: "S boy", M: "M boy", L: "L boy", XL: "XL boy", XXL: "XXL boy"};
const NITELIK_ADI = {organik: "organik", gezen: "gezen", koy: "köy", omega: "omega-3",
  "a-sinifi": "A sınıfı", glutensiz: "glutensiz", laktozsuz: "laktozsuz",
  sekersiz: "şekersiz", tuzsuz: "tuzsuz", light: "light", tamyagli: "tam yağlı",
  tuzlu: "tuzlu"};
const nitelikYaz = (s) => (s || "").split("+").filter(Boolean)
  .map((k) => NITELIK_ADI[k] || k).join(", ");

// "2026-07-29" -> "29.07.2026"
const tarihYaz = (s) => {
  if (!s || s.length < 10) return s || "";
  return `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)}`;
};
const gunFarki = (s) => {
  if (!s) return null;
  const fark = (new Date(D.tarih) - new Date(s)) / 86400000;
  return isNaN(fark) ? null : Math.max(0, Math.round(fark));
};

const TR = {"ı":"i","İ":"i","I":"i","ğ":"g","Ğ":"g","ü":"u","Ü":"u",
            "ş":"s","Ş":"s","ö":"o","Ö":"o","ç":"c","Ç":"c"};
const sade = (s) => (s || "").replace(/[ıİIğĞüÜşŞöÖçÇ]/g, (c) => TR[c]).toLowerCase();

// Arama dizini ve grup haritasi
const ARAMA = U.map((u) => sade(u[0] + " " + u[2]));
const GRUPLAR = [...new Set(U.map((u) => u[2]).filter(Boolean))].sort();
const GID = new Map();
U.forEach((u, i) => {
  if (!GID.has(u[3])) GID.set(u[3], []);
  GID.get(u[3]).push(i);
});

// Ana kelimeler: markadan bagimsiz olarak urunun NE oldugunu anlatan kelimeler.
// "Türem Yumurta M Boy 30 Adet" -> {yumurta}
const OLCU_KELIME = new Set(["adet","gram","kilo","litre","paket","boy","tane",
                             "gr","kg","lt","ml","adetli","lik","luk"]);
const ANA = U.map((u) => new Set(
  sade(u[0]).split(/[^a-z0-9]+/)
    .filter((k) => k.length >= 4 && !OLCU_KELIME.has(k) && !/^\d/.test(k))
));

// Ayni gramaj + ayni birim. Marka tutmadiginda muadiller burada aranir:
// yumurtada 28 urunun 27'si tek markete ozel marka oldugu icin
// "ayni marka" kurali hic calismiyor, "ayni gramaj" ise calisiyor.
const OLCU = new Map();
U.forEach((u, i) => {
  if (!u[5] || !u[4]) return;
  const k = u[4] + "|" + u[5];
  if (!OLCU.has(k)) OLCU.set(k, []);
  OLCU.get(k).push(i);
});

/* ---------- ortak siralama ---------- */
const bfOf = (i) => (U[i][5] ? U[i][6][0][1] / U[i][5] : null);
const ucuzOf = (i) => U[i][6][0][1];
const farkOf = (i) => (U[i][6].length > 1 ? U[i][6][U[i][6].length - 1][1] - ucuzOf(i) : 0);
const oranOf = (i) => {
  const t = U[i][6];
  if (t.length < 2) return 0;
  const p = t[t.length - 1][1];
  return p ? (p - t[0][1]) / p : 0;
};
const bosSona = (x, y, i, j) => {
  if (x == null && y == null) return ucuzOf(i) - ucuzOf(j);
  if (x == null) return 1;
  if (y == null) return -1;
  return x - y;
};

const SIRA_SECENEKLERI = [
  ["birim", "birim fiyat (ucuzdan)"],
  ["fiyat", "etiket fiyatı (ucuzdan)"],
  ["pahali", "etiket fiyatı (pahalıdan)"],
  ["fark", "marketler arası fark (TL)"],
  ["oran", "marketler arası fark (%)"],
  ["market", "kaç markette bulunduğu"],
  ["ad", "isme göre (A→Z)"],
];

const SIRALAYICI = {
  birim: (a, b) => bosSona(bfOf(a), bfOf(b), a, b),
  fiyat: (a, b) => ucuzOf(a) - ucuzOf(b),
  pahali: (a, b) => ucuzOf(b) - ucuzOf(a),
  fark: (a, b) => farkOf(b) - farkOf(a),
  oran: (a, b) => oranOf(b) - oranOf(a),
  market: (a, b) => U[b][6].length - U[a][6].length || farkOf(b) - farkOf(a),
  ad: (a, b) => U[a][0].localeCompare(U[b][0], "tr"),
};

function siraDoldur(secim, varsayilan) {
  secim.innerHTML = SIRA_SECENEKLERI.map(
    ([d, ad]) => `<option value="${d}"${d === varsayilan ? " selected" : ""}>${ad}</option>`
  ).join("");
}

const sirala = (liste, nasil) => liste.slice().sort(SIRALAYICI[nasil] || SIRALAYICI.fiyat);

const birimFiyat = (i, fiyat) => (U[i][5] ? fiyat / U[i][5] : null);
const birimYaz = (i, fiyat) => {
  const bf = birimFiyat(i, fiyat);
  return bf == null ? "" : para(bf) + "/" + U[i][4];
};

let sepet = [], favori = [];
try { sepet = JSON.parse(localStorage.getItem("marketSepet") || "[]"); } catch (e) { sepet = []; }
try { favori = JSON.parse(localStorage.getItem("marketFavori") || "[]"); } catch (e) { favori = []; }
if (!Array.isArray(sepet)) sepet = [];
if (!Array.isArray(favori)) favori = [];
// Katalog yenilendiginde kaybolan urunleri temizle
sepet = sepet.filter((k) => k && U[k.i]);
favori = favori.filter((i) => U[i]);

const el = (s) => document.querySelector(s);
const para = (n) => (n == null || isNaN(n) ? "-" :
  n.toLocaleString("tr-TR", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " TL");
const kacir = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

el("#ust").textContent =
  `${U.length} ürün · ${D.sube_sayisi} şube · ${MARKET.length} market · fiyat ${D.tarih}`;
const grupSecenek = '<option value="">hepsi</option>' +
  GRUPLAR.map((g) => `<option>${kacir(g)}</option>`).join("");
el("#grupSuz").innerHTML = grupSecenek;
el("#firsatGrup").innerHTML = grupSecenek;

siraDoldur(el("#sirala"), "birim");
siraDoldur(el("#favSirala"), "ad");
siraDoldur(el("#firsatSirala"), "fark");
el("#favSirala").onchange = cizFavoriler;
el("#firsatSirala").onchange = cizFirsatlar;
el("#firsatGrup").onchange = cizFirsatlar;

/* ---------- sekmeler ---------- */
document.querySelectorAll(".sekmeler button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".sekmeler button").forEach((x) => x.classList.remove("etkin"));
    document.querySelectorAll(".sayfa").forEach((x) => x.classList.remove("etkin"));
    b.classList.add("etkin");
    el("#sayfa-" + b.dataset.s).classList.add("etkin");
    if (b.dataset.s === "firsat") cizFirsatlar();
    if (b.dataset.s === "sepet") cizSepet();
    if (b.dataset.s === "favori") cizFavoriler();
    if (b.dataset.s === "elle") { cizElleFavoriler(); cizBekleyen(); cizKayitli(); }
    if (b.dataset.s === "istatistik") cizIstatistik();
    window.scrollTo(0, 0);
  };
});

/* ---------- arama ---------- */
let zaman = null;
el("#q").addEventListener("input", () => { clearTimeout(zaman); zaman = setTimeout(ara, 180); });
el("#grupSuz").onchange = ara;
el("#sadeceCok").onchange = ara;
el("#sirala").onchange = ara;

function ara() {
  const ham = el("#q").value.trim();
  const grup = el("#grupSuz").value;
  const sadeceCok = el("#sadeceCok").checked;
  if (ham.length < 2 && !grup) {
    el("#sonuclar").innerHTML = '<div class="bos">Ürün aramak için yukarıya yazın.</div>';
    return;
  }
  const kelimeler = sade(ham).split(/\s+/).filter(Boolean);
  const bulunan = [];
  for (let i = 0; i < U.length; i++) {
    if (grup && U[i][2] !== grup) continue;
    if (sadeceCok && U[i][6].length < 2) continue;
    const metin = ARAMA[i];
    let uyar = true;
    for (const k of kelimeler) { if (!metin.includes(k)) { uyar = false; break; } }
    if (uyar) bulunan.push(i);
  }
  if (!bulunan.length) {
    el("#sonuclar").innerHTML =
      '<div class="bos">Sonuç yok.<br><span style="font-size:12px">' +
      '“sadece 2+ markette olanlar” işaretliyse kaldırmayı deneyin.</span></div>';
    return;
  }

  const gosterilecek = sirala(bulunan, el("#sirala").value).slice(0, 120);
  el("#sonuclar").innerHTML =
    '<div class="kart">' + gosterilecek.map(urunSatiri).join("") + "</div>" +
    (bulunan.length > 120
      ? `<div class="bos" style="padding:12px">${bulunan.length} sonuçtan ilk 120'si
         gösteriliyor. Aramayı daraltın.</div>` : "");
  bagla(el("#sonuclar"));
}

function urunSatiri(i) {
  const u = U[i], teklif = u[6];
  const ucuz = teklif[0], pahali = teklif[teklif.length - 1];
  const fark = pahali[1] - ucuz[1];
  const oran = pahali[1] ? Math.round((fark / pahali[1]) * 100) : 0;
  const sepette = sepet.some((k) => k.i === i);
  const yildizli = favori.includes(i);
  const birim = birimYaz(i, ucuz[1]);
  return `<div class="urun">
    <button class="yildiz ${yildizli ? "dolu" : ""}" data-y="${i}"
            title="Favorilere ekle">${yildizli ? "★" : "☆"}</button>
    <div class="bilgi">
      <div class="ad">${kacir(u[0])}</div>
      <div class="alt">
        <span class="rozet ${teklif.length > 1 ? "iyi" : ""}">${teklif.length} markette</span>
        ${fark > 0 ? `<span class="rozet firsat">%${oran} fark</span>` : ""}
        ${u[7] ? `<span class="rozet">${kacir(BOY_ADI[u[7]] || u[7])}</span>` : ""}
        ${u[8] ? `<span class="rozet">${kacir(nitelikYaz(u[8]))}</span>` : ""}
        ${kacir(u[1])}${birim ? " · " + birim : ""}
      </div>
      <div class="alt">en ucuz: <b>${kacir(MARKET[ucuz[0]])}</b>${
        teklif.length > 1 ? ` · en pahalı: ${kacir(MARKET[pahali[0]])} ${para(pahali[1])}` : ""}</div>
    </div>
    <div class="fiyat"><b>${para(ucuz[1])}</b></div>
    <button class="ekle ${sepette ? "eklendi" : ""}" data-i="${i}">${sepette ? "✓" : "Ekle"}</button>
  </div>`;
}

function bagla(kapsayici) {
  kapsayici.querySelectorAll(".ekle[data-i]").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.i;
      const yer = sepet.findIndex((k) => k.i === i);
      if (yer >= 0) sepet.splice(yer, 1); else sepet.push({i: i, adet: 1});
      kaydet();
      b.classList.toggle("eklendi");
      b.textContent = b.classList.contains("eklendi") ? "✓" : "Ekle";
    };
  });
  kapsayici.querySelectorAll(".yildiz").forEach((b) => {
    b.onclick = () => {
      const i = +b.dataset.y;
      const yer = favori.indexOf(i);
      if (yer >= 0) favori.splice(yer, 1); else favori.push(i);
      favKaydet();
      b.classList.toggle("dolu");
      b.textContent = b.classList.contains("dolu") ? "★" : "☆";
      if (kapsayici.id === "favoriListe") cizFavoriler();
    };
  });
}

/* ---------- favoriler ---------- */
function favKaydet() {
  localStorage.setItem("marketFavori", JSON.stringify(favori));
  el("#favSayi").textContent = favori.length;
  favSunucuyaBildir();
}

function cizFavoriler() {
  el("#favAraclar").style.display = favori.length ? "flex" : "none";
  if (!favori.length) {
    el("#favoriListe").innerHTML =
      '<div class="bos">Henüz favoriniz yok.<br>' +
      '<span style="font-size:12px">Arama sonuçlarında ürünün solundaki ☆ işaretine ' +
      'dokunun. Düzenli aldıklarınızı favorileyin, bir daha aramanız gerekmez.</span></div>';
    return;
  }
  el("#favoriListe").innerHTML =
    '<div class="kart">' + sirala(favori, el("#favSirala").value).map(urunSatiri).join("") + "</div>";
  bagla(el("#favoriListe"));
}

el("#favHepsi").onclick = () => {
  favori.forEach((i) => { if (!sepet.some((k) => k.i === i)) sepet.push({i: i, adet: 1}); });
  kaydet();
  cizFavoriler();
  document.querySelector('.sekmeler button[data-s="sepet"]').click();
};

el("#favTemizle").onclick = () => {
  if (favori.length && confirm("Tüm favoriler silinsin mi?")) {
    favori = [];
    favKaydet();
    cizFavoriler();
  }
};

/* ---------- sepet ---------- */
function kaydet() {
  localStorage.setItem("marketSepet", JSON.stringify(sepet));
  el("#rozetSayi").textContent = sepet.length;
  el("#hesapla").disabled = sepet.length === 0;
  el("#altSay").textContent = sepet.length
    ? sepet.length + " kalem sepette"
    : "Sepet boş";
}

function cizSepet() {
  if (!sepet.length) {
    el("#sepetListe").innerHTML =
      '<div class="bos">Sepetiniz boş.<br>“Ara” sekmesinden ürün ekleyin.</div>';
    return;
  }
  el("#sepetListe").innerHTML = '<div class="kart">' + sepet.map((k, n) => {
    const u = U[k.i];
    return `<div class="urun">
      <div class="bilgi"><div class="ad">${kacir(u[0])}</div>
        <div class="alt">${kacir(u[1])} · ${u[6].length} markette</div></div>
      <div class="adet">
        <button data-eksi="${n}">−</button><span>${k.adet}</span><button data-arti="${n}">+</button>
      </div>
      <button class="sil" data-sil="${n}">×</button>
    </div>`;
  }).join("") + "</div>";

  el("#sepetListe").querySelectorAll("[data-arti]").forEach((b) => {
    b.onclick = () => { sepet[+b.dataset.arti].adet++; kaydet(); cizSepet(); };
  });
  el("#sepetListe").querySelectorAll("[data-eksi]").forEach((b) => {
    b.onclick = () => {
      const k = sepet[+b.dataset.eksi];
      if (k.adet > 1) { k.adet--; kaydet(); cizSepet(); }
    };
  });
  el("#sepetListe").querySelectorAll("[data-sil]").forEach((b) => {
    b.onclick = () => { sepet.splice(+b.dataset.sil, 1); kaydet(); cizSepet(); };
  });
}

/* ---------- optimizasyon ----------
   Her urunu en ucuzdan almak sizi 6 markete gonderir; yakit ve zaman
   tasarrufu yer. Bu yuzden ziyaret basina sabit maliyet ekleyip toplam
   gideri minimize ediyoruz. Market sayisi az oldugu icin TUM alt kumeleri
   deneyip kesin en iyiyi buluyoruz -- yaklasik cozum degil.            */

function secenekler(urunIndeksi, markaFarkOk) {
  const enUcuz = new Map();   // marketIndeksi -> {f: fiyat, j: urun, farkli: bool}
  const koy = (m, f, j, farkli) => {
    const v = enUcuz.get(m);
    // Esit fiyatta ayni markayi tercih et
    if (!v || f < v.f || (f === v.f && v.farkli && !farkli)) {
      enUcuz.set(m, {f: f, j: j, farkli: farkli});
    }
  };

  // 1) Ayni marka + ayni gramaj
  for (const j of GID.get(U[urunIndeksi][3]) || [urunIndeksi]) {
    for (const [m, f] of U[j][6]) koy(m, f, j, false);
  }

  // 2) Marka tutmuyorsa: ayni gramaj, farkli marka
  if (markaFarkOk && U[urunIndeksi][5] && U[urunIndeksi][4]) {
    const ana = ANA[urunIndeksi];
    const boy = U[urunIndeksi][7], nitelik = U[urunIndeksi][8] || "";
    for (const j of OLCU.get(U[urunIndeksi][4] + "|" + U[urunIndeksi][5]) || []) {
      if (j === urunIndeksi || U[j][3] === U[urunIndeksi][3]) continue;
      // Boy bilgisi ikisinde de varsa tutmali: M boy ile L boy ayni sey degil.
      if (boy && U[j][7] && boy !== U[j][7]) continue;
      // Organik / gezen / omega gibi nitelikler birebir tutmali.
      if ((U[j][8] || "") !== nitelik) continue;
      let ortak = false;
      for (const k of ANA[j]) if (ana.has(k)) { ortak = true; break; }
      if (!ortak) continue;   // "elma" ile "karpuz" muadil sayilmasin
      for (const [m, f] of U[j][6]) koy(m, f, j, true);
    }
  }
  return enUcuz;
}

function coz(maksMarket, ziyaret, markaFarkOk) {
  const kalemler = sepet.map((k) => ({
    i: k.i, adet: k.adet, sec: secenekler(k.i, markaFarkOk),
  })).filter((k) => k.sec.size > 0);

  const bulunamayan = sepet.filter((k) => secenekler(k.i, markaFarkOk).size === 0);
  if (!kalemler.length) return {hata: "Sepetteki ürünler için fiyat bulunamadı."};

  const marketSet = new Set();
  kalemler.forEach((k) => k.sec.forEach((_, m) => marketSet.add(m)));
  const marketler = [...marketSet].sort((a, b) => a - b);

  const genelMin = kalemler.map((k) => {
    let en = Infinity;
    k.sec.forEach((v) => { if (v.f * k.adet < en) en = v.f * k.adet; });
    return en;
  });

  let enIyi = null, enIyiTek = null, yedek = null;
  const n = marketler.length;

  for (let maske = 1; maske < (1 << n); maske++) {
    const boyut = popcount(maske);
    if (boyut > maksMarket) continue;

    const atamalar = [], eksikler = [];
    let toplam = 0;

    kalemler.forEach((k, idx) => {
      let enUcuzM = -1, enUcuzF = Infinity, enUcuzJ = -1, enUcuzFarkli = false;
      k.sec.forEach((v, m) => {
        const yer = marketler.indexOf(m);
        if (!(maske & (1 << yer))) return;
        const tutar = v.f * k.adet;
        if (tutar < enUcuzF) {
          enUcuzF = tutar; enUcuzM = m; enUcuzJ = v.j; enUcuzFarkli = v.farkli;
        }
      });
      if (enUcuzM < 0) { eksikler.push(k); toplam += genelMin[idx]; return; }
      toplam += enUcuzF;
      atamalar.push({kalem: k, market: enUcuzM, urun: enUcuzJ,
                     tutar: enUcuzF, farkli: enUcuzFarkli});
    });

    const kapsam = atamalar.length / kalemler.length;
    const maliyet = toplam + boyut * ziyaret;
    const aday = {maske, boyut, atamalar, eksikler, sepetTutar: toplam, maliyet, kapsam,
                  marketler: marketler.filter((_, y) => maske & (1 << y))};

    if (!yedek || kapsam > yedek.kapsam ||
        (kapsam === yedek.kapsam && maliyet < yedek.maliyet)) yedek = aday;

    // Kapsam esigi TEK marketlik planlara da uygulanir; aksi halde
    // "tek market daha ucuz" diye yaniltici bir kiyas cikiyor.
    if (kapsam < D.min_kapsam) continue;
    if (!enIyi || maliyet < enIyi.maliyet) enIyi = aday;
    if (boyut === 1 && (!enIyiTek || maliyet < enIyiTek.maliyet)) enIyiTek = aday;
  }

  const sonuc = enIyi || Object.assign(yedek, {kapsamUyarisi: true});
  sonuc.tek = enIyiTek;
  sonuc.tasarruf = enIyiTek ? enIyiTek.maliyet - sonuc.maliyet : null;
  sonuc.bulunamayan = bulunamayan;
  sonuc.kalemSayisi = kalemler.length;
  return sonuc;
}

function popcount(x) { let s = 0; while (x) { s += x & 1; x >>= 1; } return s; }

/* ---------- sonuc ekrani ---------- */
el("#hesapla").onclick = () => {
  document.querySelector('.sekmeler button[data-s="sonuc"]').click();
  cizSonuc();
};
el("#maks").onchange = cizSonuc;
el("#ziyaret").onchange = cizSonuc;

function cizSonuc() {
  if (!sepet.length) {
    el("#sonucIcerik").innerHTML = '<div class="bos">Sepete ürün ekleyip “Hesapla” deyin.</div>';
    return;
  }
  const r = coz(+el("#maks").value, +el("#ziyaret").value, el("#markaFark").checked);
  if (r.hata) { el("#sonucIcerik").innerHTML = `<div class="uyari">${kacir(r.hata)}</div>`; return; }

  let h = "";
  if (!r.tek) {
    h += `<div class="ozet duz"><div class="buyuk">${para(r.maliyet)}</div>
          <div class="kucuk">Tek marketle sepet tamamlanmıyor, kıyas yapılmadı.</div></div>`;
  } else if (r.tasarruf > 0.5) {
    h += `<div class="ozet"><div class="buyuk">${para(r.tasarruf)} tasarruf</div>
          <div class="kucuk">Tek markete (${kacir(MARKET[r.tek.marketler[0]])}) gitseydiniz
          ${para(r.tek.maliyet)} → bu dağılımla ${para(r.maliyet)}<br>
          ziyaret maliyeti dahil (${para(+el("#ziyaret").value)}/market)</div></div>`;
  } else {
    h += `<div class="ozet duz"><div class="buyuk">Tek markete gidin:
          ${kacir(MARKET[r.marketler[0]])}</div>
          <div class="kucuk">Gezmek yakıt ve zamana değmiyor. Dürüst cevap bu.</div></div>`;
  }

  const gruplu = new Map();
  r.atamalar.forEach((a) => {
    if (!gruplu.has(a.market)) gruplu.set(a.market, []);
    gruplu.get(a.market).push(a);
  });

  [...gruplu.entries()]
    .sort((a, b) => b[1].reduce((t, x) => t + x.tutar, 0) - a[1].reduce((t, x) => t + x.tutar, 0))
    .forEach(([m, liste]) => {
      const ara = liste.reduce((t, x) => t + x.tutar, 0);
      h += `<div class="kart market"><h3><span>${kacir(MARKET[m])}</span>
            <span>${liste.length} kalem · ${para(ara)}</span></h3>`;
      liste.forEach((a) => {
        const u = U[a.urun], k = a.kalem, istenen = U[k.i];
        const bf = birimYaz(a.urun, a.tutar / k.adet);
        h += `<div class="urun"><div class="bilgi">
                <div class="ad">${kacir(u[0])}${k.adet > 1 ? " ×" + k.adet : ""}</div>
                <div class="alt">${kacir(u[1])}${bf ? " · " + bf : ""}</div>`;
        const eTarih = (D.elle_tarih || {})[u[9] + "|" + (D.marketler || [])[m]];
        if (eTarih) {
          const y = gunFarki(eTarih);
          h += `<div class="alt" style="color:#a8710a">elle girildi:
                ${kacir(tarihYaz(eTarih))}${y !== null ? ` (${y} gün önce)` : ""}${
                  y !== null && y > 30 ? " — eskimiş olabilir" : ""}</div>`;
        }
        if (a.farkli) {
          h += `<div class="alt"><span class="rozet firsat">farklı marka</span>
                istediğiniz: ${kacir(istenen[0])} — aynı gramaj (${kacir(istenen[1])}),
                bu markette bu marka yok</div>`;
        } else if (a.urun !== k.i) {
          h += `<div class="alt">aynı ürünün bu marketteki karşılığı</div>`;
        }
        h += `</div><div class="fiyat"><b>${para(a.tutar)}</b></div></div>`;
      });
      h += "</div>";
    });

  h += `<div class="kart" style="padding:11px 12px;font-size:13px;color:#5a6472">
        Sepet tutarı <b>${para(r.sepetTutar)}</b> · ziyaret
        ${para(r.boyut * (+el("#ziyaret").value))} · toplam <b>${para(r.maliyet)}</b><br>
        ${r.atamalar.length}/${r.kalemSayisi} kalem karşılandı</div>`;

  if (r.eksikler.length || r.bulunamayan.length) {
    h += '<div class="uyari"><b>Bu listede yok:</b><br>';
    r.eksikler.forEach((k) => h += "• " + kacir(U[k.i][0]) + " — seçilen marketlerde yok<br>");
    r.bulunamayan.forEach((k) => h += "• " + kacir(U[k.i][0]) + " — fiyat bulunamadı<br>");
    h += "</div>";
  }
  if (r.kapsamUyarisi) {
    h += '<div class="uyari">Hiçbir market kombinasyonu sepetin yeterli kısmını ' +
         'karşılayamadı; en geniş kapsamlı plan gösteriliyor.</div>';
  }
  el("#sonucIcerik").innerHTML = h;
}

/* ---------- firsatlar ---------- */
function cizFirsatlar() {
  const grup = el("#firsatGrup").value;
  const liste = [];
  for (let i = 0; i < U.length; i++) {
    if (U[i][6].length < 2) continue;
    if (grup && U[i][2] !== grup) continue;
    liste.push(i);
  }
  if (!liste.length) {
    el("#firsatListe").innerHTML =
      '<div class="bos">Bu grupta iki markette birden bulunan ürün yok.</div>';
    return;
  }
  el("#firsatListe").innerHTML =
    '<div class="kart">' +
    sirala(liste, el("#firsatSirala").value).slice(0, 150).map(urunSatiri).join("") +
    "</div>" +
    (liste.length > 150 ? `<div class="bos" style="padding:12px">${liste.length}
      üründen ilk 150'si gösteriliyor.</div>` : "");
  bagla(el("#firsatListe"));
}

/* ---------- elle fiyat girisi ----------
   Telefonda da calisir: sunucu yoksa girisler cihazda birikir, "Kopyala"
   ile eve tasinir. Sunucu varsa dogrudan veritabanina yazilir.          */

let bekleyen = [];
try { bekleyen = JSON.parse(localStorage.getItem("marketElle") || "[]"); } catch (e) {}
if (!Array.isArray(bekleyen)) bekleyen = [];

// Market listesi elle_marketler.txt'ten geliyor; oraya satir ekleyip
// programi yeniden baslatinca burada da cikar.
el("#elleMarket").innerHTML = Object.entries(D.elle_marketler || {})
  .map(([kod, ad]) => `<option value="${kacir(kod)}">${kacir(ad)}</option>`).join("");
el("#elleKodlar").innerHTML = Object.entries(D.elle_marketler || {})
  .map(([kod, ad]) => `<code>${kacir(kod)}</code> = ${kacir(ad)}`).join(" &middot; ");

function bekleyenKaydet() {
  localStorage.setItem("marketElle", JSON.stringify(bekleyen));
  el("#elleRozet").textContent = bekleyen.length ? ` (${bekleyen.length})` : "";
  cizBekleyen();
}

async function elleGonder(kayit) {
  // Girisin tarihi kaydin kendisinde tasinsin: baskasina gonderildiginde
  // "eski fiyat yeniyi ezmesin" kurali ancak boyle isleyebilir.
  if (!kayit.tarih) kayit.tarih = new Date().toISOString().slice(0, 10);
  if (!sunucuVar) { bekleyen.push(kayit); bekleyenKaydet(); return {yerel: true}; }
  try {
    const r = await (await fetch("/api/elle", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(kayit)
    })).json();
    if (r.hata) { alert(r.hata); return {hata: r.hata}; }
    await cizKayitli();
    return r;
  } catch (e) {
    bekleyen.push(kayit); bekleyenKaydet();
    return {yerel: true};
  }
}

function cizBekleyen() {
  const kutu = el("#elleBekleyen");
  if (!bekleyen.length) { kutu.innerHTML = ""; return; }
  kutu.innerHTML = `<div class="uyari"><b>${bekleyen.length} giriş bu cihazda bekliyor.</b>
    <div class="kucuk" style="margin-top:4px">Evde bilgisayardaki sayfayı açın,
    “Telefondan gelen girişleri içeri al” bölümüne yapıştırın.</div>
    <div style="margin-top:8px">` +
    bekleyen.map((k, i) => `<div class="urun" style="padding:5px 0">
      <div class="bilgi"><div class="ad">${kacir(k.baslik || (U[k._i] && U[k._i][0]) || "?")}</div>
      <div class="alt">${kacir(k.market)} · ${para(+k.fiyat)}</div></div>
      <button class="sil" data-bek="${i}">×</button></div>`).join("") +
    `</div><button class="birincil" id="elleKopyala">Kopyala</button></div>`;

  kutu.querySelectorAll("[data-bek]").forEach((b) => {
    b.onclick = () => { bekleyen.splice(+b.dataset.bek, 1); bekleyenKaydet(); };
  });
  el("#elleKopyala").onclick = async () => {
    const metin = JSON.stringify(bekleyen);
    try {
      await navigator.clipboard.writeText(metin);
      alert("Kopyalandı. Bilgisayardaki sayfaya yapıştırın.");
    } catch (e) {
      prompt("Bu metni kopyalayın:", metin);
    }
  };
}

async function cizKayitli() {
  if (!sunucuVar) { el("#elleKayitli").innerHTML = ""; return; }
  let liste = [];
  try { liste = await (await fetch("/api/elle")).json(); } catch (e) { return; }
  if (!liste.length) { el("#elleKayitli").innerHTML = ""; return; }
  el("#elleKayitli").innerHTML =
    `<b style="font-size:13px">Kayıtlı elle fiyatlar (${liste.length})</b>
     <div class="kart" style="margin-top:6px">` + liste.map((k) => {
      const eski = k.yas_gun > 30;
      return `<div class="urun">
        <div class="bilgi"><div class="ad">${kacir(k.baslik)}</div>
        <div class="alt"><span class="rozet ${eski ? "firsat" : "iyi"}">${kacir(k.market_adi)}</span>
        ${k.gramaj ? kacir(k.gramaj) + " · " : ""}<b>${kacir(tarihYaz(k.tarih))}</b>
        · ${k.yas_gun} gün önce${eski ? " — güncelleyin" : ""}</div></div>
        <div class="fiyat"><b>${para(k.fiyat)}</b></div>
        <button class="sil" data-sil-id="${kacir(k.urun_id)}"
                data-sil-m="${kacir(k.market)}">×</button></div>`;
    }).join("") + "</div>";

  el("#elleKayitli").querySelectorAll("[data-sil-id]").forEach((b) => {
    b.onclick = async () => {
      await fetch("/api/elle/sil", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({urun_id: b.dataset.silId, market: b.dataset.silM})});
      cizKayitli();
    };
  });
}

/* ---------- istatistik ----------
   Iki kaynak var:
     * Bugunku veri (U dizisi) -> market kazanma oranlari, kategori farklari
     * Zaman serisi (D.ist)    -> gunluk medyan birim fiyat gecmisi
   Ikincisi her cekimde birikiyor; bugun tek gun varsa grafik yerine
   "kac gun sonra anlamli olacak" bilgisi gosterilir.                      */

let istCizildi = false;

function cizIstatistik() {
  if (istCizildi) return;
  istCizildi = true;

  // --- bugunku veriden hesaplananlar ---
  const kazanan = new Array(MARKET.length).fill(0);   // kac uruntte en ucuz
  const varlik  = new Array(MARKET.length).fill(0);   // kac urunde bulunuyor
  const grupBilgi = new Map();
  let karsilastirilabilir = 0, farkToplam = 0, oranToplam = 0;

  for (const u of U) {
    const t = u[6];
    t.forEach((p) => varlik[p[0]]++);
    if (t.length > 1) {
      karsilastirilabilir++;
      kazanan[t[0][0]]++;
      const fark = t[t.length - 1][1] - t[0][1];
      const oran = t[t.length - 1][1] ? fark / t[t.length - 1][1] : 0;
      farkToplam += fark; oranToplam += oran;
      const g = grupBilgi.get(u[2]) || {n: 0, oran: 0, fark: 0};
      g.n++; g.oran += oran; g.fark += fark;
      grupBilgi.set(u[2], g);
    }
  }

  const ortOran = karsilastirilabilir ? oranToplam / karsilastirilabilir : 0;
  const ortFark = karsilastirilabilir ? farkToplam / karsilastirilabilir : 0;

  let h = `<div class="kart" style="padding:14px">
    <h3 style="margin:0 0 10px;font-size:15px">Genel</h3>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px">
      ${[["Ürün", U.length.toLocaleString("tr-TR")],
         ["Market", MARKET.length],
         ["Karşılaştırılabilir", karsilastirilabilir.toLocaleString("tr-TR")],
         ["Ortalama fark", "%" + Math.round(ortOran * 100)],
         ["Ortalama tutar farkı", para(ortFark)],
         ["Fiyat tarihi", tarihYaz(D.tarih)]].map(([a, b]) =>
        `<div><div class="kucuk">${a}</div>
         <div style="font-size:19px;font-weight:700">${b}</div></div>`).join("")}
    </div></div>`;

  // --- market siralamasi ---
  const siralama = MARKET.map((ad, i) => ({
    ad, i, kazanan: kazanan[i], varlik: varlik[i],
    oran: varlik[i] ? kazanan[i] / varlik[i] : 0,
  })).sort((a, b) => b.kazanan - a.kazanan);
  const enCok = Math.max(...siralama.map((s) => s.kazanan), 1);

  h += `<div class="kart" style="padding:14px;margin-top:12px">
    <h3 style="margin:0 0 4px;font-size:15px">Hangi market daha sık ucuz</h3>
    <div class="kucuk" style="margin-bottom:10px">Birden fazla markette bulunan
      ${karsilastirilabilir.toLocaleString("tr-TR")} üründe, kaçında en ucuz olduğu.</div>` +
    siralama.map((s) => `
      <div style="margin-bottom:9px">
        <div style="display:flex;justify-content:space-between;font-size:13px">
          <b>${kacir(s.ad)}</b>
          <span>${s.kazanan.toLocaleString("tr-TR")} üründe en ucuz
            <span class="kucuk">· ${s.varlik.toLocaleString("tr-TR")} üründe var</span></span>
        </div>
        <div style="background:#eef1f5;border-radius:99px;height:8px;margin-top:3px">
          <div style="background:#0b7a3b;height:100%;border-radius:99px;
               width:${(s.kazanan / enCok * 100).toFixed(1)}%"></div>
        </div>
      </div>`).join("") + "</div>";

  // --- kategori farklari ---
  const gruplar = [...grupBilgi.entries()]
    .filter(([, g]) => g.n >= 5)
    .map(([ad, g]) => ({ad, n: g.n, oran: g.oran / g.n, fark: g.fark / g.n}))
    .sort((a, b) => b.oran - a.oran).slice(0, 20);

  h += `<div class="kart" style="padding:14px;margin-top:12px">
    <h3 style="margin:0 0 4px;font-size:15px">Marketler arası farkın en büyük olduğu kategoriler</h3>
    <div class="kucuk" style="margin-bottom:8px">Aynı ürünün marketten markete
      ne kadar değiştiği. Yüksek olanlarda market seçimi çok kazandırır.</div>
    <table><tr><th>Kategori</th><th class="sag">Ürün</th>
      <th class="sag">Ort. fark</th><th class="sag">Tutar</th></tr>` +
    gruplar.map((g) => `<tr><td>${kacir(g.ad)}</td>
      <td class="sag kucuk">${g.n}</td>
      <td class="sag"><b>%${Math.round(g.oran * 100)}</b></td>
      <td class="sag kucuk">${para(g.fark)}</td></tr>`).join("") + "</table></div>";

  // --- zaman serisi ---
  h += cizZamanSerisi();

  el("#istIcerik").innerHTML = h;
  el("#istIcerik").querySelectorAll(".seriSec").forEach((s) => {
    s.onchange = () => { istCizildi = false; seriGrup = s.value; cizIstatistik(); };
  });
}

let seriGrup = "";

function cizZamanSerisi() {
  const ist = D.ist || {gunler: []};
  const gun = ist.gunler || [];

  if (gun.length < 2) {
    return `<div class="kart" style="padding:14px;margin-top:12px">
      <h3 style="margin:0 0 6px;font-size:15px">Zaman içindeki değişim</h3>
      <div class="kucuk">Şu ana kadar <b>${gun.length} gün</b> kayıt var.
      Zaman grafiği için en az iki güne ihtiyaç var; her gün otomatik olarak
      bir gün ekleniyor. Bir hafta sonra haftalık, bir ay sonra aylık değişimi
      buradan göreceksiniz.<br><br>
      Kaydedilenler: her kategori ve market için günlük medyan birim fiyat,
      ayrıca favori ürünlerinizin tam fiyatı.</div></div>`;
  }

  const seri = seriGrup ? (ist.grup[seriGrup] || {}) : (ist.market || {});
  const kodlar = Object.keys(seri);
  const tumDeger = kodlar.flatMap((k) => seri[k].filter((v) => v != null));
  if (!tumDeger.length) return "";

  const enAz = Math.min(...tumDeger), enCok = Math.max(...tumDeger);
  const G = 640, Y = 190, kenar = 34;
  const x = (i) => kenar + i * (G - kenar * 2) / Math.max(1, gun.length - 1);
  const y = (v) => Y - 22 - (v - enAz) / (enCok - enAz || 1) * (Y - 48);
  const renk = ["#0b7a3b", "#b3261e", "#1a56c4", "#a8710a", "#6b2fb3",
                "#0f7b8a", "#b3005c", "#4a5568"];

  let svg = `<svg viewBox="0 0 ${G} ${Y}" style="width:100%;height:auto">
    <line x1="${kenar}" y1="${Y - 22}" x2="${G - kenar}" y2="${Y - 22}"
          stroke="#d9dee6"/>`;
  kodlar.forEach((k, n) => {
    const noktalar = seri[k].map((v, i) => v == null ? null : `${x(i)},${y(v)}`)
                            .filter(Boolean).join(" ");
    if (noktalar) {
      svg += `<polyline points="${noktalar}" fill="none"
               stroke="${renk[n % renk.length]}" stroke-width="2"
               stroke-linejoin="round"/>`;
    }
  });
  svg += `<text x="${kenar}" y="12" font-size="10" fill="#7b8494">${
            para(enCok)}</text>
          <text x="${kenar}" y="${Y - 6}" font-size="10" fill="#7b8494">${
            tarihYaz(gun[0])}</text>
          <text x="${G - kenar}" y="${Y - 6}" font-size="10" fill="#7b8494"
            text-anchor="end">${tarihYaz(gun[gun.length - 1])}</text></svg>`;

  const gosterge = kodlar.map((k, n) =>
    `<span style="white-space:nowrap;margin-right:10px;font-size:12px">
      <span style="display:inline-block;width:10px;height:3px;vertical-align:middle;
       background:${renk[n % renk.length]}"></span>
      ${kacir(MARKET_KOD[k] || k)}</span>`).join("");

  const gruplar = Object.keys(ist.grup || {}).sort();
  return `<div class="kart" style="padding:14px;margin-top:12px">
    <h3 style="margin:0 0 4px;font-size:15px">Zaman içindeki değişim</h3>
    <div class="kucuk">Günlük medyan birim fiyat. ${gun.length} günlük kayıt.</div>
    <div class="ayar" style="margin:8px 0">
      <label>Kapsam: <select class="seriSec">
        <option value="">Tüm katalog</option>
        ${gruplar.map((g) => `<option value="${kacir(g)}"${
          g === seriGrup ? " selected" : ""}>${kacir(g)}</option>`).join("")}
      </select></label>
    </div>
    ${svg}<div style="margin-top:6px">${gosterge}</div></div>`;
}

/* ---------- dosyadan toplu aktarma ----------
   Bicim:  [market]  satiri o noktadan sonrasinin marketini belirler,
           [tarih: YYYY-AA-GG] giris tarihini,
           kalan satirlar "urun adi | fiyat".
   Urun adi katalogla eslestirilir; eslesmezse yeni urun olarak eklenir.  */

function toplu_coz(metin) {
  const kodlar = Object.keys(D.elle_marketler || {});
  let market = kodlar[0] || "file";
  let tarih = null;
  const kayitlar = [], hatalar = [];

  metin.split(/\r?\n/).forEach((ham, i) => {
    const s = ham.trim();
    if (!s || s.startsWith("#")) return;

    const basliksatiri = s.match(/^\[\s*([^\]]+?)\s*\]$/);
    if (basliksatiri) {
      const ic = basliksatiri[1].trim();
      const t = ic.match(/^tarih\s*[:=]\s*(\d{4}-\d{2}-\d{2})$/i);
      if (t) { tarih = t[1]; return; }
      const kod = sade(ic);
      if (kodlar.includes(kod)) { market = kod; }
      else hatalar.push(`Satır ${i + 1}: bilinmeyen market “${ic}”`);
      return;
    }

    const parca = s.split(/\s*[|;\t]\s*/).filter((x) => x !== "");
    if (parca.length < 2) {
      hatalar.push(`Satır ${i + 1}: ayırıcı ( | ) yok — ${s}`);
      return;
    }

    // "market | urun | fiyat" bicimi de kabul edilir
    let satirMarket = market;
    let alanlar = parca;
    if (parca.length >= 3 && kodlar.includes(sade(parca[0]))) {
      satirMarket = sade(parca[0]);
      alanlar = parca.slice(1);
    }

    const fiyat = parseFloat(
      alanlar[alanlar.length - 1].replace(/[^\d.,]/g, "").replace(",", ".")
    );
    if (!fiyat || fiyat <= 0) {
      hatalar.push(`Satır ${i + 1}: fiyat okunamadı — ${s}`);
      return;
    }

    const ad = alanlar.slice(0, -1).join(" ").trim();
    if (!ad) { hatalar.push(`Satır ${i + 1}: ürün adı boş`); return; }

    kayitlar.push({satir: i + 1, ad, market: satirMarket, fiyat, tarih});
  });

  return {kayitlar, hatalar};
}

// Yazdiginiz metinden miktar cikarir: "1 Lt" -> [1, "lt"], "500 Gr" -> [0.5, "kg"]
const BIRIM_CARPAN = {
  kg: [1, "kg"], kilo: [1, "kg"], gr: [0.001, "kg"], g: [0.001, "kg"], gram: [0.001, "kg"],
  lt: [1, "lt"], l: [1, "lt"], litre: [1, "lt"], ml: [0.001, "lt"], cl: [0.01, "lt"],
  adet: [1, "adet"], adetli: [1, "adet"], li: [1, "adet"], lu: [1, "adet"],
};

function miktarCoz(metin) {
  const m = sade(metin).match(
    /(\d+(?:[.,]\d+)?)\s*(kg|kilo|gram|gr|litre|lt|ml|cl|adetli|adet|li|lu|g|l)\b/);
  if (!m) return null;
  const c = BIRIM_CARPAN[m[2]];
  if (!c) return null;
  return [parseFloat(m[1].replace(",", ".")) * c[0], c[1]];
}

/*  Once yazdiginiz kelimelerin hepsini iceren urunler bulunur, sonra
    sirasiyla daraltilir:
      1) basligi birebir ayni olan
      2) gramaji yazdiginizla ayni olan
      3) fazladan kelimesi en az olan (en sade eslesme)
    Tek aday kalmazsa hepsi dondurulur ve arayuz size sectirir.          */
function toplu_eslestir(ad) {
  const k = sade(ad).split(/\s+/).filter(Boolean);
  if (!k.length) return [];

  let aday = [];
  for (let i = 0; i < U.length; i++) {
    if (k.every((x) => ARAMA[i].includes(x))) {
      aday.push(i);
      if (aday.length > 60) break;
    }
  }
  if (aday.length <= 1) return aday;

  const hedef = sade(ad);
  const tam = aday.filter((i) => sade(U[i][0]) === hedef);
  if (tam.length === 1) return tam;

  const mik = miktarCoz(ad);
  if (mik) {
    const ayni = aday.filter(
      (i) => U[i][4] === mik[1] && Math.abs((U[i][5] || 0) - mik[0]) < 0.0005);
    if (ayni.length === 1) return ayni;
    if (ayni.length) aday = ayni;
  }

  // En sade eslesme: basliginda fazladan kelime en az olan
  aday.sort((a, b) => sade(U[a][0]).split(/\s+/).length -
                      sade(U[b][0]).split(/\s+/).length);
  const enKisa = sade(U[aday[0]][0]).split(/\s+/).length;
  const esKisa = aday.filter((i) => sade(U[i][0]).split(/\s+/).length === enKisa);
  if (esKisa.length === 1) return esKisa;

  return aday.slice(0, 8);
}

/*  Girilen fiyat, o urunun bilinen fiyatlarindan asiri sapiyorsa uyarir.
    Iki tipik hatayi yakalar:
      * ekran goruntusunden yanlis okunan rakam (149,00 -> 14,90)
      * satir toplaminin birim fiyat sanilmasi (0,5 kg tutari girilmesi)
    Uyari engellemez, sadece isaretler -- gercekten uc fiyatlar da olabilir. */
function supheli(urunIndeksi, fiyat) {
  const t = U[urunIndeksi][6];
  if (!t || !t.length) return null;
  const enUcuz = t[0][1], enPahali = t[t.length - 1][1];
  if (fiyat < enUcuz / 2.5) {
    return `çok düşük — bu ürün en ucuz ${para(enUcuz)}. Satır toplamı girmiş olabilirsiniz`;
  }
  if (fiyat > enPahali * 2.5) {
    return `çok yüksek — bu ürün en pahalı ${para(enPahali)}. Rakam yanlış okunmuş olabilir`;
  }
  return null;
}

let topluHazir = [];

function toplu_onizle(metin) {
  const {kayitlar, hatalar} = toplu_coz(metin);
  topluHazir = [];

  if (!kayitlar.length && !hatalar.length) {
    el("#elleOnizleme").innerHTML = '<div class="bos">Okunacak satır yok.</div>';
    return;
  }

  let h = "";
  if (hatalar.length) {
    h += '<div class="uyari"><b>Okunamayan satırlar:</b><br>' +
         hatalar.map(kacir).join("<br>") + "</div>";
  }

  let belirsizSayisi = 0;
  const satirlar = kayitlar.map((k, sira) => {
    const bul = toplu_eslestir(k.ad);
    const marketAdi = (D.elle_marketler || {})[k.market] || k.market;
    let ekMenu = "";
    let durum, aciklama;

    if (bul.length === 1) {
      durum = "eslesti";
      aciklama = U[bul[0]][0];
      // Ekran goruntusunden okunan fiyatlarda iki hata sik: rakam yanlis
      // okunmasi ve satir toplaminin birim fiyat sanilmasi. Ikisi de
      // fiyati mevcutlardan cok uzaga dusurur -- yakalayip uyaralim.
      const s = supheli(bul[0], k.fiyat);
      if (s) { durum = "supheli"; aciklama = U[bul[0]][0] + " — " + s; }
      topluHazir.push({urun_id: U[bul[0]][9], baslik: U[bul[0]][0],
                       market: k.market, fiyat: k.fiyat, tarih: k.tarih});
    } else if (bul.length > 1) {
      // Karar veremedik: kullaniciya sectirelim, dosyayi duzelttirmeyelim
      durum = "belirsiz";
      belirsizSayisi++;
      aciklama = `${bul.length} olası ürün — hangisi?`;
      ekMenu = `<select class="topluSec" data-sira="${sira}"
                   data-market="${kacir(k.market)}" data-fiyat="${k.fiyat}"
                   data-tarih="${kacir(k.tarih || "")}"
                   style="width:100%;margin-top:5px;font-size:12px">
          <option value="">— seçilmedi, aktarılmayacak —</option>` +
        bul.map((i) => `<option value="${i}">${kacir(U[i][0])}${
          U[i][1] ? " (" + kacir(U[i][1]) + ")" : ""}</option>`).join("") +
        `<option value="yeni">yeni ürün olarak ekle: ${kacir(k.ad)}</option></select>`;
    } else {
      durum = "yeni";
      aciklama = "katalogda yok — yeni ürün olarak eklenecek";
      topluHazir.push({baslik: k.ad, marka: "", gramaj: "",
                       market: k.market, fiyat: k.fiyat, tarih: k.tarih});
    }

    const renk = {eslesti: "iyi", yeni: "", belirsiz: "firsat", supheli: "firsat"}[durum];
    const isaret = {eslesti: "✓", yeni: "＋", belirsiz: "?", supheli: "⚠"}[durum];
    return `<div class="urun" style="align-items:flex-start">
      <div class="bilgi"><div class="ad">${isaret} ${kacir(k.ad)}</div>
        <div class="alt"><span class="rozet ${renk}">${kacir(marketAdi)}</span>${
          kacir(aciklama)}</div>${ekMenu}</div>
      <div class="fiyat"><b>${para(k.fiyat)}</b></div></div>`;
  }).join("");

  h += `<div class="kart" style="margin-top:8px">${satirlar}</div>`;
  h += `<div class="kucuk" style="margin-top:8px" id="elleSayac">
        ${topluHazir.length} kayıt aktarılmaya hazır` +
       (belirsizSayisi ? `, <b>${belirsizSayisi} satır için seçim bekleniyor</b>` : "") +
       "</div>";
  if (topluHazir.length) {
    h += `<button class="birincil" id="elleTopluAktar">
          ${topluHazir.length} kaydı aktar</button>`;
  }

  el("#elleOnizleme").innerHTML = h;

  // Belirsiz satirlarda yapilan secimler listeye eklenir/cikarilir
  const secimler = new Map();
  el("#elleOnizleme").querySelectorAll(".topluSec").forEach((s) => {
    s.onchange = () => {
      const sira = s.dataset.sira;
      const onceki = secimler.get(sira);
      if (onceki) {
        const yer = topluHazir.indexOf(onceki);
        if (yer >= 0) topluHazir.splice(yer, 1);
        secimler.delete(sira);
      }
      const d = s.value;
      if (d) {
        const ortak = {market: s.dataset.market, fiyat: +s.dataset.fiyat,
                       tarih: s.dataset.tarih || null};
        const kayit = d === "yeni"
          ? Object.assign({baslik: s.closest(".urun").querySelector(".ad")
                             .textContent.replace(/^[?＋✓]\s*/, "").trim(),
                           marka: "", gramaj: ""}, ortak)
          : Object.assign({urun_id: U[+d][9], baslik: U[+d][0]}, ortak);
        topluHazir.push(kayit);
        secimler.set(sira, kayit);
      }
      const bekleyenSecim = el("#elleOnizleme").querySelectorAll(".topluSec").length
                            - secimler.size;
      el("#elleSayac").innerHTML = `${topluHazir.length} kayıt aktarılmaya hazır` +
        (bekleyenSecim ? `, <b>${bekleyenSecim} satır için seçim bekleniyor</b>` : "");
      const d2 = el("#elleTopluAktar");
      if (d2) {
        d2.textContent = `${topluHazir.length} kaydı aktar`;
        d2.disabled = topluHazir.length === 0;
      }
    };
  });

  const dugme = el("#elleTopluAktar");
  if (dugme) dugme.onclick = async () => {
    dugme.disabled = true;
    const sayac = {eklendi: 0, guncellendi: 0, atlandi: 0, yerel: 0, hata: 0};
    for (const kayit of topluHazir) {
      const r = await elleGonder(kayit);
      if (r.yerel) sayac.yerel++;
      else if (r.hata) sayac.hata++;
      else sayac[r.durum || "eklendi"]++;
    }
    let ozet = sayac.yerel
      ? `${sayac.yerel} kayıt bu cihazda biriktirildi (sunucu yok).`
      : `${sayac.eklendi} yeni, ${sayac.guncellendi} güncellendi` +
        (sayac.atlandi ? `, ${sayac.atlandi} atlandı (mevcut kayıt daha yeni)` : "") +
        (sayac.hata ? `, ${sayac.hata} hata` : "");
    alert(ozet + "\n\nYeni fiyatlar için sayfayı yenileyin (F5).");
    el("#elleToplu").value = "";
    el("#elleOnizleme").innerHTML = "";
    topluHazir = [];
    cizElleFavoriler(); cizKayitli();
  };
}

el("#elleOnizle").onclick = () => toplu_onizle(el("#elleToplu").value);

el("#elleDosya").onchange = (olay) => {
  const dosya = olay.target.files && olay.target.files[0];
  if (!dosya) return;
  const okuyucu = new FileReader();
  okuyucu.onload = () => {
    el("#elleToplu").value = okuyucu.result;
    toplu_onizle(okuyucu.result);
  };
  okuyucu.readAsText(dosya, "utf-8");
};

function cizElleFavoriler() {
  const kutu = el("#elleFavoriler");
  if (!favori.length) {
    kutu.innerHTML = '<div class="bos" style="padding:14px 0">' +
      'Favoriniz yok. “Ara” sekmesinde ürünlerin solundaki ☆ işaretine dokunun.</div>';
    return;
  }
  const mKod = el("#elleMarket").value;
  const mYer = (D.marketler || []).indexOf(mKod);

  kutu.innerHTML = '<div class="kart" style="margin-top:6px">' + favori.map((i) => {
    const u = U[i];
    // Bu markette daha once girilmis fiyat varsa gosterelim
    const mevcut = mYer >= 0 ? (u[6].find((p) => p[0] === mYer) || [])[1] : undefined;
    const enUcuz = u[6][0];
    const gt = (D.elle_tarih || {})[u[9] + "|" + mKod];
    const yas = gunFarki(gt);
    const eski = yas !== null && yas > 30;
    return `<div class="urun">
      <div class="bilgi">
        <div class="ad">${kacir(u[0])}</div>
        <div class="alt">${kacir(u[1])} · en ucuz
          <b>${kacir(MARKET[enUcuz[0]])} ${para(enUcuz[1])}</b></div>
        ${mevcut !== undefined ? `<div class="alt">
          <span class="rozet ${eski ? "firsat" : "iyi"}">kayıtlı ${para(mevcut)}</span>
          ${gt ? tarihYaz(gt) + (yas !== null ? ` · ${yas} gün önce` : "") : ""}${
            eski ? " — güncelleyin" : ""}</div>` : ""}
      </div>
      <input type="text" inputmode="decimal" placeholder="${
        mevcut !== undefined ? mevcut.toFixed(2) : "fiyat"}"
             data-fav="${i}" style="width:78px;padding:6px;font-size:14px;
             border:1px solid #c8cfd9;border-radius:7px;text-align:right">
      <button class="ekle" data-favkaydet="${i}">Kaydet</button>
    </div>`;
  }).join("") + "</div>";

  kutu.querySelectorAll("[data-favkaydet]").forEach((b) => {
    b.onclick = async () => {
      const i = +b.dataset.favkaydet;
      const g = kutu.querySelector(`[data-fav="${i}"]`);
      const f = (g.value || "").replace(",", ".");
      if (!f || isNaN(+f) || +f <= 0) { alert("Geçerli bir fiyat girin."); return; }
      const r = await elleGonder({urun_id: U[i][9], market: el("#elleMarket").value,
                                  fiyat: +f, baslik: U[i][0], _i: i});
      if (!r.hata) { g.value = ""; b.textContent = "✓"; b.classList.add("eklendi"); }
    };
  });
}

el("#elleMarket").onchange = cizElleFavoriler;

let elleZaman = null;
el("#elleAra").addEventListener("input", () => {
  clearTimeout(elleZaman);
  elleZaman = setTimeout(() => {
    const q = el("#elleAra").value.trim();
    if (q.length < 2) { el("#elleSonuc").innerHTML = ""; return; }
    const k = sade(q).split(/\s+/).filter(Boolean);
    const bul = [];
    for (let i = 0; i < U.length && bul.length < 25; i++) {
      if (k.every((x) => ARAMA[i].includes(x))) bul.push(i);
    }
    el("#elleSonuc").innerHTML = bul.length
      ? '<div class="kart" style="margin-top:6px">' + bul.map((i) => `<div class="urun">
          <div class="bilgi"><div class="ad">${kacir(U[i][0])}</div>
          <div class="alt">${kacir(U[i][1])} · en ucuz ${para(U[i][6][0][1])}</div></div>
          <input type="text" inputmode="decimal" placeholder="fiyat"
                 data-f="${i}" style="width:78px;padding:6px;font-size:14px;
                 border:1px solid #c8cfd9;border-radius:7px;text-align:right">
          <button class="ekle" data-kaydet="${i}">Kaydet</button></div>`).join("") + "</div>"
      : '<div class="bos">Sonuç yok — aşağıdaki “yeni ürün” bölümünü kullanın.</div>';

    el("#elleSonuc").querySelectorAll("[data-kaydet]").forEach((b) => {
      b.onclick = async () => {
        const i = +b.dataset.kaydet;
        const g = el("#elleSonuc").querySelector(`[data-f="${i}"]`);
        const f = (g.value || "").replace(",", ".");
        if (!f || isNaN(+f) || +f <= 0) { alert("Geçerli bir fiyat girin."); return; }
        const r = await elleGonder({urun_id: U[i][9], market: el("#elleMarket").value,
                                    fiyat: +f, baslik: U[i][0], _i: i});
        if (!r.hata) { g.value = ""; b.textContent = "✓"; b.classList.add("eklendi"); }
      };
    });
  }, 200);
});

el("#elleYeniEkle").onclick = async () => {
  const baslik = el("#elleBaslik").value.trim();
  const f = (el("#elleFiyat2").value || "").replace(",", ".");
  if (!baslik) { alert("Ürün adı girin."); return; }
  if (!f || isNaN(+f) || +f <= 0) { alert("Geçerli bir fiyat girin."); return; }
  const r = await elleGonder({
    baslik: baslik, marka: el("#elleMarka").value.trim(),
    gramaj: el("#elleGramaj").value.trim(),
    market: el("#elleMarket").value, fiyat: +f
  });
  if (!r.hata) {
    el("#elleBaslik").value = el("#elleMarka").value = "";
    el("#elleGramaj").value = el("#elleFiyat2").value = "";
    alert("Eklendi.");
  }
};

el("#elleIceAl").onclick = async () => {
  let kayitlar;
  try { kayitlar = JSON.parse(el("#elleYapistir").value.trim()); } catch (e) {
    alert("Metin okunamadı. Telefondaki “Kopyala” çıktısını olduğu gibi yapıştırın.");
    return;
  }
  if (!Array.isArray(kayitlar) || !kayitlar.length) { alert("Kayıt yok."); return; }

  const sayac = {eklendi: 0, guncellendi: 0, atlandi: 0, hata: 0};
  const atlananlar = [];
  for (const k of kayitlar) {
    const r = await (await fetch("/api/elle", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(k)})).json();
    if (r.hata) { sayac.hata++; continue; }
    sayac[r.durum || "eklendi"]++;
    if (r.durum === "atlandi") atlananlar.push(`${k.baslik || k.urun_id}: ${r.mesaj}`);
  }

  el("#elleYapistir").value = "";
  await cizKayitli();

  let ozet = `${sayac.eklendi} yeni, ${sayac.guncellendi} güncellendi`;
  if (sayac.atlandi) ozet += `, ${sayac.atlandi} atlandı (sizdeki kayıt daha yeni)`;
  if (sayac.hata) ozet += `, ${sayac.hata} hata`;
  if (atlananlar.length) ozet += "\n\nAtlananlar:\n" + atlananlar.slice(0, 8).join("\n");
  ozet += "\n\nYeni fiyatlar için sayfayı yenileyin (F5).";
  alert(ozet);
};

/* ---------- sunucu modu ----------
   Ayni dosya iki sekilde acilabiliyor:
     * file:// ile dogrudan (telefon, cevrimdisi) -> arkasinda program yok,
       fiyat cekilemez, guncelleme sekmesi gizli kalir
     * py uygulama.py ile sunucudan -> asagidaki yoklama tutar ve
       guncelleme sekmesi belirir
   Boylece tek bir arayuz var, iki ayri sayfa degil.                        */

let sunucuVar = false;
let cekZaman = null;

async function sunucuYokla() {
  try {
    const c = await fetch("/api/durum", {cache: "no-store"});
    if (!c.ok) return;
    const d = await c.json();
    sunucuVar = true;
    el("#sekmeGuncelle").style.display = "";
    el("#elleAktarKutu").style.display = "";
    el("#elleDurum").textContent =
      "Bilgisayardasınız — girdikleriniz doğrudan kaydedilir.";
    await cizKayitli();
    if (d.damga) {
      el("#ust").textContent += ` · marketlerin son güncellemesi ${d.damga}`;
    }
    await favSunucuyaBildir();
    const i = await (await fetch("/api/cekim")).json();
    if (i.calisiyor) { document.querySelector('[data-s="guncelle"]').click(); cekIzle(); }
  } catch (e) {
    sunucuVar = false;   // file:// ile acilmis, normal durum
    el("#elleDurum").textContent =
      "Telefondasınız — girişler bu cihazda birikir, evde bilgisayara aktarırsınız.";
  }
}

async function favSunucuyaBildir() {
  if (!sunucuVar) return;
  const kimlikler = favori.map((i) => U[i][9]).filter(Boolean);
  el("#favBilgi").textContent = kimlikler.length
    ? `${kimlikler.length} favori ürün — güncelleme bunlarla sınırlı olacak.`
    : "Henüz favori yok. “Ara” sekmesinde ☆ işaretine dokunun.";
  try {
    await fetch("/api/favori", {method: "POST", headers: {"Content-Type": "application/json"},
                                body: JSON.stringify(kimlikler)});
  } catch (e) { /* sunucu kapanmis olabilir */ }
}

async function cekBaslat(kapsam, onay) {
  if (!confirm(onay)) return;
  el("#cekHepsi").disabled = el("#cekFavori").disabled = true;
  try {
    const r = await (await fetch("/api/cekim", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({kapsam: kapsam})
    })).json();
    if (r.hata) { alert(r.hata); el("#cekHepsi").disabled = el("#cekFavori").disabled = false; return; }
  } catch (e) {
    alert("Sunucuya ulaşılamadı. py uygulama.py çalışıyor mu?");
    el("#cekHepsi").disabled = el("#cekFavori").disabled = false;
    return;
  }
  cekIzle();
}

async function cekIzle() {
  let d;
  try { d = await (await fetch("/api/cekim")).json(); } catch (e) { return; }

  const log = el("#cekLog");
  log.textContent = (d.satirlar || []).join("\n");
  log.scrollTop = log.scrollHeight;

  if (d.calisiyor) {
    el("#cekHepsi").disabled = el("#cekFavori").disabled = true;
    el("#cekHepsi").textContent = `Çekiliyor… (${d.toplam_satir} satır)`;
    clearTimeout(cekZaman);
    cekZaman = setTimeout(cekIzle, 2000);
    return;
  }

  el("#cekHepsi").disabled = el("#cekFavori").disabled = false;
  el("#cekHepsi").textContent = "Tüm sepeti çek (13–15 dk)";
  if (d.bitti && !d.hata) {
    log.textContent += "\n\nBitti. Yeni fiyatlar için sayfayı yenileyin (F5).";
  }
}

el("#cekHepsi").onclick = () => cekBaslat("hepsi",
  "Tüm sepet çekilecek, 13–15 dakika sürer. Başlatılsın mı?");

el("#cekFavori").onclick = () => {
  if (!favori.length) {
    alert("Henüz favoriniz yok. “Ara” sekmesinde ürünün solundaki ☆ işaretine dokunun.");
    return;
  }
  cekBaslat("favori",
    `${favori.length} favori ürünün fiyatı güncellenecek. Genellikle 1–3 dakika sürer. Başlatılsın mı?`);
};

kaydet();
favKaydet();
bekleyenKaydet();
sunucuYokla();
</script></body></html>"""


def sayfa_html(veri: dict | None = None) -> str | None:
    """
    Tam sayfayi (veri gomulu) metin olarak uretir.

    Hem dosyaya yazmak icin hem de uygulama.py'nin sunmasi icin kullanilir --
    boylece tek bir arayuz var, iki ayri kopya degil. Sayfa acildiginda
    /api/durum'u yoklayip sunucudan mi yoksa dosyadan mi acildigini anlar,
    guncelleme sekmesini ona gore gosterir.
    """
    veri = veri or veriyi_hazirla()
    if not veri:
        return None

    gomulu = json.dumps(veri, ensure_ascii=False, separators=(",", ":"))
    # </script> dizisi gomulu JSON icinde gecerse sayfayi bozar
    gomulu = gomulu.replace("</", "<\\/")
    return SAYFA.replace("__VERI__", gomulu)


def uret() -> None:
    veri = veriyi_hazirla()
    icerik = sayfa_html(veri)
    if icerik is None:
        yaz("Veritabaninda fiyat yok. Once calistirin:  py topla.py")
        return

    klasor = rapor.cikti_yolu().parent
    yol = klasor / "Market-Sepet.html"
    yol.write_text(icerik, encoding="utf-8")

    boyut = yol.stat().st_size / 1024
    yaz(f"{len(veri['urunler'])} urun, {len(veri['marketler'])} market gomuldu.")
    yaz(f"\nYazildi ({boyut:.0f} KB):\n  {yol}")
    yaz(f"\nTarayiciya yapistirin:\n  {yol.as_uri()}")
    if market.onedrive_koku():
        yaz("\nTelefondan: OneDrive uygulamasi -> Alisveris -> Market-Sepet.html")
        yaz("Cevrimdisi calisir, sepetiniz telefonda saklanir.")

    if "--ac" in sys.argv:
        import webbrowser
        webbrowser.open(yol.as_uri())
        yaz("\nTarayicida aciliyor...")


if __name__ == "__main__":
    uret()
