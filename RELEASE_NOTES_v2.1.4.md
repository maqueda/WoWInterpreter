# WoWInterpreter v2.1.4

First stable public release of WoWInterpreter.

WoWInterpreter helps English-speaking and Chinese-speaking World of Warcraft Classic Era players communicate using an in-game addon plus a Windows translation bridge.

## Highlights

- English ↔ Simplified Chinese translation
- Whisper / party / raid / say / yell oriented workflow
- `/wi <text>` direct translation
- Recent-message selection
- Scrollable translation overlay
- Tray-based Start / Stop controls
- Translation engine remains stopped until explicitly started
- English / Simplified Chinese installer
- Installer asks for the WoW `Interface\AddOns` directory
- No separate Python installation required
- English and Chinese user guides included

## Installation

Download:

`WoWInterpreter-2.1.4-Setup.exe`

Run the installer, choose English or Simplified Chinese, and select your World of Warcraft Classic Era `Interface\AddOns` folder when prompted.

Then start WoWInterpreter from the Windows Start menu, right-click the WI tray icon → **Start translator**, restart/start WoW, and test:

`/wi this is a test`

## Important model notice

WoWInterpreter uses `facebook/nllb-200-distilled-600M`, which is separately licensed under CC BY-NC 4.0. Its model card describes it as a research model and not as a production-deployment model. Review `THIRD_PARTY_NOTICES.md` before commercial use or redistribution.

## Known notes

- The first translation after Start can take longer while NLLB is loaded/downloaded.
- Windows SmartScreen may warn about an unsigned installer.
- Machine translation can be inaccurate.
