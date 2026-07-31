/* =====================================================================
   SAYFA SINAMASI  --  calistirma:  node sinama.js

   Market-Sepet.html'in GERCEK javascriptini sahte bir DOM icinde
   calistirir ve gercek veriyle birkac seyi kontrol eder. Tarayici
   acmadan "sayfa bozuldu mu" sorusuna cevap verir.

   Neden var: katalog.py'de yapilan bir degisiklik sayfayi sessizce
   bozabiliyor -- HTML uretilir, dosya yazilir, hicbir hata cikmaz,
   ama sayfa acilinca bos kalir. Bu dosya iki gercek hatayi boyle
   yakaladi (market adinin "Bizimtoptan" diye bozulmasi ve secim
   kutusu bos gelince cozucunun cokmesi).

   Veriye bagli olmayan sinamalar: veritabaninda ne varsa ona gore
   kendini ayarlar, o yuzden her gun calisir.
   ===================================================================== */

const fs = require("fs");
const vm = require("vm");
const path = require("path");

// Sayfa OneDrive icindeki Alisveris klasorune yaziliyor; katalog.py ile
// ayni yeri bulalim.
const ADAYLAR = [
  process.argv[2],
  path.join(process.env.USERPROFILE || "", "OneDrive - Bolu Abant \u0130zzet Baysal \u00dcniversitesi",
            "Alisveris", "Market-Sepet.html"),
  "D:/OneDrive - Bolu Abant \u0130zzet Baysal \u00dcniversitesi/Alisveris/Market-Sepet.html",
  path.join(__dirname, "docs", "index.html"),
].filter(Boolean);

const yol = ADAYLAR.find((a) => fs.existsSync(a));
if (!yol) {
  console.error("Sayfa bulunamadi. Once 'py katalog.py' calistirin.");
  console.error("Baktigim yerler:\n  " + ADAYLAR.join("\n  "));
  process.exit(2);
}
console.log("Sinanan dosya: " + yol + "\n");

const html = fs.readFileSync(yol, "utf8");
const veri = html.match(/<script id="veri" type="application\/json">([\s\S]*?)<\/script>/)[1];
const kod = html.match(/<script>([\s\S]*?)<\/script>/)[1];

/* ---------- sahte DOM ---------- */
function sahteEleman(id) {
  return {
    id, textContent: "", innerHTML: "", value: "", checked: false, dataset: {},
    style: {}, classList: {add() {}, remove() {}, toggle() {}, contains() { return false; }},
    querySelector: () => sahteEleman("?"), querySelectorAll: () => [],
    addEventListener() {}, appendChild() {}, remove() {}, focus() {}, click() {},
    setAttribute() {}, getAttribute() { return null; },
  };
}
const elemanlar = new Map();
function bul(sec) {
  if (sec === "#veri") return {textContent: veri};
  if (!elemanlar.has(sec)) elemanlar.set(sec, sahteEleman(sec));
  return elemanlar.get(sec);
}

const ctx = {
  console,
  document: {
    querySelector: bul, querySelectorAll: () => [],
    getElementById: (i) => bul("#" + i),
    createElement: () => sahteEleman("yeni"),
    addEventListener() {}, body: sahteEleman("body"),
  },
  localStorage: {
    _d: {},
    getItem(k) { return k in this._d ? this._d[k] : null; },
    setItem(k, v) { this._d[k] = String(v); },
    removeItem(k) { delete this._d[k]; },
  },
  location: {href: "file://sinama", reload() {}},
  navigator: {clipboard: {writeText: async () => {}}},
  fetch: () => Promise.reject(new Error("sunucu yok")),
  alert() {}, confirm() { return true; }, prompt() { return null; },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Math, JSON, Intl,
};
ctx.window = ctx;
vm.createContext(ctx);

let hata = 0;
const kontrol = (ad, kosul, ek) => {
  console.log((kosul ? "  TAMAM  " : "  HATA   ") + ad + (ek ? "   -> " + ek : ""));
  if (!kosul) hata++;
};

try {
  vm.runInContext(kod, ctx, {filename: "sayfa.js"});
} catch (e) {
  console.error("  HATA   sayfa javascripti calismadi: " + e.message);
  process.exit(1);
}

