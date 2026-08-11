WoWInterpreter 2.1 - Bilingual Installer

Installer languages:
- English
- Simplified Chinese (简体中文)

The installer deliberately asks the user to select the World of Warcraft
AddOns directory. It does not silently guess the WoW installation.

Example:
C:\Program Files (x86)\World of Warcraft\_classic_era_\Interface\AddOns

The installer then copies the addon to:
<selected AddOns folder>\WoWInterpreter

The Windows application is installed separately under the user's LocalAppData
Programs directory, so the user does not need to place the EXE inside WoW.

Optional installer tasks:
- Desktop shortcut
- Start WoWInterpreter with Windows (tray only; translator/Bridge remains
  stopped until the user selects Start translator)

Build:
1. Run build_release.bat.
2. It builds the self-contained application.
3. If Inno Setup 6 is installed, it also produces:
   installer\WoWInterpreter-2.1.4-Setup.exe

The already validated WoWInterpreter 2.1 application/Bridge/addon code is not
functionally changed by this installer update.
