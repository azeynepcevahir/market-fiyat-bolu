/* ============================================================================
   YAPILACAKLAR PANELI URETICISI          calistirma:  node tools/build-isler.mjs
   ============================================================================

   ! YAPILACAKLAR.html ELLE DUZENLENMEZ. Her zaman bu betikle uretilir.
     Elle yapilan bir degisiklik bir sonraki uretimde sessizce silinir.
     Icerik degisecekse tools/isler.json duzenlenir, sonra bu betik calisir.

   IKI PARCA
     tools/isler.json       gorev listesi (tek dogru kaynak)
     tools/build-isler.mjs  bu dosya -- listeyi okur, sayilari olcer, HTML yazar
     YAPILACAKLAR.html      cikti (proje kokunde)

   SAYILAR ELLE YAZILMAZ
     Paneldeki her sayi uretim aninda GERCEK KAYNAKTAN okunur: uretilmis
     sayfanin icindeki veri, git, dosya sistemi, sinama ciktisi. Elle yazilan
     bir yuzde bir kez yanlis girilirse orada donar ve yazili oldugu icin
     dogruymus gibi gorunur. Okunamayan olcum sayi uydurmaz, "okunamadi" der.

     Yuzde sadece ILERLEME olcumlerinde gosterilir; yani "yapilan is / yapilacak
     is". "Elde olan / hedef" turu oranlar (kac market cekilebiliyor gibi)
     KAPSAM diye ayri etiketlenir ve yuzde cubugu almaz -- ikisi karisirsa
     ilerleme oldugundan yuksek gorunur.

   SECENEKLER
     --hizli    sinamayi calistirma (birkac saniye kazandirir)
     --yayin    panelin bir kopyasini docs/ icine de koyar (siteye cikar)
   ==========================================================================*/

import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const BURASI = path.dirname(fileURLToPath(import.meta.url));
const KOK = path.resolve(BURASI, "..");
const HIZLI = process.argv.includes("--hizli");
const YAYIN = process.argv.includes("--yayin");

const BASLIKLAR = {
  donuyor: ["Dönüyor", "şu an üzerinde çalışılan"],
  sirada: ["Sırada", "yapılacak, henüz başlanmadı"],
  karar: ["Karar bekliyor", "sizin cevabınızı bekleyenler"],
  not: ["Açık kalan not", "iş değil ama bilinmesi gereken"],
  bitti: ["Bitti", "silinmiyor; neyin neden yapıldığı kalsın diye duruyor"],
};
const SIRA = ["donuyor", "sirada", "karar", "not", "bitti"];

/* ---------------------------------------------------------------- yardimci */

const kacir = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

const ikiHane = (n) => String(n).padStart(2, "0");
const trTarih = (d) => `${ikiHane(d.getDate())}.${ikiHane(d.getMonth() + 1)}.${d.getFullYear()}`;
const trSaat = (d) => `${ikiHane(d.getHours())}:${ikiHane(d.getMinutes())}`;
const sayiYaz = (n) => Number(n).toLocaleString("tr-TR");

function komut(dosya, argumanlar) {
  return execFileSync(dosya, argumanlar, {
    cwd: KOK, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 120000,
  }).trim();
}

/* Uretilmis sayfayi bul: once OneDrive'daki taze kopya, sonra yayindaki. */
function sayfaYolu() {
  const adaylar = [
    path.resolve(KOK, "..", "..", "..", "Alisveris", "Market-Sepet.html"),
    process.env.OneDriveCommercial &&
      path.join(process.env.OneDriveCommercial, "Alisveris", "Market-Sepet.html"),
    process.env.OneDrive && path.join(process.env.OneDrive, "Alisveris", "Market-Sepet.html"),
    path.join(KOK, "docs", "index.html"),
  ].filter(Boolean);
  return adaylar.find((a) => fs.existsSync(a)) || null;
}

/* ------------------------------------------------------------------ olcum */
/*  Her olcum: {ad, deger, ek, kaynak, tur, pay, payda, formul, hata}
    tur: "ilerleme" (yuzde cubugu alir) | "kapsam" | "durum"                */

