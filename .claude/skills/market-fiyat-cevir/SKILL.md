---
name: market-fiyat-cevir
description: Market uygulamasi ekran goruntulerindeki fiyatlari market-fiyat-bolu sisteminin toplu aktarma formatina cevirir. File, Ozdilek, Nuhmar, Basgimpa gibi API'de olmayan marketlerin fiyatlarini girmek icin. Kullanici ekran goruntusu, fotograf ya da fiyat listesi paylasip "bunu formata cevir", "fiyatlari aktar", "File fiyatlarini gir" dediginde kullanilir.
---

# Market fiyatlarını içeri aktarma formatına çevir

Kullanıcının paylaştığı market uygulaması ekran görüntülerini
`market-fiyat-bolu` sisteminin toplu aktarma biçimine çevir.

## Çıktı biçimi

Yalnızca listeyi yaz. Açıklama, giriş cümlesi, özet ekleme.

```
[tarih: YYYY-AA-GG]
[file]
Ürün Adı Gramaj | fiyat
Ürün Adı Gramaj | fiyat
```

Market kodları: `file` · `ozdilek` · `nuhmar` · `basgimpa` · `diger`

Birden fazla market varsa her biri için ayrı `[market]` başlığı aç.

## Kurallar

**1. Fiyat = birim fiyat. Satır toplamını asla yazma.**

Bu en kritik kural. Uygulamalar genelde sepetteki miktarın tutarını
gösterir, birim fiyatı değil.

| Ekranda görünen | Yazılacak |
|---|---|
| `0,5 kg · 59,90 TL/kg · 29,95 TL` | **59,90** |
| `4,5 kg · 49,90 TL/kg · 224,55 TL` | **49,90** |
| `1 ad · 94,90 TL` | **94,90** |

Kiloyla satılanlarda `TL/kg` değerini al. Adetle satılanlarda paketin
kendi fiyatını al.

**2. Ürün adına gramaj ekle.** Sistem gramajı isimden çözüyor; yoksa
birim fiyat hesaplanamaz ve ürün karşılaştırmaya giremez.

- Kiloyla satılan → `1 Kg` yaz: `Havuç 1 Kg | 59,90`
- Litreyle satılan → `1 Lt`
- Paketliyse paketin gramajı: `İstiridye Mantarı 200 Gr | 84,90`
- Adetliyse: `Ananas 1 Adet | 94,90`, `Yumurta M Boy 30 Adet | 129,00`

**3. Marka varsa başa yaz.** `Sütaş Tam Yağlı Süt 1 Lt | 42,50`
Marka + ürün + gramaj üçlüsü katalogla eşleşmeyi neredeyse kesinleştirir.

**4. Fiyatta yalnızca rakam.** `42,50` — TL, ₺ yazma. Ondalık ayracı
virgül ya da nokta olabilir.

**5. Ayırıcı tek dik çizgi:** `|`

**6. Okuyamadığın satırı atla, uydurma.** Emin olmadığın rakamı yazmak,
atlamaktan kötüdür — sistem yanlış fiyatla yanlış market önerir.

**7. Sonuna ürün sayısını not düş:** `# 27 ürün`

**8. Tarih.** Ekran görüntüsünde tarih varsa onu kullan. Yoksa kullanıcıya
sor ya da bugünü yaz.

## Çevirdikten sonra

Kullanıcıya şunu hatırlat: çıktıyı sayfadaki
**✎ Elle → 4) Dosyadan toplu aktar** kutusuna yapıştırıp **Önizle**'ye
bassın. Önizlemede **⚠** işaretli satır çıkarsa o fiyatı uygulamadan
doğrulasın — sistem, fiyatın bilinen fiyatlardan 2,5 kat saptığını
gördüğünde uyarıyor (yanlış okunan rakam ya da satır toplamı girilmiş
olabilir).

## Doğrulama

Çeviriyi bitirince, toplam tutarı hesaplayıp uygulamada görünen sepet
tutarıyla karşılaştırabiliyorsan karşılaştır. Tutmuyorsa hangi satırda
sorun olduğunu söyle. Ama bu doğrulamayı yaparken **satır toplamlarını**
kullan (miktar × birim fiyat), yazdığın birim fiyatları değil.

## Örnek

Girdi: File Market sepet ekran görüntüsü, 3 ürün.

Çıktı:

```
[tarih: 2026-07-30]
[file]
Havuç 1 Kg | 59,90
Starking Elma 1 Kg | 109,00
Ananas 1 Adet | 94,90
# 3 ürün
```
