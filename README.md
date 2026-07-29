# Bolu Merkez Market Fiyat Karşılaştırma

Bolu merkezdeki market şubelerinin fiyatlarını günlük çeker, aynı marka ve aynı
gramajdaki ürünleri karşılaştırır, hangi ürünü hangi marketten alacağınızı
hesaplar ve telefondan açabileceğiniz bir alışveriş listesi üretir.

**Kurulum gerektirmez.** Sadece Python standart kütüphanesi kullanır, `pip install`
yapmanıza gerek yoktur.

---

## Hızlı başlangıç

Önce fiyatları çekin (~13 dakika, günde bir kez yeter):

```bash
py topla.py
```

Sonra alışveriş sayfasını üretin:

```bash
py katalog.py --ac
```

Bu, **tek dosyalık bir alışveriş sitesi** üretir: `OneDrive\Alisveris\Market-Sepet.html`.
Sunucu gerekmez, internet gerekmez, telefonda da açılır. İçinde:

- **Ara** — ürün arayın, ☆ ile favorileyin, "Ekle" ile sepete atın
- **★ Favoriler** — düzenli aldıklarınız; "Hepsini sepete ekle" ile tek dokunuşta sepet
- **Sepet** — adet ayarlayın
- **Sonuç** — hangi ürün hangi markette, ne kadar tasarruf
- **Fırsat** — marketler arası farkı en büyük ürünler

Sepetiniz ve favorileriniz tarayıcıda saklanır; dosyayı kapatıp açsanız durur.

Her sayfada **7 farklı sıralama** var: birim fiyat, etiket fiyatı (ucuzdan/pahalıdan),
marketler arası fark (TL veya %), kaç markette bulunduğu, isim.

Arayüz istemiyorsanız `alisveris.txt` dosyasını elle düzenleyip:

```bash
py rapor.py
```

Her iki yolda da rapor şuraya yazılır:

```
OneDrive\Alisveris\Alisveris-Listesi.html
```

OneDrive telefonunuza senkronladığı için markette telefondan açabilirsiniz.
Dosya çevrimdışı da çalışır.

### Tüm komutlar

| Komut | Ne yapar |
|---|---|
| `py topla.py` | Fiyatları çeker |
| `py topla.py --grup Meyve Sebze` | Sadece o grupları çeker |
| `py topla.py --kesfet domates zeytin` | Kelimelerin hangi kategoride geçtiğini yazar |
| `py topla.py --adaylar` | Onay listesini çekim yapmadan tazeler |
| `py katalog.py` | Tek dosyalık alışveriş sayfasını üretir |
| `py katalog.py --ac` | Üretip tarayıcıda açar |
| `py uygulama.py` | Masaüstü arayüzü (sunucu gerektirir, telefonda çalışmaz) |
| `py rapor.py` | `alisveris.txt`'ten rapor üretir |
| `py rapor.py --ac` | Raporu üretip tarayıcıda açar |
| `py rapor.py --market 3` | En fazla 3 markete uğrama planı |
| `py rapor.py --yol` | HTML'in nereye yazıldığını söyler |

> **Raporu açarken:** adres çubuğuna `onedrive/Alisveris/...` yazmayın — tarayıcı
> onu internet adresi sanıp "Bu siteye ulaşılamıyor" der. Ya Dosya Gezgini'nden
> çift tıklayın, ya `py rapor.py --ac` kullanın, ya da `rapor.py`'nin yazdığı
> `file:///...` adresini yapıştırın.

---

## Veri kaynağı

