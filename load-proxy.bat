@echo off
chcp 65001 >nul
REM ---------------------------------------------------------------------------
REM Load corporate proxy settings from proxy.env.
REM Called by build-all.bat and run-all.bat via "call load-proxy.bat".
REM Variables are set in the current cmd session and inherited by every
REM process started from it: pip, pyinstaller, and both EXE files.
REM ---------------------------------------------------------------------------

if not exist "proxy.env" (
    echo [proxy] proxy.env not found - running without proxy
    echo         To enable: copy proxy.env.example to proxy.env
    goto :force_local_bypass
)

echo [proxy] Reading proxy.env
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("proxy.env") do (
    if not "%%~A"=="" if not "%%~B"=="" (
        set "%%~A=%%~B"
        echo         %%~A=%%~B
    )
)

:force_local_bypass
REM The GUI talks to the API on localhost:8001. If that address goes through
REM the corporate proxy the request never comes back, so localhost is always
REM added to the bypass list - even if proxy.env forgot it. Duplicate entries
REM in NO_PROXY are harmless, so this just prepends unconditionally.
if defined NO_PROXY (
    set "NO_PROXY=127.0.0.1,localhost,%NO_PROXY%"
) else (
    set "NO_PROXY=127.0.0.1,localhost"
)

REM httpx (LLM calls) and requests (GUI -> API) read the lowercase names on
REM some builds - set both so behaviour does not depend on that.
if defined HTTP_PROXY  set "http_proxy=%HTTP_PROXY%"
if defined HTTPS_PROXY set "https_proxy=%HTTPS_PROXY%"
set "no_proxy=%NO_PROXY%"

echo [proxy] HTTPS_PROXY=%HTTPS_PROXY%
echo [proxy] NO_PROXY=%NO_PROXY%
exit /b 0
