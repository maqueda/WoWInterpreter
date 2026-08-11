# Contributing

Thanks for your interest in WoWInterpreter.

For bug reports, please include:
- WoWInterpreter version
- Windows version
- WoW client/version
- whether the KT06 grid appears
- the relevant section of `WoWInterpreter.log`
- exact steps to reproduce

Please do not include private chat content in logs/screenshots unless necessary and intentionally shared.

For code changes:
1. Keep the WoW addon and Windows Bridge protocol compatible.
2. Avoid increasing background CPU usage.
3. Preserve the explicit Start/Stop behavior.
4. Test both EN→ZH and ZH→EN.
5. Test a frozen PyInstaller build, not only Python source execution.
6. Test installation through the Inno Setup release package.
