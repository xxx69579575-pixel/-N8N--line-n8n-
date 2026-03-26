@echo off
chcp 65001 > nul
echo ========================================
echo   AI 企業問答助理 - 環境檢查 (Windows)
echo ========================================
echo.

set PASS=0
set FAIL=0

:: 檢查 Docker
echo [1/8] 檢查 Docker...
docker --version > nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=*" %%i in ('docker --version') do echo   OK: %%i
    set /a PASS+=1
) else (
    echo   FAIL: Docker 未安裝 - 請到 https://www.docker.com/products/docker-desktop/ 下載
    set /a FAIL+=1
)

:: 檢查 Docker Compose
echo [2/8] 檢查 Docker Compose...
docker compose version > nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=*" %%i in ('docker compose version') do echo   OK: %%i
    set /a PASS+=1
) else (
    echo   FAIL: Docker Compose 未安裝
    set /a FAIL+=1
)

:: 檢查 Python
echo [3/8] 檢查 Python...
python --version > nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=*" %%i in ('python --version') do echo   OK: %%i
    set /a PASS+=1
) else (
    echo   FAIL: Python 未安裝 - 請到 https://www.python.org/downloads/ 下載
    set /a FAIL+=1
)

:: 檢查 psycopg2
echo [4/8] 檢查 psycopg2...
python -c "import psycopg2; print('psycopg2 ' + psycopg2.__version__)" > nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=*" %%i in ('python -c "import psycopg2; print(psycopg2.__version__)"') do echo   OK: psycopg2 %%i
    set /a PASS+=1
) else (
    echo   FAIL: psycopg2 未安裝 - 執行: pip install psycopg2-binary
    set /a FAIL+=1
)

:: 檢查 Ollama
echo [5/8] 檢查 Ollama...
ollama --version > nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=*" %%i in ('ollama --version') do echo   OK: %%i
    set /a PASS+=1
) else (
    echo   FAIL: Ollama 未安裝 - 請到 https://ollama.ai/download 下載
    set /a FAIL+=1
)

:: 檢查 ngrok
echo [6/8] 檢查 ngrok...
ngrok --version > nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=*" %%i in ('ngrok --version') do echo   OK: %%i
    set /a PASS+=1
) else (
    echo   FAIL: ngrok 未安裝 - 請到 https://ngrok.com/download 下載
    set /a FAIL+=1
)

:: 檢查 Git
echo [7/8] 檢查 Git...
git --version > nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=*" %%i in ('git --version') do echo   OK: %%i
    set /a PASS+=1
) else (
    echo   FAIL: Git 未安裝 - 請到 https://git-scm.com/ 下載
    set /a FAIL+=1
)

:: 檢查磁碟空間 (C 槽)
echo [8/8] 檢查磁碟空間...
for /f "tokens=3" %%a in ('dir /-c C:\ ^| findstr /i "bytes free"') do set FREE_BYTES=%%a
echo   INFO: 磁碟可用空間請確認 >= 20GB

echo.
echo ========================================
echo   結果: %PASS% 項通過 / %FAIL% 項失敗
echo ========================================
if %FAIL% == 0 (
    echo   所有環境檢查通過！可以繼續安裝。
) else (
    echo   請先安裝上述失敗的工具，再繼續安裝流程。
)
echo.
pause
