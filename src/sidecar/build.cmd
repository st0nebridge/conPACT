@echo off
rem @module sidecar/build
rem @description Compile the Codex sidecar launcher to a native exe. The sidecar
rem              itself is Python (conpact.codex_sidecar); this is only the
rem              executable ChatGPT Desktop can spawn on Windows, which Node will
rem              not do for a .py or a .cmd. clang is preferred; cl.exe is the
rem              fallback. No dependencies beyond the Windows SDK import libs.
rem @input  none
rem @output codex_sidecar.exe beside this script; a non-zero exit on failure
setlocal
cd /d "%~dp0"

where clang >nul 2>&1
if %errorlevel%==0 (
    echo building with clang...
    clang -O2 -D_CRT_SECURE_NO_WARNINGS -o codex_sidecar.exe codex_launcher.c -lkernel32
    goto done
)

where cl >nul 2>&1
if %errorlevel%==0 (
    echo building with cl...
    cl /O2 /nologo /D_CRT_SECURE_NO_WARNINGS codex_launcher.c /Fe:codex_sidecar.exe /link kernel32.lib
    goto done
)

echo No C compiler found. Install LLVM ^(clang^) or the MSVC build tools.
exit /b 1

:done
if exist codex_sidecar.exe (
    echo built: %~dp0codex_sidecar.exe
) else (
    echo build failed
    exit /b 1
)