function olcumler(isler) {
  const cikti = [];
  const ekle = (o) => cikti.push(o);

  /* 1 -- gorev ilerlemesi: yapilan is / yapilacak is.
        "not" maddeleri is degil, paydaya girmez.                          */
  {
    const is = isler.filter((i) => i.durum !== "not");
    const bitti = is.filter((i) => i.durum === "bitti").length;
    ekle({
      ad: "Görev ilerlemesi", tur: "ilerleme",
      pay: bitti, payda: is.length,
      deger: is.length ? Math.round((bitti / is.length) * 100) + "%" : "-",
      formul: `${bitti} biten iş ÷ ${is.length} toplam iş (biten + açık). ` +
              `"Açık kalan not" maddeleri iş sayılmadığı için paydada yok.`,
      kaynak: "tools/isler.json",
    });
  }

  /* 2 -- sizde bekleyen is sayisi */
  {
    const sizde = isler.filter((i) => i.kim === "siz" && i.durum !== "bitti" && i.durum !== "not");
    ekle({
      ad: "Sizi bekleyen", tur: "durum", deger: sizde.length,
      ek: sizde.length ? sizde.map((i) => i.baslik).join(" · ") : "yok",
      kaynak: "tools/isler.json",
    });
  }

  /* 3 -- uretilmis sayfadan okunanlar: urun, market, veri tarihi */
  const yol = sayfaYolu();
  if (!yol) {
    ekle({ad: "Katalog", tur: "durum", hata: "üretilmiş sayfa bulunamadı (py katalog.py)",
           kaynak: "Market-Sepet.html"});
  } else {
    try {
      const ham = fs.readFileSync(yol, "utf8");
      const m = ham.match(/<script id="veri" type="application\/json">([\s\S]*?)<\/script>/);
      if (!m) throw new Error("sayfada veri bloğu yok");
      const D = JSON.parse(m[1]);
      const kisaYol = path.basename(path.dirname(yol)) + "/" + path.basename(yol);

      ekle({
        ad: "Katalogdaki ürün", tur: "durum", deger: sayiYaz(D.urunler.length),
        ek: `${D.marketler.length} market · fiyat tarihi ${D.tarih}`,
        kaynak: kisaYol,
      });

      // Bugunun verisiyle gelen market sayisi. Bu ILERLEME degil, kapsamdir.
      const yaslar = D.market_yasi || D.marketler.map(() => 0);
      const elle = D.elle_marketler || {};
      const otomatik = D.marketler.filter((k) => !elle[k]);
      const taze = otomatik.filter((k, i) => !yaslar[D.marketler.indexOf(k)]);
      const eski = otomatik.filter((k) => yaslar[D.marketler.indexOf(k)] > 0)
        .map((k) => `${D.market_adlari[D.marketler.indexOf(k)]} ` +
                    `${yaslar[D.marketler.indexOf(k)]} gün eski`);
      ekle({
        ad: "Son çekimde gelen market", tur: "kapsam",
        pay: taze.length, payda: otomatik.length,
        deger: `${taze.length}/${otomatik.length}`,
        formul: `Otomatik çekilen marketlerin kaçı verinin son gününde (${D.tarih}) ` +
                "gelebildi. Bu bir ilerleme değil, o günkü durum — yüzdeye çevirmek " +
                "yanıltıcı olur.",
        ek: eski.length ? eski.join(" · ") : "hepsi bugünün verisi",
        kaynak: kisaYol,
      });

      // Fiyatlarin yasi. Dosyanin damgasina degil VERININ KENDI TARIHINE
      // bakiyoruz: OneDrive esitlemesi dosya damgasini degistirebiliyor,
      // veri tarihi ise cekimin gercekten hangi gune ait oldugunu soyler.
      const st = fs.statSync(yol);
      const gun = Math.round(
        (new Date(new Date().toISOString().slice(0, 10)) - new Date(D.tarih)) / 86400000);
      ekle({
        ad: "Fiyat verisinin yaşı", tur: "durum",
        deger: gun <= 0 ? "bugünün verisi" : gun === 1 ? "1 gün eski" : `${gun} gün eski`,
        ek: `veri tarihi ${D.tarih} · dosya ${trTarih(st.mtime)} ${trSaat(st.mtime)} · ` +
            `${(st.size / 1048576).toFixed(1)} MB`,
        kaynak: kisaYol,
      });
    } catch (e) {
      ekle({ad: "Katalog", tur: "durum", hata: e.message, kaynak: path.basename(yol)});
    }
  }

  /* 4 -- elle girilen fiyatlar */
  try {
    const j = JSON.parse(fs.readFileSync(path.join(KOK, "elle_fiyatlar.json"), "utf8"));
    const liste = Array.isArray(j) ? j : (j.fiyatlar || []);
    const marketler = [...new Set(liste.map((k) => k.market))];
    const tarihler = liste.map((k) => k.tarih).filter(Boolean).sort();
    ekle({
      ad: "Elle girilen fiyat", tur: "durum", deger: liste.length,
      ek: liste.length
        ? `${marketler.join(", ")} · en eskisi ${tarihler[0]}`
        : "hiç girilmemiş",
      kaynak: "elle_fiyatlar.json",
    });
  } catch (e) {
    ekle({ad: "Elle girilen fiyat", tur: "durum", hata: e.message,
          kaynak: "elle_fiyatlar.json"});
  }

  /* 5 -- gonderilmemis commit */
  try {
    const bekleyen = komut("git", ["rev-list", "--count", "origin/main..HEAD"]);
    const son = komut("git", ["log", "-1", "--format=%h · %s"]);
    ekle({
      ad: "Gönderilmemiş commit", tur: "durum", deger: Number(bekleyen),
      ek: Number(bekleyen) ? `en üsttekі: ${son} — Push origin deyin` : `son: ${son}`,
      kaynak: "git",
    });
  } catch (e) {
    ekle({ad: "Gönderilmemiş commit", tur: "durum",
          hata: "git okunamadı: " + String(e.message).split("\n")[0], kaynak: "git"});
  }

  /* 6 -- sayfa sinamasi: gercekten calistirilir, ciktisi sayilir */
  if (HIZLI) {
    ekle({ad: "Sayfa sınaması", tur: "durum", hata: "--hizli ile atlandı",
          kaynak: "sinama.js"});
  } else {
    let metin = "", calisti = true;
    try {
      metin = komut("node", ["sinama.js"]);
    } catch (e) {
      metin = String(e.stdout || "") + String(e.stderr || "");
      calisti = false;
    }
    const gecen = (metin.match(/TAMAM/g) || []).length;
    const kalan = (metin.match(/HATA/g) || []).length;
    const toplam = gecen + kalan;
    if (!toplam) {
      ekle({ad: "Sayfa sınaması", tur: "durum",
            hata: "çalıştırılamadı" + (calisti ? "" : " (çıktı yok)"), kaynak: "sinama.js"});
    } else {
      ekle({
        ad: "Sayfa sınaması", tur: "ilerleme", pay: gecen, payda: toplam,
        deger: `${gecen}/${toplam}`,
        formul: `Geçen kontrol ÷ çalıştırılan kontrol. node sinama.js şimdi çalıştırıldı, ` +
                `sonuç okundu — bu sayı elle yazılmıyor.`,
        ek: kalan ? `${kalan} kontrol başarısız` : "hepsi geçti",
        kaynak: "sinama.js",
      });
    }
  }

  /* 7 -- sepet kapsami: kac urun grubu takip ediliyor */
  try {
    const satirlar = fs.readFileSync(path.join(KOK, "sepet.txt"), "utf8")
      .split("\n").map((s) => s.trim())
      .filter((s) => s && !s.startsWith("#"));
    // Bicim:  Grup | API kategorisi | kelime, kelime, ...
    const kelime = satirlar.reduce(
      (n, s) => n + (s.split("|")[2] || "").split(",").filter((x) => x.trim()).length, 0);
    ekle({
      ad: "Takip edilen ürün grubu", tur: "durum", deger: satirlar.length,
      ek: `${kelime} arama kelimesi`, kaynak: "sepet.txt",
    });
  } catch (e) {
    ekle({ad: "Takip edilen ürün grubu", tur: "durum", hata: e.message, kaynak: "sepet.txt"});
  }

  return cikti;
}

