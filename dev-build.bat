@echo off
rem Builds LunaTranslator's native code for running from source and copies the
rem results into src\files. Also creates .venv (Python 3.13 + PyQt5) if missing.
rem Usage: dev-build.bat            build everything
rem        dev-build.bat nohook     skip LunaHook (faster when only NativeImpl changed)
setlocal
set ROOT=%~dp0
set SRC=%ROOT%src
set NI=%SRC%\NativeImpl
set LH=%NI%\LunaHook
set GEN=Visual Studio 17 2022
set SYSVER=-DCMAKE_SYSTEM_VERSION=10.0.26621.0

where cmake >nul 2>nul || (echo cmake not found on PATH. & goto :fail)

rem ---- Python environment ----
if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo === Creating .venv
    py -3.13 -m venv "%ROOT%.venv" || goto :fail
    "%ROOT%.venv\Scripts\python.exe" -m pip install --disable-pip-version-check PyQt5 tinycss2 || goto :fail
)

rem ---- NativeImpl: x64 everything, x86 only LunaSubprocess32 ----
call :build "%NI%" "build\x64_win10" "-A x64 -T host=x64 -DWIN10ABOVE=ON %SYSVER%" || goto :fail
call :build "%NI%" "build\x86_win10" "-A win32 -T host=x86 -DWIN10ABOVE=ON -DSTATIC_FORCE=ON -DBUILD_S_EXE_ONLY=ON %SYSVER%" || goto :fail

rem ---- LunaHook: x64 hook + host, x86 hook only ----
if /i not "%1"=="nohook" (
    call :build "%LH%" "build\x64_win10_2" "-A x64 -T host=x64 -DWIN10ABOVE=ON -DBUILD_HOST=OFF" || goto :fail
    call :build "%LH%" "build\x86_win10_2" "-A win32 -T host=x86 -DWIN10ABOVE=ON -DBUILD_HOST=OFF" || goto :fail
    call :build "%LH%" "build\x64_win10_1" "-A x64 -T host=x64 -DWIN10ABOVE=ON -DBUILD_HOOK=OFF" || goto :fail
)

rem ---- Copy into src\files (same layout as the release "merge" step) ----
echo === Copying native files into src\files
call :copy "%NI%\builds\_x64_win10" "%SRC%\files\DLL64" "*.dll" || goto :copyfail
call :copy "%NI%\builds\_x64_win10" "%SRC%\files" "LunaSubprocess64.exe" || goto :copyfail
call :copy "%NI%\builds\_x86_win10" "%SRC%\files" "LunaSubprocess32.exe" || goto :copyfail
if /i not "%1"=="nohook" (
    call :copy "%LH%\builds\Release_win10" "%SRC%\files\LunaHook" "*.dll" || goto :copyfail
)

echo.
echo Build finished. Start the app with dev-run.bat
exit /b 0

rem %1 = source dir, %2 = build dir (relative), %3 = configure options
:build
echo === Building %~2
if not exist "%~1\%~2\CMakeCache.txt" (
    cmake -S "%~1" -B "%~1\%~2" -G "%GEN%" %~3 || exit /b 1
)
cmake --build "%~1\%~2" --config Release --target ALL_BUILD -j %NUMBER_OF_PROCESSORS% -- /v:m /nologo || exit /b 1
exit /b 0

rem %1 = from, %2 = to, %3 = file pattern. robocopy returns 0-7 on success.
:copy
robocopy "%~1" "%~2" %~3 /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 exit /b 1
exit /b 0

:copyfail
echo.
echo Copy failed. Close LunaTranslator (it locks these files) and run dev-build.bat again.
exit /b 1

:fail
echo.
echo Build failed.
exit /b 1