[marketfiyati.org.tr](https://marketfiyati.org.tr) — TÜBİTAK BİLGEM tarafından
geliştirilen, Ticaret Bakanlığı destekli resmi fiyat karşılaştırma platformu.
Zincir marketler fiyatlarını buraya günlük bildiriyor.

Bolu merkezde (40.7350, 31.6080) taranan şubeler:

| Market | Şube |
|---|---|
| BİM | 5 |
| ŞOK | 5 |
| A101 | 5 |
| Migros | 5 |
| Tarım Kredi | 5 |
| CarrefourSA | 3 |

**Özdilek ve File bu kaynakta yok.** Bunlar için ayrı veri toplayıcı yazmak
gerekirdi; en kırılgan ve en pahalı parça o olduğu için kapsam dışı bırakıldı.
İhtiyaç duyarsanız o fiyatları elle ekleyebilirsiniz.

---

## Dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `sepet.txt` | **Hangi ürünlerin fiyatı takip edilecek.** Kategori ve arama kelimeleri. |
| `alisveris.txt` | **Bu hafta ne alacaksınız.** Market dağıtımı bunun üzerinden hesaplanır. |
| `beyaz_liste.txt` | **Onayladığınız temizlik/bakım ürünleri.** Boşsa hiçbiri önerilmez. |
| `beyaz_liste_adaylari.txt` | Her çekimde otomatik üretilir, onayınızı bekleyen ürünler. |
| `fiyatlar.db` | SQLite veritabanı. Fiyat geçmişi burada birikir. |
| `listem.json` | Arayüzde kurduğunuz liste. Otomatik kaydedilir. |
| `market.py` | Çekirdek: API istemcisi, normalizasyon, veritabanı. |
| `topla.py` | Fiyat çekici. |
| `rapor.py` | Karşılaştırma, optimizasyon, HTML üretimi. |
| `katalog.py` | Tek dosyalık, sunucusuz alışveriş sayfasını üretir. |
| `uygulama.py` | Masaüstü arayüzü (yerel sunucu). |

---

## Ürünler nasıl eşleştiriliyor

İki kademeli:

**1. Aynı marka + aynı gramaj** → "aynı ürün". En güvenilir karşılaştırma.

**2. Marka tutmuyorsa: aynı gramaj, farklı marka** → "farklı marka" rozetiyle gösterilir.

İkincisi olmadan bazı kategorilerde hiç karşılaştırma yapılamıyor. Örnek: Bolu'daki
**28 yumurta ürününden sadece 1'i** iki ayrı markette bulunuyor, çünkü her zincir
kendi markasını satıyor — Bili Bili sadece BİM'de, Anadolu Çiftliği sadece ŞOK'ta,
Keskinoğlu sadece Migros'ta. "Aynı marka" kuralı yumurtada hiç çalışmıyor.

Farklı marka eşleştirmesi şu şartların **hepsini** arar:

| Şart | Örnek |
|---|---|
| Aynı gramaj/adet | 30 adet ↔ 30 adet |
| Aynı boy | M boy ↔ 53-62 Gr (ikisi de M'ye çözülür), L ile eşleşmez |
| Aynı nitelik | organik ↔ organik; organik ile normal **eşleşmez** |
| Ortak ana kelime | "yumurta" ↔ "yumurta"; elma ile karpuz eşleşmez |

Sonuç — Türem Yumurta M Boy 30 Adet için:

```
Tarım Kredi  105,00  (aynı marka)
A101         139,00  (farklı marka)  Yumurta M Boy 53-62 Gr 30 Adet
BİM          139,00  (farklı marka)  Bili Bili Yumurta 53-62 Gr 30 Adet
ŞOK          139,00  (farklı marka)  Anadolu Çiftliği Yumurta 53-62 Gr 30 Adet
Migros       139,95  (farklı marka)  Keskinoğlu Yumurta 53-62 Gr 30 Adet
```

Sonuç sayfasındaki **"aynı gramajda farklı markaları da değerlendir"** kutusunu
kapatırsanız sadece 1. kural uygulanır.

---

## Temizlik ürünleri neden farklı çalışıyor

Sistem temizlik ve kişisel bakım kategorilerinde **hiçbir ürünü kendiliğinden
önermez.** Sadece `beyaz_liste.txt` içinde sizin onayladığınız ürünler
karşılaştırmaya girer.

Sebebi: "hipoalerjenik" bilgisi veride güvenilir değil. Bolu'da bu kelimenin
geçtiği sadece 3 ürün var ve hepsi tek marka; gerçekte uygun olan ürünler
"bebek", "sensitive", "parfümsüz", "dermatolojik" gibi farklı kelimelerle
etiketli. Sistemin tahmin yürütmesi, size uygun olmayan bir ürünü "daha ucuz"
diye önermesi anlamına gelirdi.

Doldurmak için:

1. `py topla.py` çalıştırın
2. `beyaz_liste_adaylari.txt` dosyasını açın
3. Uygun ürünlerin satırını `beyaz_liste.txt` içine kopyalayın
4. `py rapor.py`

Bir kez yaparsınız, sonra fiyat takibi otomatik işler.

---

## Çeşit filtreleri — ilk kurulumda ayarlamanız gereken tek şey

Sistem en düşük **birim fiyatı** seçer. Filtre koymazsanız:

- `yumurta` → bıldırcın yumurtası (adet fiyatı daha düşük)
- `un` → mısır unu veya galeta unu

`alisveris.txt` içinde `>` ile düzeltirsiniz:

```
yumurta > !bildircin
un > !misir, !glutensiz, !galeta
elma > golden
```

`!` = "bunu istemiyorum". Ünlemsiz yazarsanız "sadece bu olsun" demektir.

Raporda her kalemin altında **diğer çeşitler** de gösterilir; yanlış bir seçim
yapıldığında oradan fark edip filtreyi eklersiniz.

---

## Market dağıtımı nasıl hesaplanıyor

Her ürünü en ucuzdan almak sizi 6 markete gönderir; yakıt, zaman ve "madem
geldim" alışverişi tasarrufu yer. Onun yerine bu bir **tesis yerleşim problemi**
olarak çözülüyor:

```
en aza indir:  Σ (ürün fiyatı)  +  (uğranan market sayısı × ziyaret maliyeti)
kısıt:         en fazla K markete uğranır
               seçilen marketler listenin en az %80'ini karşılamalı
```

Market sayısı az olduğu için **tüm kombinasyonlar denenip kesin en iyi** bulunur,
yaklaşık çözüm değil.

`rapor.py` başındaki ayarlar:

```python
ZIYARET_MALIYETI = 25.0   # bir markete uğramanın size maliyeti (TL)
MAKS_MARKET      = 2      # en fazla kaç markete uğrarsınız
MIN_KAPSAM       = 0.80   # seçilen marketler listenin en az %80'ini karşılamalı
```

`ZIYARET_MALIYETI` değerini yükseltirseniz sistem sizi daha az markete gönderir.

Komut satırından da değiştirilebilir:

```bash
py rapor.py --market 3
```

Sistem bazı haftalar "tek markete gidin" diyecek. Bu bir hata değil, doğru cevap.

---

## Kategori adı yanlışsa

`sepet.txt` içindeki kategori adı API'ninkiyle birebir eşleşmeli. Bir gruptan hiç
ürün gelmezse `topla.py` sizi uyarır. Doğru adı öğrenmek için:

```bash
py topla.py --kesfet domates zeytin
```

Bu komut o kelimelerin hangi kategorilerde geçtiğini listeler.

Kategori filtresi şart: `domates` filtresiz arandığında gelen 24 sonucun 23'ü
**salça** çıkıyor.

---

## Otomatik çalıştırma

Görev Zamanlayıcı'da her sabah çalışacak bir görev oluşturun:

- **Program:** `py`
- **Bağımsız değişkenler:** `topla.py`
- **Başlangıç yeri:** bu klasörün yolu

Ardından ikinci bir görev aynı şekilde `rapor.py` için. Böylece liste her sabah
telefonunuzda hazır olur, terminal açmanız gerekmez.

---

## Bilinmesi gerekenler

- **Çekim yavaştır ve öyle olmalı.** İstekler arasında 2 saniye beklenir. Hızlı
  ard arda istek atınca sunucu tarafından engellendik; bu değerleri düşürmeyin.
- **Online fiyat = raf fiyatı değil.** İlk haftalarda birkaç ürünü mağazada
  doğrulayın.
- **Uç farklara şüpheyle bakın.** İlk taramada "Siyah Üzüm 1 Kg" A101'de
  119,50 TL, Migros'ta 479,00 TL çıktı (%75 fark). Bu ya farklı bir çeşit ya da
  veri hatası. Sistem farkı gösterir, doğrulamak size düşer. %20–45 bandındaki
  farklar tipik ve genellikle gerçektir; %70 üstü olanları kontrol edin.
- **Kart indirimleri yansımaz.** Money Kart, ŞOK Kart gibi indirimler veride yok.
- **Stok garantisi yok.** Fiyat var demek rafta var demek değil. Raporda her
  kalemin altındaki alternatifler bunun içindir.
- **Birim fiyatı sistem kendisi hesaplar.** API'nin `unitPrice` alanı bazen adet
  bazen kilo üzerinden geliyor ve tutarsız.
- **Gramaj oyunu yakalanır.** Aynı Omo ürünü Bolu'da 1.5 L / 1.495 L / 1.48 L
  olarak üç ayrı gramajda satılıyor. Birim fiyat karşılaştırması bunu görünür
  kılar.