/* -------------------------------------------------------------------- HTML */

function olcumKarti(o) {
  if (o.hata) {
    return `<div class="olcum yok">
      <div class="ad">${kacir(o.ad)}</div>
      <div class="deger">okunamadı</div>
      <div class="not">${kacir(o.hata)}</div>
      <div class="kaynak">kaynak: ${kacir(o.kaynak)}</div></div>`;
  }
  const yuzde = o.tur === "ilerleme" && o.payda
    ? `<div class="cubuk"><div style="width:${(o.pay / o.payda * 100).toFixed(1)}%"></div></div>`
    : "";
  const etiket = o.tur === "ilerleme" ? '<span class="tur ilerleme">ilerleme</span>'
    : o.tur === "kapsam" ? '<span class="tur kapsam">kapsam</span>' : "";
  return `<div class="olcum">
    <div class="ad">${kacir(o.ad)}${etiket}</div>
    <div class="deger">${kacir(o.deger)}</div>
    ${yuzde}
    ${o.formul ? `<div class="formul">${kacir(o.formul)}</div>` : ""}
    ${o.ek ? `<div class="not">${kacir(o.ek)}</div>` : ""}
    <div class="kaynak">kaynak: ${kacir(o.kaynak)}</div></div>`;
}

function isSatiri(is) {
  const rozet = is.kim === "siz" ? '<span class="rozet siz">sizde</span>'
    : is.kim === "ben" ? '<span class="rozet ben">bende</span>' : "";
  const tarih = is.tarih ? `<span class="rozet tarih">${kacir(is.tarih.slice(5).replace("-", "."))}</span>` : "";
  return `<div class="is ${kacir(is.durum)}">
    <div class="im"></div>
    <div class="govde">
      <div class="baslik">${kacir(is.baslik)}${rozet}${tarih}</div>
      <div class="neden">${kacir(is.neden)}</div>
      ${is.kaynak ? `<div class="kaynak"><code>${kacir(is.kaynak)}</code></div>` : ""}
    </div></div>`;
}

