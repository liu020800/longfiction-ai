@echo off
setlocal EnableExtensions
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0longfiction_launcher.ps1" start
if errorlevel 1 pause
exit /b %errorlevel%
