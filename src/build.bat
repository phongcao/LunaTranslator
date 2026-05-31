@echo off
setlocal

for %%I in ("%~dp0.") do set "SRC_DIR=%%~fI"
set "NATIVE_DIR=%SRC_DIR%\NativeImpl\LunaHook"
set "NATIVEIMPL_DIR=%SRC_DIR%\NativeImpl"
set "RUNTIME_DIR=%SRC_DIR%\files\LunaHook"
set "BUILD_OUTPUT_DIR=%NATIVE_DIR%\builds\Release_win10"
set "PARALLEL=%NUMBER_OF_PROCESSORS%"
if not defined PARALLEL set "PARALLEL=4"

echo [1/8] Building NativeUtils (x64)...
call :build_target "%NATIVEIMPL_DIR%\build\x64_win10" ALL_BUILD || goto :error

echo [2/8] Copying NativeUtils DLLs...
robocopy "%NATIVEIMPL_DIR%\builds\_x64_win10" "%SRC_DIR%\files\DLL64" *.dll /NFL /NDL /NJH /NJS >nul
if exist "%NATIVEIMPL_DIR%\builds\_x64_win10\LunaSubprocess64.exe" (
    copy /y "%NATIVEIMPL_DIR%\builds\_x64_win10\LunaSubprocess64.exe" "%SRC_DIR%\files\LunaSubprocess64.exe" >nul
)

echo [3/8] Building LunaHook32.dll...
call :build_target "%NATIVE_DIR%\build\x86_win10_2" LunaHook || goto :error

echo [4/8] Building LunaHook64.dll...
call :build_target "%NATIVE_DIR%\build\x64_win10_2" LunaHook || goto :error

echo [5/8] Building LunaHost64.dll...
call :build_target "%NATIVE_DIR%\build\x64_win10_1" LunaHostDll || goto :error

echo [6/8] Copying runtime DLLs...
call :copy_required "%BUILD_OUTPUT_DIR%\LunaHook32.dll" "%RUNTIME_DIR%\LunaHook32.dll" || goto :error
call :copy_required "%BUILD_OUTPUT_DIR%\LunaHook64.dll" "%RUNTIME_DIR%\LunaHook64.dll" || goto :error
call :copy_required "%BUILD_OUTPUT_DIR%\LunaHost64.dll" "%RUNTIME_DIR%\LunaHost64.dll" || goto :error

echo [7/8] Copying optional runtime DLLs...
call :copy_optional "%BUILD_OUTPUT_DIR%\LunaHost32.dll" "%RUNTIME_DIR%\LunaHost32.dll"

echo [8/8] Done.
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