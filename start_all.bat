@echo off
REM Boot startup wrapper — invoked by Task Scheduler at logon (or manually).
REM All logic lives in scripts\start_all.ps1.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_all.ps1"
