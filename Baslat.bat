@echo off
rem ---------------------------------------------------------------
rem  Market Sepeti -- cift tiklayin, tarayicida acilir.
rem  Kapatmak icin bu siyah pencereyi kapatin.
rem ---------------------------------------------------------------
cd /d "%~dp0"
title Market Sepeti - kapatmak icin bu pencereyi kapatin
echo.
echo   Baslatiliyor... Tarayici birazdan acilacak.
echo   Bu pencereyi KAPATMAYIN, program burada calisiyor.
echo.
py uygulama.py
echo.
echo   Program durdu. Kapatmak icin bir tusa basin.
pause >nul
