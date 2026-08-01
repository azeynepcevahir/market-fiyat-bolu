@echo off
rem Bekciyi cift tiklayarak baslatmak icin. Ayrinti: tools\bekci.sh
rem Kapatmak icin bu pencereyi kapatin.
title Gorev panosu bekcisi
cd /d "%~dp0.."
:dongu
node tools\build-isler.mjs --hizli >nul 2>&1
if errorlevel 1 (
  echo [%date% %time:~0,5%] URETILEMEDI -- ayrinti icin: node tools\build-isler.mjs
) else (
  echo [%date% %time:~0,5%] panel yenilendi
)
timeout /t 3600 /nobreak >nul
goto dongu