function sayfaUret(veri, olcumListesi) {
  const simdi = new Date();
  const bolumler = SIRA.map((durum) => {
    const liste = veri.isler.filter((i) => i.durum === durum);
    if (!liste.length) return "";
    const [ad, aciklama] = BASLIKLAR[durum];
    return `<section class="bolum ${durum}">
      <h2>${kacir(ad)} <span class="adet">${liste.length}</span></h2>
      <div class="altbaslik">${kacir(aciklama)}</div>
      <div class="kart">${liste.map(isSatiri).join("")}</div>
    </section>`;
  }).join("");

  return `<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yapılacaklar — ${kacir(veri.proje)}</title>
<style>
:root{
  --zemin:#f4f6f8; --kart:#ffffff; --cizgi:#dde2e9; --yazi:#14181f; --soluk:#6b7484;
  --koyu:#14181f; --yesil:#0b7a3b; --sari:#a8710a; --kirmizi:#b3261e; --mavi:#2b4b80;
  --vurgu:#eef1f5;
}
@media(prefers-color-scheme:dark){
  :root{
    --zemin:#0f1216; --kart:#181c22; --cizgi:#2b323d; --yazi:#e8ecf2; --soluk:#9aa3b1;
    --koyu:#000000; --yesil:#4cbd82; --sari:#d9a13a; --kirmizi:#e8705f; --mavi:#7aa5e8;
    --vurgu:#22272f;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--zemin);color:var(--yazi);line-height:1.55;
  font-family:-apple-system,'Segoe UI',Roboto,sans-serif}
header{background:var(--koyu);color:#fff;padding:16px 0}
.kap{max-width:880px;margin:0 auto;padding:0 15px}
header h1{margin:0;font-size:17px;font-weight:600}
header .alt{font-size:11.5px;opacity:.62;margin-top:3px}
.olcumler{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:11px;
  margin:15px 0 4px}
.olcum{background:var(--kart);border:1px solid var(--cizgi);border-radius:11px;padding:11px 13px}
.olcum.yok{opacity:.72}
.olcum .ad{font-size:11.5px;color:var(--soluk);text-transform:uppercase;letter-spacing:.03em}
.olcum .deger{font-size:23px;font-weight:700;line-height:1.25;margin-top:2px}
.olcum .cubuk{height:6px;background:var(--vurgu);border-radius:99px;overflow:hidden;margin:6px 0 2px}
.olcum .cubuk div{height:100%;background:var(--yesil);border-radius:99px}
.olcum .formul{font-size:11.5px;color:var(--soluk);margin-top:5px;
  padding-left:8px;border-left:2px solid var(--cizgi)}
.olcum .not{font-size:12px;color:var(--soluk);margin-top:5px}
.olcum .kaynak{font-size:10.5px;color:var(--soluk);opacity:.75;margin-top:6px;
  font-family:ui-monospace,Consolas,monospace}
.tur{font-size:9.5px;font-weight:700;padding:1px 6px;border-radius:99px;margin-left:6px;
  letter-spacing:0;text-transform:none}
.tur.ilerleme{background:rgba(11,122,59,.13);color:var(--yesil)}
.tur.kapsam{background:rgba(43,75,128,.13);color:var(--mavi)}
.aciklama{font-size:12.5px;color:var(--soluk);margin:9px 0 4px;
  border-left:2px solid var(--cizgi);padding-left:9px}
h2{font-size:15px;margin:22px 0 1px;display:flex;align-items:center;gap:8px}
h2 .adet{font-size:11px;font-weight:600;color:var(--soluk);background:var(--vurgu);
  border-radius:99px;padding:1px 8px}
.altbaslik{font-size:11.5px;color:var(--soluk);margin-bottom:8px}
.kart{background:var(--kart);border:1px solid var(--cizgi);border-radius:11px;overflow:hidden}
.is{display:flex;gap:11px;padding:11px 13px;border-bottom:1px solid var(--cizgi)}
.is:last-child{border-bottom:none}
.im{width:9px;height:9px;border-radius:50%;flex:none;margin-top:7px;background:var(--soluk)}
.donuyor .im{background:var(--sari);box-shadow:0 0 0 3px rgba(168,113,10,.16)}
.sirada .im{background:var(--mavi)}
.karar .im{background:var(--kirmizi);box-shadow:0 0 0 3px rgba(179,38,30,.13)}
.not .im{background:var(--soluk);opacity:.5}
.bitti .im{background:var(--yesil)}
.is .baslik{font-size:14px;font-weight:600}
.is .neden{font-size:12.5px;color:var(--soluk);margin-top:2px}
.is .kaynak{margin-top:4px}
.bitti .is{opacity:.6}
.bitti .is .baslik{font-weight:500;text-decoration:line-through;
  text-decoration-color:var(--soluk);text-decoration-thickness:1px}
.rozet{display:inline-block;font-size:9.5px;font-weight:700;padding:1px 7px;
  border-radius:99px;margin-left:7px;vertical-align:2px}
.rozet.siz{background:rgba(179,38,30,.13);color:var(--kirmizi)}
.rozet.ben{background:rgba(43,75,128,.13);color:var(--mavi)}
.rozet.tarih{background:var(--vurgu);color:var(--soluk)}
code{font-family:ui-monospace,Consolas,monospace;font-size:11px;background:var(--vurgu);
  padding:1px 6px;border-radius:5px;color:var(--soluk)}
footer{font-size:11.5px;color:var(--soluk);margin:26px 0 34px;line-height:1.7}
</style></head><body>

<header><div class="kap">
  <h1>Yapılacaklar — ${kacir(veri.proje)}</h1>
  <div class="alt">${trTarih(simdi)} ${trSaat(simdi)}'de üretildi ·
    sayılar bu anda gerçek kaynaklardan okundu</div>
</div></header>

<div class="kap">
  <div class="olcumler">${olcumListesi.map(olcumKarti).join("")}</div>
  <div class="aciklama">
    <b>ilerleme</b> = yapılan iş ÷ yapılacak iş; yüzde çubuğu sadece bunlarda var.
    <b>kapsam</b> = elde olan ÷ hedeflenen; ilerleme değildir, o yüzden yüzdeye
    çevrilmez. Bir ölçüm okunamazsa sayı uydurulmaz, “okunamadı” yazar.
  </div>
  ${bolumler}
  <footer>
    Bu dosya elle düzenlenmez. Kaynak <code>tools/isler.json</code>,
    üretici <code>tools/build-isler.mjs</code>.<br>
    Yenilemek için: <code>node tools/build-isler.mjs</code> —
    saat başı kendiliğinden yenilensin isterseniz <code>tools/bekci.sh</code>.
  </footer>
</div>
</body></html>
`;
}

