# Durum notu — 31 Temmuz 2026

Bu dosya, projeye sonradan bakan biri (veya yeni bir Claude oturumu) için
"neredeyiz, ne bekliyor" özetidir. Ayrıntılar `README.md` içinde.

---

## Sistem ne yapıyor

Bolu merkezdeki marketlerin fiyatlarını her sabah çeker, aynı marka + aynı
gramajdaki ürünleri karşılaştırır, marka tutmadığında aynı gramaj/boy/nitelikteki
muadili bulur, ve kaç markete uğramaya razı olduğunuza göre alışverişi dağıtır.

**Yayın:** https://azeynepcevahir.github.io/market-fiyat-bolu/

## Veri kaynakları (9 market)

| Kaynak | Marketler | Nasıl |
|---|---|---|
| marketfiyati.org.tr | A101, BİM, CarrefourSA, Migros, ŞOK, Tarım Kredi | `topla.py` |
| Özdilek kendi API'si | Özdilek | `ozdilek.py` — `market-bolu-store` |
| Bizim Toptan sitesi | Bizim Toptan | `bizimtoptan.py` — sunucu render, HTML'de gömülü JSON |
| Elle giriş | File, Nuhmar, Başgimpa, yerel marketler | sayfadaki ✎ Elle sekmesi |

**Önemli:** Özdilek fiyatları mağazaya göre değişiyor. Bolu anahtarı
`market-bolu-store`; varsayılan `market-gecit-store` Bursa'dır.

**Bir market o gün çekilemezse** (ağ kesintisi, site çöker, iş atlanır)
elimizdeki son fiyat kullanılır — en fazla 7 gün geriye (`rapor.GECMIS_GUN`).
Fiyatın kaç günlük olduğu üst satırda, arama sonucunda ve alışveriş listesinde
tarihiyle yazar. Bunsuz, tek bir başarısız çekim o marketi listeden tamamen
düşürüyordu ve kullanıcı nedenini göremiyordu.

**Sayfa sınaması:** `node sinama.js` — üretilen HTML'in kendi javascriptini
sahte bir DOM içinde çalıştırıp gerçek veriyle kontrol eder. Tarayıcı açmadan
"sayfa bozuldu mu" sorusuna cevap verir. katalog.py'ye dokunduysanız çalıştırın.

## Yapılacaklar paneli

Açık işlerin güncel hali `YAPILACAKLAR.html` dosyasında — çift tıklayıp açın.
Sayıları (ürün sayısı, test sonucu, gönderilmemiş commit, verinin yaşı) üretim
anında gerçek kaynaklardan okur, elle yazılmaz.

    node tools/build-isler.mjs          paneli yenile
    node tools/build-isler.mjs --hizli  sınamayı atla, hızlı üret
    bash tools/bekci.sh                 saat başı kendiliğinden yenile

İş bittikçe `tools/isler.json` güncellenir ve panel yeniden üretilir.
**HTML elle düzenlenmez**, bir sonraki üretimde silinir.

Aşağıdaki liste anlatı; panel ise güncel durumdur. İkisi çelişirse panel doğrudur.

## Açık işler

1. **Bizim Toptan sayfalama çözülmedi.** `?page=N` ilerlemiyor, her kategoriden
   sadece ilk sayfa geliyor (276 ürün). Doğru parametre bulunursa birkaç bine çıkar.
2. **Bizim Toptan çoklu paketleri atlanıyor.** Sitedeki fiyatları tutarsız
   (aynı boy ürünün biri 45 TL, diğeri 480 TL). `--coklu-dahil` ile alınabilir
   ama önerilmez. Ayrıntı `bizimtoptan.py` içindeki nota bakın.
3. **Bizim Toptan adresi zaman zaman çözülmüyor.** 31.07'de yerel internet
   sağlayıcısı `www.bizimtoptan.com.tr`'yi çözemedi (Google DNS çözüyordu).
   Site Cloudflare arkasında. GitHub Actions başka ağdan çalıştığı için
   oradan etkilenmiyor. Artık bir günlük kesinti veriyi düşürmüyor.
4. **Zamanlanmış çalışma atlanabiliyor.** 31.07'de 07:00 UTC'deki iş hiç
   çalışmadı. GitHub cron'u "en iyi çaba" ile işler. Tekrarlarsa yedek tetikleyici
   düşünülebilir.
5. **İstatistik zaman serisi yeni başladı.** `gunluk_endeks` ve `takip_fiyat`
   her çekimde birikiyor; ham `fiyat` verisi 45 günde budanıyor. Grafikler
   birkaç hafta sonra anlamlı olacak.

## Denenmiş ve vazgeçilmiş

- **File Market otomatik çekimi.** Web mağazası yok, sadece mobil uygulama.
  API'si var (`api.filemarket.com.tr`) ama uç noktaları bilinmiyor; bulmak için
  telefonda trafik yakalamak gerekir, sertifika sabitlemeye takılabilir.
  Elle giriş tercih edildi.
- **`market.file.com.tr`** SAP kurumsal portalı, çalışan girişi — dokunulmadı.

## Sonraki adaylar

- Bizim Toptan sayfalaması
- Adese, Seç Market, Soykan, Çetinkaya, Ekomini, Bol Avantaj — hepsi
  `elle_marketler.txt`'te tanımlı, otomatik çekilebilirlikleri araştırılmadı

## Alışkanlıklar

- **Kod push edilince site güncellenmez.** Sayfayı Actions üretir; ya sabahki
  çalışmayı bekleyin ya Actions sekmesinden elle tetikleyin.
- Commit mesajlarında çift tırnak kullanmayın; PowerShell'den `git commit -m`
  bozuluyor. `-F dosya` ile verin.
- Elle girilen fiyatlar `elle_fiyatlar.json` ile depoya taşınır — girdikten
  sonra commit + push şart, yoksa yayındaki sayfada görünmez.
