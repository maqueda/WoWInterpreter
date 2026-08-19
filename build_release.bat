@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "STAGEROOT=C:\WI21\stage"

echo ============================================================
echo  WoWInterpreter 2.2.0 - Release Builder
echo ============================================================
echo.

echo [1/6] Building self-contained application...
call build_windows.bat
if errorlevel 1 goto :fail
if not exist "dist\WoWInterpreter\WoWInterpreter.exe" goto :fail
for %%M in (kt08_protocol.py kt08_geometry.py kt08_decoder.py kt08_tracker.py runtime_housekeeping.py) do (
  if not exist "dist\WoWInterpreter\_internal\Bridge\%%M" (
    echo ERROR: Frozen runtime missing Bridge\%%M.
    goto :fail
  )
)

echo.
echo [2/6] Pruning development/metadata trees from frozen runtime...
if exist "dist\WoWInterpreter\_internal\torch\include" rmdir /s /q "dist\WoWInterpreter\_internal\torch\include"
if exist "dist\WoWInterpreter\_internal\torch\share\cmake" rmdir /s /q "dist\WoWInterpreter\_internal\torch\share\cmake"

REM IMPORTANT: Keep *.dist-info / *.egg-info metadata.
REM transformers uses importlib.metadata at runtime to validate versions of
REM tqdm, tokenizers, huggingface-hub, numpy, packaging, etc.
REM Only prune deep non-runtime license/test trees inside metadata.
for /d %%D in ("dist\WoWInterpreter\_internal\*.dist-info") do (
  if exist "%%D\licenses" rmdir /s /q "%%D\licenses"
  if exist "%%D\tests" rmdir /s /q "%%D\tests"
  if exist "%%D\test" rmdir /s /q "%%D\test"
)
for /d %%D in ("dist\WoWInterpreter\_internal\*.egg-info") do (
  if exist "%%D\licenses" rmdir /s /q "%%D\licenses"
  if exist "%%D\tests" rmdir /s /q "%%D\tests"
  if exist "%%D\test" rmdir /s /q "%%D\test"
)

echo.
echo Verifying required Python package metadata...
set "METAFAIL="
for %%P in (tqdm transformers torch tokenizers huggingface_hub packaging numpy) do (
  dir /b /ad "dist\WoWInterpreter\_internal\%%P-*.dist-info" >nul 2>&1
  if errorlevel 1 (
    echo WARNING: metadata for %%P was not found in the frozen runtime.
  ) else (
    echo Metadata OK: %%P
  )
)

echo.
echo [3/6] Creating SHORT staging path: %STAGEROOT%
if exist "C:\WI21" rmdir /s /q "C:\WI21"
mkdir "%STAGEROOT%\app"
mkdir "%STAGEROOT%\addon"

robocopy "dist\WoWInterpreter" "%STAGEROOT%\app" /E /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 goto :stage_fail
robocopy "Addon\WoWInterpreter" "%STAGEROOT%\addon" /E /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 goto :stage_fail

echo.
echo [4/6] Verifying staged executable...
if not exist "%STAGEROOT%\app\WoWInterpreter.exe" (
  echo ERROR: staged executable missing.
  goto :fail
)

echo.
echo [5/6] Looking for Inno Setup 6...

REM Validate installer documentation inputs before compiling Inno Setup.
if not exist "Documentation\WoWInterpreter-2.2.0-User-Guide-English.docx" (
  echo ERROR: Missing English user guide required by installer.
  exit /b 1
)
if not exist "Documentation\WoWInterpreter-2.2.0-User-Guide-Chinese-Simplified.docx" (
  echo ERROR: Missing Simplified Chinese user guide required by installer.
  exit /b 1
)

set "ISCC="
for %%I in (ISCC.exe) do if not "%%~$PATH:I"=="" set "ISCC=%%~$PATH:I"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo ERROR: Inno Setup 6 not found.
  goto :fail
)

echo.
echo [6/6] Building installer from short stage...
if exist "installer" rmdir /s /q "installer"
mkdir "installer"
"%ISCC%" /DStageRoot="%STAGEROOT%" "installer.iss"
if errorlevel 1 goto :inno_fail

if not exist "installer\WoWInterpreter-2.2.0-Setup.exe" (
  echo ERROR: Setup.exe not found after compilation.
  goto :fail
)

echo.
echo Cleaning temporary short stage...
rmdir /s /q "C:\WI21"

echo.
echo ============================================================
echo  RELEASE COMPLETE
echo ============================================================
echo "%CD%\installer\WoWInterpreter-2.2.0-Setup.exe"
start "" explorer.exe /select,"%CD%\installer\WoWInterpreter-2.2.0-Setup.exe"
pause
exit /b 0

:stage_fail
echo ERROR: Failed copying files into %STAGEROOT%.
goto :fail

:inno_fail
echo.
echo ERROR: Inno Setup compilation failed.
echo Temporary stage retained at %STAGEROOT% for inspection.
goto :fail

:fail
echo.
echo Release build failed.
pause
exit /b 1