/* -------------------------------------------------------------------- ana */

const veri = JSON.parse(fs.readFileSync(path.join(BURASI, "isler.json"), "utf8"));
const bilinmeyen = veri.isler.filter((i) => !SIRA.includes(i.durum));
if (bilinmeyen.length) {
  console.error("Bilinmeyen durum: " +
    bilinmeyen.map((i) => `${i.id}=${i.durum}`).join(", ") +
    `\nGecerli durumlar: ${SIRA.join(", ")}`);
  process.exit(1);
}
const eksikNeden = veri.isler.filter((i) => !i.neden || i.neden.length < 15);
if (eksikNeden.length) {
  console.error("Her isin bir 'neden'i olmali (en az bir cumle). Eksik: " +
    eksikNeden.map((i) => i.id).join(", "));
  process.exit(1);
}

const olculen = olcumler(veri.isler);
const html = sayfaUret(veri, olculen);

const hedefler = [path.join(KOK, "YAPILACAKLAR.html")];
if (YAYIN && fs.existsSync(path.join(KOK, "docs"))) {
  hedefler.push(path.join(KOK, "docs", "yapilacaklar.html"));
}
for (const h of hedefler) {
  fs.writeFileSync(h, html, "utf8");
  console.log("Yazildi: " + path.relative(KOK, h));
}

const acik = veri.isler.filter((i) => ["donuyor", "sirada", "karar"].includes(i.durum));
console.log(`\n${veri.isler.length} madde · ${acik.length} acik is` +
  ` (${acik.filter((i) => i.kim === "siz").length} tanesi sizde)`);
const okunamayan = olculen.filter((o) => o.hata);
if (okunamayan.length) {
  console.log("Okunamayan olcum: " + okunamayan.map((o) => o.ad).join(", "));
}
