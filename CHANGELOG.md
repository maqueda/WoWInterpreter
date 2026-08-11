# Changelog

All notable WoWInterpreter changes are documented here.

## [2.1.4] - 2026-08-11

### Stable release
- Validated complete Windows installer → tray → Bridge → KT06 → NLLB → overlay translation flow.
- English ↔ Simplified Chinese translation.
- Scrollable translation overlay and recent-message workflow.
- `/wi` command family with manual/automatic modes.
- Windows notification-area Start / Stop / Status / Log / Exit controls.
- Lazy NLLB loading so the model is loaded only when translation is requested.
- Bridge stdout/stderr persisted to `WoWInterpreter.log`.
- Fixed frozen-runtime Pillow `Image` import used by adaptive calibration.
- Preserved package metadata required by Transformers dependency checks.
- Short-path installer staging to avoid deep PyTorch path failures.
- Removed non-runtime Torch development headers/CMake data from release staging.
- Bilingual English / Simplified Chinese Inno Setup installer.
- Explicit AddOns-directory selection during installation.
- English and Simplified Chinese end-user documentation included in the installer.

## [2.1.0]
- Promoted the proven tray-managed Bridge architecture to the stable 2.1 line.

## [2.0.x]
- Added tray diagnostics, frozen `--bridge` child mode, resource fixes and explicit Bridge dependency packaging.
