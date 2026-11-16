@echo off
rem DVB-Nexus one-click launcher (backend + frontend + open browser).
rem All logic lives in scripts\start-dvbnexus.ps1 so Chinese messages render
rem correctly on any console codepage (PowerShell uses the Unicode console API;
rem cmd batch files break when mixing UTF-8 text with chcp 65001).
rem Usage: double-click, or run "start.cmd -NoOpen" to start without the browser.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dvbnexus.ps1" %*
exit /b %ERRORLEVEL%
