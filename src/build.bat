@echo off
setlocal

for %%I in ("%~dp0.") do set "SRC_DIR=%%~fI"
set "NATIVE_DIR=%SRC_DIR%\NativeImpl\LunaHook"
set "RUNTIME_DIR=%SRC_DIR%\files\LunaHook"
set "BUILD_OUTPUT_DIR=%NATIVE_DIR%\builds\Release_win10"
set "PARALLEL=%NUMBER_OF_PROCESSORS%"
if not defined PARALLEL set "PARALLEL=4"

echo [1/6] Building LunaHook32.dll...
call :build_target "%NATIVE_DIR%\build\x86_win10_2" LunaHook || goto :error

echo [2/6] Building LunaHook64.dll...
call :build_target "%NATIVE_DIR%\build\x64_win10_2" LunaHook || goto :error

echo [3/6] Building LunaHost64.dll...
call :build_target "%NATIVE_DIR%\build\x64_win10_1" LunaHostDll || goto :error

echo [4/6] Copying runtime DLLs...
call :copy_required "%BUILD_OUTPUT_DIR%\LunaHook32.dll" "%RUNTIME_DIR%\LunaHook32.dll" || goto :error
call :copy_required "%BUILD_OUTPUT_DIR%\LunaHook64.dll" "%RUNTIME_DIR%\LunaHook64.dll" || goto :error
call :copy_required "%BUILD_OUTPUT_DIR%\LunaHost64.dll" "%RUNTIME_DIR%\LunaHost64.dll" || goto :error

echo [5/6] Copying optional runtime DLLs...
call :copy_optional "%BUILD_OUTPUT_DIR%\LunaHost32.dll" "%RUNTIME_DIR%\LunaHost32.dll"

echo [6/6] Done.
echo Runtime DLLs updated in "%RUNTIME_DIR%".
exit /b 0

:build_target
set "BUILD_DIR=%~1"
set "TARGET_NAME=%~2"
if not exist "%BUILD_DIR%\CMakeCache.txt" (
    echo Missing build directory: "%BUILD_DIR%"
    exit /b 1
)
cmake --build "%BUILD_DIR%" --config Release --target %TARGET_NAME% --parallel %PARALLEL%
if errorlevel 1 exit /b 1
exit /b 0

:copy_required
set "SRC_FILE=%~1"
set "DST_FILE=%~2"
if not exist "%SRC_FILE%" (
    echo Missing build output: "%SRC_FILE%"
    exit /b 1
)
copy /y "%SRC_FILE%" "%DST_FILE%" >nul
if errorlevel 1 exit /b 1
exit /b 0

:copy_optional
set "SRC_FILE=%~1"
set "DST_FILE=%~2"
if not exist "%SRC_FILE%" (
    echo Optional output not found, skipping: "%SRC_FILE%"
    exit /b 0
)
copy /y "%SRC_FILE%" "%DST_FILE%" >nul
if errorlevel 1 exit /b 1
exit /b 0

:error
echo Build failed.
exit /b 1