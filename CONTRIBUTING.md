# Contributing

Thanks for your interest in WoWInterpreter.

Before making code changes, please read the [Development Guide](Documentation/DEVELOPMENT.md). It documents the KT08-first architecture, KT07 compatibility fallback, addon/Bridge requirements, debugging workflow, performance constraints, testing expectations and release process.

For bug reports, please include:
- WoWInterpreter version
- Windows version
- WoW client/version
- whether the visual transport appears and whether the log identifies KT08 or KT07
- the relevant section of `WoWInterpreter.log`
- exact steps to reproduce

Please do not include private chat content in logs/screenshots unless necessary and intentionally shared.

For code changes:
1. Keep the WoW addon and Windows Bridge protocol compatible.
2. Avoid increasing background CPU usage.
3. Preserve the explicit Start/Stop behavior.
4. Test both EN → ZH and ZH → EN.
5. Test a frozen PyInstaller build, not only Python source execution.
6. Test installation through the Inno Setup release package.
