@echo off
setlocal
cd /d %~dp0
echo Building WoWInterpreter v2.2.0...
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -r requirements-runtime.txt pyinstaller
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --windowed --onedir ^
 --name WoWInterpreter ^
 --icon "assets\WoWInterpreter.ico" ^
 --collect-all PIL ^
 --collect-all pyperclip ^
 --collect-all transformers ^
 --collect-all sentencepiece ^
 --collect-all torch ^
 --collect-all sacremoses ^
 --collect-all pystray ^
 --hidden-import PIL.ImageGrab ^
 --hidden-import PIL.Image ^
 --hidden-import PIL.ImageTk ^
 --hidden-import pyperclip ^
 --hidden-import transformers ^
 --hidden-import torch ^
 --hidden-import sentencepiece ^
 --hidden-import tkinter ^
 --hidden-import tkinter.scrolledtext ^
 --hidden-import pystray._win32 ^
 --add-data "Bridge;Bridge" ^
 --add-data "assets;assets" ^
 WoWInterpreterTray.py
if errorlevel 1 exit /b 1
if not exist "dist\WoWInterpreter\WoWInterpreter.exe" exit /b 1
echo.
echo Build complete: dist\WoWInterpreter\WoWInterpreter.exe
echo Next: compile installer.iss with Inno Setup if you want Setup.exe.
pause
