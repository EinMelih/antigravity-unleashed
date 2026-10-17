@echo off
title Antigravity Web - All Services
echo.
echo  ================================================
echo   Antigravity Web - Startup
echo  ================================================
echo.

if "%1"=="proxy" goto start_proxy
if "%1"=="api" goto start_api
if "%1"=="agents" goto start_agents
if "%1"=="all" goto start_all
goto start_all

:start_all
echo  Starting Proxy Server (Port 8000)...
start /B "Antigravity Proxy" cmd /c "python "%~dp0proxy_server.py" 2>&1"
timeout /t 2 /nobreak >nul

echo  Starting API Bridge (Port 8001)...
start /B "Antigravity API Bridge" cmd /c "python "%~dp0api_bridge.py" 2>&1"
timeout /t 2 /nobreak >nul

echo  Starting Session Manager (Port 8002)...
start /B "Antigravity Session Manager" cmd /c "python "%~dp0session_manager.py" 2>&1"
timeout /t 2 /nobreak >nul

echo  Starting Auto-Healer (Port 8007)...
start /B "Antigravity Auto-Healer" cmd /c "python "%~dp0auto_healer.py" 2>&1"
timeout /t 2 /nobreak >nul

echo  Starting Watchdog Monitor (Port 8010)...
start /B "Antigravity Watchdog" cmd /c "python "%~dp0watchdog_monitor.py" 2>&1"
timeout /t 2 /nobreak >nul

echo.
echo  ================================================
echo   All services started!
echo  ================================================
echo.
echo   Proxy:           http://127.0.0.1:8000
echo   API Bridge:      http://127.0.0.1:8001
echo   Session Manager: http://127.0.0.1:8002
echo   Auto-Healer:     http://127.0.0.1:8007
echo   Watchdog:        http://127.0.0.1:8010
echo.
echo   Health Checks:
echo     curl http://127.0.0.1:8001/health
echo     curl http://127.0.0.1:8002/health
echo     curl http://127.0.0.1:8007/health
echo     curl http://127.0.0.1:8010/health
echo.
echo   Press any key to stop all services...
echo  ================================================
pause >nul
taskkill /FI "WindowTitle eq Antigravity*" /F >nul 2>&1
goto end

:start_agents
echo  Starting Agent Services only (no Proxy/Bridge)...
echo.
echo  Starting Session Manager (Port 8002)...
start /B "Antigravity Session Manager" cmd /c "python "%~dp0session_manager.py" 2>&1"
timeout /t 2 /nobreak >nul

echo  Starting Auto-Healer (Port 8007)...
start /B "Antigravity Auto-Healer" cmd /c "python "%~dp0auto_healer.py" 2>&1"
timeout /t 2 /nobreak >nul

echo  Starting Watchdog Monitor (Port 8010)...
start /B "Antigravity Watchdog" cmd /c "python "%~dp0watchdog_monitor.py" 2>&1"
timeout /t 2 /nobreak >nul

echo.
echo  Agent services started!
echo  Press any key to stop...
pause >nul
taskkill /FI "WindowTitle eq Antigravity*" /F >nul 2>&1
goto end

:start_proxy
echo  Starting Proxy Server only...
python "%~dp0proxy_server.py"
goto end

:start_api
echo  Starting API Bridge only...
python "%~dp0api_bridge.py"
goto end

:end
