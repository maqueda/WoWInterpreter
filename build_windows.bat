@echo off
setlocal
cd /d %~dp0
echo Building WoWInterpreter v2.1...
py -m pip install --upgrade pip
py -m pip install -r requirements-runtime.txt pyinstaller
py -m PyInstaller --noconfirm --clean --windowed --onedir ^
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
echo.
echo Build complete: dist\WoWInterpreter\WoWInterpreter.exe
echo Next: compile installer.iss with Inno Setup if you want Setup.exe.
pause
