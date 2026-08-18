# Changelog

All notable WoWInterpreter changes are documented here.

## [2.2.0] - 2026-08-18

### Stable release
- Introduced KT08 as the primary visual transport, with physical pilot-based geometry and independent horizontal/vertical pitch derivation.
- Added CRC32 integrity, matching start/end sequence markers, strict UTF-8 validation and Lua double buffering for coherent frames.
- Added robust initial acquisition in Fullscreen and client-relative Windowed modes.
- Added automatic relocation after WoW moves, resizes or changes between Windowed and Fullscreen, including fractional physical rasterization.
- Added generation-aware overlay suppression so protected captures occur only after the Tk UI thread acknowledges that the overlay is hidden.
- Kept KT07 as a bounded legacy compatibility fallback with ambiguity rejection and fractional relocation support.
- Preserved English/Simplified Chinese translation behavior and sequence-aware duplicate suppression.
- Added real-raster regression fixtures and expanded protocol, acquisition, relocation, overlay and race-condition tests.
- Removed obsolete successful-runtime screenshot diagnostics and clarified transport logging.
- Updated runtime, addon, installer, build and documentation metadata for 2.2.0.

## [2.1.34] - 2026-08-13

### Stable release
- Migrated the visual chat transport from KT06 to KT07 with persistent geometry locking and validated symbol-grid calibration.
- Added reliable English <-> Simplified Chinese bidirectional translation.
- Fixed outgoing message envelope parsing so transport metadata such as OUT and You is not included in translated text.
- Added dynamic self labels (Me: / 我:) according to the translation direction.
- Preloads the NLLB translation model when **Start Translator** is selected, avoiding the long wait on the first /wi translation.
- Reduced idle CPU usage with ROI capture, fast anchor rejection and adaptive idle polling.
- Limited PyTorch runtime threads to reduce CPU usage while preserving translation performance.
- Protected the KT07 pixel-grid region from accidental overlay placement while keeping the overlay freely movable elsewhere.
- Closing the translation overlay now stops the Bridge process and releases the loaded translation model.
- Added Bridge process monitoring so the tray immediately synchronizes **Start Translator**, **Stop Translator** and **Status** when the overlay is closed.
- Updated installer, build scripts and English/Simplified Chinese documentation for 2.1.34.

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
