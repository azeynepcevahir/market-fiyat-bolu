#!/usr/bin/env bash
# ============================================================================
#  BEKCI  --  paneli saat basi yeniden uretir
# ============================================================================
#
#  Uzun suren bir is donerken (gece boyu cekim, arka planda calisan toplayici)
#  panelin sayilari kendiliginden tazelensin diye. Panel sayilari uretim
#  aninda okudugu icin, yeniden uretmek = sayilari tazelemek.
#
#  Windows'ta Git Bash icinden calistirin:
#      bash tools/bekci.sh
#  Ya da cift tiklamak icin:  tools/bekci.bat
#
#  Durdurmak: Ctrl+C  (ya da pencereyi kapatin)
#
#  Aralik varsayilan 3600 saniye; degistirmek icin:
#      bash tools/bekci.sh 900
# ============================================================================

set -u

ARALIK="${1:-3600}"
KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KOK" || exit 1

echo "Bekci basladi. Panel her $ARALIK saniyede yeniden uretilecek."
echo "Proje: $KOK"
echo "Durdurmak icin Ctrl+C."
echo

while true; do
  DAMGA="$(date '+%d.%m.%Y %H:%M')"
  # --hizli: sinama her seferinde calismasin, bekci hafif kalsin.
  if node tools/build-isler.mjs --hizli >/dev/null 2>&1; then
    echo "[$DAMGA] panel yenilendi"
  else
    echo "[$DAMGA] URETILEMEDI -- ayrinti icin: node tools/build-isler.mjs"
  fi
  sleep "$ARALIK"
done