// const/let ile tanimlananlar sandbox nesnesine yansimaz; ayni baglamda
// degerlendirerek ulasiyoruz.
const ev = (s) => vm.runInContext(s, ctx);
const D = ev("D"), U = ev("U");
const urunSatiri = ev("urunSatiri"), coz = ev("coz"), cizSonuc = ev("cizSonuc");
const sepet = ev("sepet");

/* ---------- 1. temel ---------- */
kontrol("veri yuklendi", U && U.length > 0, U ? U.length + " urun" : "yok");
kontrol("market listesi dolu", D.market_adlari.length > 0, D.market_adlari.join(", "));
kontrol("market adlari bozuk degil",
  !D.market_adlari.some((a) => /^[a-z]/.test(a) || /^[A-Z][a-z]+toptan$/.test(a)),
  D.market_adlari.join(", "));
kontrol("ust satir yazildi", /ürün/.test(bul("#ust").textContent),
  bul("#ust").textContent);

/* ---------- 2. arama ve siralama ---------- */
const s0 = urunSatiri(0);
kontrol("urun satiri uretiliyor", /class="urun"/.test(s0) && /class="fiyat"/.test(s0));
kontrol("fiyatlar ucuzdan pahaliya sirali",
  U.every((u) => u[6].every((p, i) => i === 0 || p[1] >= u[6][i - 1][1])));

/* ---------- 3. eski fiyatlar (yas_gun) ---------- */
// Ucuncu alan sadece bugunden eski fiyatlarda olmali.
const eskiSayisi = U.reduce((n, u) => n + u[6].filter((p) => p.length === 3).length, 0);
const bozuk = U.some((u) => u[6].some((p) => p.length === 3 && !(p[2] > 0)));
kontrol("eski fiyat isaretleri tutarli", !bozuk, eskiSayisi + " eski fiyat");

const eskiMarket = (D.market_yasi || []).findIndex((y) => y > 0);
if (eskiMarket >= 0) {
  const yas = D.market_yasi[eskiMarket];
  const elle = !!(D.elle_marketler || {})[D.marketler[eskiMarket]];
  console.log(`  (${D.market_adlari[eskiMarket]} verisi ${yas} gun eski` +
              (elle ? ", elle giriliyor)" : ")"));
  if (!elle) {
    kontrol("gecikmis market ust satirda duyuruluyor",
      /eski veri/.test(bul("#ust").textContent), bul("#ust").textContent);
  }
  const i = U.findIndex((u) => u[6][0][0] === eskiMarket && u[6][0].length === 3);
  if (i >= 0) {
    kontrol("arama satirinda fiyatin tarihi yaziyor", /fiyatı<\/span>/.test(urunSatiri(i)));
    sepet.length = 0;
    sepet.push({i: i, adet: 1});
    const r = coz(3, 25, false);
    kontrol("cozum uretildi", !r.hata, r.hata || "");
    const a = (r.atamalar || []).find((x) => x.market === eskiMarket);
    kontrol("cozumde fiyatin yasi tasiniyor", !a || a.yas === yas,
      a ? "yas=" + a.yas : "bu market secilmedi");
    cizSonuc();
    kontrol("sonuc ekrani fiyatin eskiligini soyluyor",
      /çekilemedi|fiyatı<\/span>|elle girildi/.test(bul("#sonucIcerik").innerHTML));
  }
} else {
  console.log("  (butun marketler bugunun verisiyle -- eski fiyat sinamasi atlandi)");
}

/* ---------- 4. cozucu ---------- */
sepet.length = 0;
for (let i = 0; i < U.length && sepet.length < 5; i++) {
  if (U[i][6].length > 1) sepet.push({i: i, adet: 1});
}
kontrol("cok markette bulunan urun var", sepet.length > 0);
if (sepet.length) {
  const r = coz(2, 25, true);
  kontrol("cozum kalemleri karsiliyor", !r.hata && r.atamalar.length > 0,
    r.hata || r.atamalar.length + "/" + r.kalemSayisi + " kalem");
  kontrol("toplam maliyet tutarli",
    !r.hata && Math.abs(r.maliyet - (r.sepetTutar + r.boyut * 25)) < 0.01);
  // Bozuk secim degeri sayfayi cokertmemeli
  let cokme = null;
  try { coz(0, NaN, false); } catch (e) { cokme = e.message; }
  kontrol("bozuk secim degerinde cokmuyor", !cokme, cokme || "");
}

console.log(hata ? "\n" + hata + " SINAMA BASARISIZ" : "\nTum sinamalar gecti.");
process.exit(hata ? 1 : 0);
