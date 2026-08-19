# WoWInterpreter Development Guide

This document is the technical guide for developers who want to understand, debug, build, or contribute to WoWInterpreter.

WoWInterpreter is a hybrid World of Warcraft Classic Era + Windows application. The in-game addon uses a visual transport to move UTF-8 chat payloads from WoW to a local Windows process. The Windows Bridge captures that transport, validates and decodes it, translates the message locally with NLLB, and displays the result in an overlay.

This guide describes the architecture used by the 2.2.x line. When changing the protocol or runtime lifecycle, update this document together with the implementation.

## 1. Architecture overview

```text
World of Warcraft chat or /wi command
              |
              v
Addon/WoWInterpreter/WoWInterpreter.lua
              |
              | KT08 visual transport
              v
Desktop screen capture
              |
              v
Bridge/bridge.py
              |
              | validated UTF-8 payload
              v
facebook/nllb-200-distilled-600M
              |
              v
English <-> Simplified Chinese translation
              |
              v
Tkinter translation overlay
```

The Windows tray application owns the Bridge lifecycle:

```text
WoWInterpreterTray.py
        |
        +-- Start translator --> Bridge child process
        +-- Stop translator  --> terminate Bridge
        +-- Status
        +-- Open diagnostic log
        `-- Exit WoWInterpreter
```

There are three main components:

1. **WoW addon** - observes chat, provides `/wi`, keeps recent messages, and encodes requests into KT08.
2. **Windows Bridge** - captures KT08 first with a safe KT07 legacy fallback, decodes payloads, runs translation, manages the overlay, and records diagnostics.
3. **Tray application** - provides the Windows lifecycle and launches/stops the Bridge.

The installer packages the addon and the frozen Windows application together.

## 2. Repository layout

```text
WoWInterpreter/
|-- .github/
|   |-- ISSUE_TEMPLATE/
|   |-- pull_request_template.md
|   `-- workflows/windows-release.yml
|-- Addon/WoWInterpreter/
|   |-- WoWInterpreter.lua
|   `-- WoWInterpreter.toc
|-- Bridge/
|   |-- bridge.py
|   `-- requirements.txt
|-- Documentation/
|   |-- DEVELOPMENT.md
|   |-- WoWInterpreter-<version>-User-Guide-English.docx
|   `-- WoWInterpreter-<version>-User-Guide-Chinese-Simplified.docx
|-- assets/
|-- installer-languages/
|-- WoWInterpreterTray.py
|-- requirements-runtime.txt
|-- build_windows.bat
|-- build_release.bat
|-- installer.iss
|-- README.md
|-- README_zh-CN.md
|-- CONTRIBUTING.md
|-- SECURITY.md
|-- THIRD_PARTY_NOTICES.md
`-- LICENSE
```

### Important files

**`Addon/WoWInterpreter/WoWInterpreter.lua`** contains the WoW-side protocol encoder, chat event handling, recent-message picker, `/wi` commands, translation modes, and ChatFrame geometry publication.

**`Bridge/bridge.py`** contains KT08-first capture and calibration with KT07 fallback, payload validation, translation, WoW terminology normalization, overlay behavior, CPU/performance diagnostics, and the Bridge event loop.

**`WoWInterpreterTray.py`** owns the Windows notification-area icon and Bridge child process. In a frozen build the same executable is launched with `--bridge`; in source mode Python launches the same entry point with `--bridge`.

**`installer.iss`** defines the Inno Setup installer, release version, packaged application, addon installation, documentation, and installer UI.

**`.github/workflows/windows-release.yml`** automates the Windows release build and release artifacts.

## 3. Development environment

Recommended environment:

- Windows 10 or Windows 11
- Python 3.11
- Git
- World of Warcraft Classic Era for end-to-end addon testing
- Inno Setup 6 for installer testing
- A Python virtual environment

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-runtime.txt
python -m pip install pyinstaller
```

If PowerShell execution policy prevents activation:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-runtime.txt
```

Do not commit `.venv`, generated PyInstaller output, downloaded model data, logs, or diagnostic screenshots.

## 4. Running from source

The normal development entry point is:

```powershell
python .\WoWInterpreterTray.py
```

This starts the tray application but intentionally leaves the translator stopped. Use **Start translator** from the tray menu to launch the Bridge.

Direct Bridge mode can also be useful for debugging:

```powershell
python .\WoWInterpreterTray.py --bridge
```

A fix must still be tested through the normal tray-managed Start/Stop lifecycle before it is considered complete.

## 5. Tray and process lifecycle

The tray process:

- enforces a single application instance;
- starts one Bridge child process;
- updates menu state according to the child process;
- watches for Bridge exit;
- stops the Bridge on **Stop translator**;
- writes lifecycle information to `WoWInterpreter.log`.

A critical lifecycle rule is:

> Closing the translation overlay is equivalent to Stop translator.

The Bridge exits when the overlay window is closed. The tray observes that child exit and changes its state back to **Stopped**. This prevents NLLB/PyTorch from remaining active invisibly.

Do not change overlay-close behavior independently of tray state.

## 6. Addon behavior

The addon listens to supported Classic Era chat events including say, yell, party, raid, guild, and whispers.

It maintains recent messages in Lua. In manual mode this allows messages to be remembered without sending every incoming chat line to the Windows Bridge.

### Translation modes

- **manual** - remember incoming messages; translate only when requested.
- **auto** - automatically send supported incoming chat to the Bridge.
- **off** - disable incoming translation.

### Commands

```text
/wi <text>   translate text
/wi last     translate the most recent captured message
/wi list     open the recent-message picker
/wi manual   use manual incoming translation
/wi auto     use automatic incoming translation
/wi off      disable incoming translation
/wi help     display command help
```

The addon also publishes ChatFrame1 geometry periodically through a `META` payload.

## 7. KT08 visual transport

KT08 is emitted by current addons. The Bridge recognizes KT08 first and keeps
the safe KT07 decoder only as a migration fallback for older addon versions.
A damaged frame identified by KT08 pilots is never reinterpreted as KT07.

The production receive path is:

```text
WoW addon -> hidden KT08 buffer -> RGB/YCM presence hint
          -> bounded screen capture -> four-pilot component detection
          -> analytical X/Y geometry -> grayscale binary sampling
          -> MAGIC/version/flags/length -> matching sequences -> CRC32
          -> UTF-8 -> tracker/duplicate suppression -> Bridge/NLLB -> overlay
```

Presence is only a cheap reason to capture. Geometry and payload acceptance
come from the four physical pilots and the complete strict binary frame.

### Binary frame

All multi-byte integers are unsigned big-endian:

```text
"KT08"[4] | VERSION[1] | FLAGS[1] | SEQUENCE_START[2] | LENGTH[2]
PAYLOAD[LENGTH] | SEQUENCE_END[2] | CRC32[4]
```

Version is 1, flags must be zero, and payload length is 0..180 bytes. Sequence
increments for every logical publication and wraps from 65535 to 0. Start and
end sequence must match. CRC-32/IEEE uses reflected polynomial `0xEDB88320`,
initial/final XOR `0xFFFFFFFF`, and covers every byte from MAGIC through
SEQUENCE_END. UTF-8 validation occurs only after sequence and CRC validation.
Frames are rejected for truncation or trailing bytes, wrong MAGIC, unsupported
version/flags, excessive length, mismatched sequences, CRC mismatch or invalid
UTF-8. Payload language and textual plausibility never participate in acceptance.

### Physical synchronization

The payload occupies 32x25 grayscale cells inside a 36x29 logical grid. Four
fixed saturated 2x2-cell pilots sit at grid-center coordinates `(1,1)`,
`(35,1)`, `(1,28)`, and `(35,28)` in red, green, blue, and yellow.
One logical CELL of black separation sits between the RGB/YCM discovery strip
and the pilot grid. This prevents the strip's red block and the TL red pilot
from becoming one connected raster component.

```text
pitch_x = (TR.x - TL.x) / 34
pitch_y = (BL.y - TL.y) / 27
data_origin = TL_center + (pitch_x, pitch_y)
```

The bottom-right pilot independently checks both projections. Pilot centers
are measured from rendered pixels, so alternating 3/4-pixel cell widths and
different horizontal/vertical scaling do not require integer raster pitches.
The RGB/YCM strip remains only a cheap presence hint; it never establishes
data geometry or frame correctness.

### Publication coherence

The Lua producer owns two complete render buffers. For each publication it
increments the 16-bit sequence, constructs the complete body and CRC, clears
and writes every data cell in the hidden buffer, then hides the old buffer and
shows the completed one. This prevents intentionally exposing a partially
updated logical frame. Matching start/end sequences and CRC provide independent
receiver-side coherence and integrity checks.

### Initial acquisition and relocation

Fullscreen acquisition uses the bounded top-left transport ROI. Windowed
startup derives bounded presence and 420x350 probe rectangles from the current
WoW client origin; normal acquisition does not scan the desktop with Python
pixel loops.

Initial Windowed acquisition and relocation share one generation-aware overlay
suppression coordinator. The worker requests suppression and cannot call the
protected `ImageGrab` path until Tk has withdrawn the overlay and acknowledged
that exact generation. A decoded candidate remains side-effect-free until a
forced native-state refresh proves that its client snapshot/generation is still
current. Only then is absolute geometry committed. The hidden overlay is placed
outside the new protected rectangle before restoration.

The native observer detects client rectangle, display rectangle, style and DPI
changes caused by moves, resizes and Windowed/Fullscreen transitions. Each
change creates a newer relocation generation. Old captures cannot commit, old
ACKs cannot authorize newer captures, and stale restore requests cannot expose
the overlay. Temporary transport absence is expected during rendering and
leaves relocation pending for the next bounded observation.

Tk thread ownership is strict:

- The worker monitors native state, manages generations, gates/captures images,
  decodes, validates, commits trackers and publishes UI requests.
- The Tk thread alone calls `withdraw()`, `deiconify()`, `geometry()`,
  `update_idletasks()` and other widget APIs.

### KT07 legacy fallback

KT07 remains only for compatibility with older addon publications. Dispatch is
deliberately asymmetric: a fully valid KT08 frame uses KT08; when no usable
KT08 pilots/geometry identify KT08, the bounded KT07 fallback may be attempted;
a positively identified but invalid KT08 frame is rejected and is never
reinterpreted as KT07.

It is **not OCR**. Text is encoded into a deterministic grid of grayscale symbols and decoded numerically from screen pixels.

### Why visual transport?

WoW addons cannot simply open a local socket or execute the Python Bridge. The
visual transport provides a narrow one-way channel through UI pixels visible to
both the game and local capture process.

### Frame constants

```text
MAX_BYTES = 180
COLS      = 32
CELL      = 4 logical UI units
MAGIC     = [75, 84, 48, 55]   # ASCII: KT07
```

Each byte is represented by four base-4 grayscale symbols.

The Bridge reconstructs a byte as:

```text
byte = d0*64 + d1*16 + d2*4 + d3
```

### Anchor

KT07 begins with a deterministic six-block color anchor:

```text
Red | Green | Blue | Yellow | Cyan | Magenta
```

The Bridge first performs a cheap top-left prefilter. More expensive anchor localization only runs when the signature is plausible.

Preserving this idle fast path is important for CPU usage.

### Symbol-grid calibration

The anchor provides an approximate physical scale and region. The Bridge then searches below it for the real grayscale symbol grid.

Calibration is accepted when the first four decoded bytes match:

```text
75 84 48 55
```

or `KT07`.

Anchor geometry and symbol geometry must not be assumed to be pixel-identical. WoW UI scale, Windows DPI, and interpolation can alter the physical symbol pitch. The Bridge therefore calibrates the actual symbol origin and pitch from MAGIC.

### Payload frame

```text
MAGIC[4 bytes]
LENGTH[1 byte]
PAYLOAD[LENGTH bytes]
CHECKSUM[1 byte]
```

The payload is UTF-8.

Checksum:

```text
(sum(MAGIC) + LENGTH + sum(PAYLOAD_BYTES)) % 256
```

Frames with invalid length, unreadable symbols, checksum mismatch, or invalid UTF-8 must be rejected.

KT07 recovery remains bounded and supports fractional pitch, but KT07 derives
geometry through raster searches and uses only an additive 8-bit checksum. Its
initial consensus rejects competing payload/geometries, yet it does not provide
KT08-level integrity and remains a compatibility path.

### Visibility and queueing

Legacy KT07 producers display a payload for approximately three seconds and
serialize queued payloads so frames do not overwrite one another.

Changes to timing must leave the capture loop enough time to observe a complete stable frame.

## 8. KT07 message envelopes

Application messages use tab-separated records such as:

```text
OUT<TAB>author<TAB>text
IN<TAB>author<TAB>text
CHATOUT<TAB>author<TAB>text
META<TAB>CHAT1<TAB>geometry
```

Record semantics are part of the addon/Bridge contract. Changes must update both sides together.

Protocol metadata must never be translated as user text. For example, the Bridge strips the `OUT<TAB>author<TAB>` envelope before passing the actual message to NLLB.

## 9. Capture and geometry

The visual transport is anchored near the top-left of the WoW client. The
Bridge protects the validated KT08 or KT07 rectangle from its own overlay.

The overlay can be moved and resized by the user, but it must not settle on top of the transport.

When changing geometry logic:

- preserve user freedom outside the protected area;
- never let the overlay cover the active transport;
- account for WoW effective UI scale;
- remember that WoW and Windows/Tk coordinate systems differ;
- test multiple UI scales/resolutions when possible.

## 10. Translation pipeline

Current model:

```text
facebook/nllb-200-distilled-600M
```

Language identifiers:

```text
English:             eng_Latn
Simplified Chinese:  zho_Hans
```

Direction is selected automatically: Chinese input is translated to English; other supported input is translated to Simplified Chinese.

### CPU behavior

The expensive NLLB/PyTorch runtime belongs to the Bridge rather than the always-running tray shell.

CPU behavior is a project requirement. A functional change that creates substantial continuous background CPU usage should be treated as a regression unless the trade-off is justified.

### WoW terminology normalization

NLLB output is conservatively normalized for common WoW terminology such as battlegrounds, dungeons, raids, roles, classes, guild/party terminology, and selected Classic cities.

Rules should be source-conditioned and narrowly scoped.

When adding terminology:

1. reproduce the undesirable raw output;
2. add the narrowest possible rule;
3. test both translation directions;
4. include examples in the pull request.

## 11. Overlay

The translation UI is implemented with Tkinter.

Two overlay invariants are especially important:

1. it must remain clear of the active transport region;
2. closing it must terminate the Bridge.

Both must be regression-tested after overlay changes.

## 12. Diagnostics

The normal application writes:

```text
WoWInterpreter.log
```

The file lives beside `WoWInterpreter.exe`. The Tray is its only writer: Bridge
stdout/stderr is relayed to the Tray over a pipe. The current file is limited
to approximately 5 MiB and three backups (`.1`, `.2`, `.3`) are retained, for
approximately 20 MiB total. Rotation closes each append before renaming, so a
Bridge restart neither truncates the log nor creates a second file owner.

Useful diagnostic prefixes may include:

```text
[BRIDGE]
[CAPTURE]
[TRANSPORT]
[KT08]
[KT07]
[pixel]
[CPU]
[PERF]
[OVERLAY]
[debug]
```

Failure-only transport diagnostics can include:

- `debug_capture.png`: most recent throttled generic KT07 anchor failure;
- `kt07_initial_ambiguity.png/.txt`: exact frame plus competing validated
  candidates when KT07 initial consensus is ambiguous;
- `kt07_relocation_failure.png`, `_reduced.png`, `_closest.png` and `.txt`:
  overwritten bounded KT07 discovery evidence;
- `kt07_relocation_failure_<generation>_validation.png/.txt`: first strict
  KT07 validation failure for a generation;
- `kt08_initial_failure_<counter>.png/.txt`: first immutable KT08 failure in
  one visible initial-acquisition interval;
- `kt08_relocation_failure_<generation>_validation.png/.txt`: first KT08
  relocation failure for a generation;
- `kt07_visible_capture.png`, `kt07_visible_crop.png` and `kt07_geometry.txt`:
  one legacy KT07 geometry evidence set.

Only explicitly recognized files inside the runtime `Bridge` directory are
eligible for cleanup. PNG/TXT files for one numbered event form one set, and
the ten most recently modified sets are retained globally. Unknown files,
repository fixtures under `tests/fixtures`, assets and documentation are never
eligible. Cleanup runs once during Bridge initialization and after a diagnostic
is written, never in the capture loop or normal translation path.

The PNG is the raw or bounded capture used by the decoder; its paired TXT
contains geometry, candidate, validation and native-generation evidence. Normal
successful messages do not write transport screenshots. When reporting a
failure, collect `WoWInterpreter.log` (plus recent numbered backups when the
event is older) and the matching PNG/TXT pair.

Diagnostic screenshots can contain visible game content. Inspect and redact them before posting publicly.

Healthy NLLB initialization includes:

```text
[BRIDGE] Loading NLLB model: facebook/nllb-200-distilled-600M
[BRIDGE] NLLB ready.
```

## 13. Debugging the visual transport

Debug transport failures in this order:

1. **Does the KT08/KT07 grid appear in WoW?**
   - No: investigate addon/command/event handling.
   - Yes: continue with the Bridge.

2. **Can the Bridge find the RGB/YCM anchor?**
   - Check UI scale, DPI, resolution, occlusion, and diagnostic captures.

3. **Can KT08 find all four pilots and validate the binary frame?**
   - Inspect component candidates, derived X/Y pitch, BR residual, sequences
     and CRC. For an older KT07 frame, inspect MAGIC symbol calibration.

4. **Are CRC/checksum failures persistent?**
   - KT08 CRC failures and KT07 checksum failures usually indicate incorrect
     sampling geometry, occlusion or frame timing; do not weaken validation.

5. **Is the correct record envelope decoded?**
   - Verify protocol parsing before debugging NLLB.

6. **Is NLLB ready?**
   - Keep transport failures separate from model/runtime failures.

Do not solve capture bugs by weakening checksum validation.

## 14. Performance rules

WoWInterpreter runs beside a game, so background resource usage matters.

- Preserve the cheap idle detection path.
- Avoid continuous expensive full-screen scanning.
- Avoid busy loops.
- Run expensive work only when the bounded transport presence hint is plausible.
- Do not increase PyTorch thread counts casually.
- Compare idle CPU behavior as well as active translation latency.
- Review performance diagnostics after capture changes.

A feature is not complete if it works but leaves the CPU unnecessarily busy while idle.

## 15. Building on Windows

### Frozen development build

Use:

```bat
build_windows.bat
```

A frozen build is important because imports, resources, Transformers metadata, Pillow, and `--bridge` child execution can differ from source mode.

### Full release build

Use:

```bat
build_release.bat
```

The release builder creates the PyInstaller application, stages runtime files, includes the addon, and invokes Inno Setup to produce the versioned installer.

PyInstaller adds `Bridge/` and `assets/` to the frozen application. The release
script explicitly verifies that `kt08_protocol.py`, `kt08_geometry.py`,
`kt08_decoder.py` and `kt08_tracker.py` exist in the frozen Bridge tree before
staging. Inno Setup packages that runtime, the addon and the two versioned user
guides. Repository tests and `tests/fixtures` are not installer inputs.

Packaging changes must be tested with a complete Windows release build.

## 16. GitHub Actions and releases

The Windows workflow is:

```text
.github/workflows/windows-release.yml
```

Pull requests can validate release packaging without publishing a public release.

The intended tagged release flow is:

```text
branch
  |
pull request
  |
merge to main
  |
prepare version
  |
tag vX.Y.Z
  |
push tag
  |
GitHub Actions
  |
  +-- PyInstaller
  +-- runtime/build validation
  +-- Inno Setup
  +-- SHA-256
  `-- release artifacts
```

The Git tag and application/installer version must remain consistent.

The final installer should be accompanied by SHA-256 information so users can verify the exact binary they downloaded.

## 17. Version consistency

Release versions may appear in:

- `installer.iss`;
- tray/application strings;
- addon `.toc`;
- addon help/version output;
- README download instructions;
- documentation filenames;
- `CHANGELOG.md`.

Search for the previous version before tagging, but do not blindly replace historical changelog references.

Example:

```text
installer version 2.1.35 -> tag v2.1.35
```

## 18. Testing checklist

Run the complete automated suite from the repository root:

```powershell
python -m unittest discover -s tests -p "test_*.py"
git diff --check
```

The suite covers KT08 framing, CRC, sequence wrap/mismatch, UTF-8, physical
pilots, fractional/anisotropic rasterization, initial Fullscreen and Windowed
acquisition, relocation, overlay ACK/generations, duplicate suppression and the
KT07 fallback. Real PNGs in `tests/fixtures` preserve Windows raster behavior:

- `kt07_relocation_failure_6_validation.png`: fractional Windowed KT07 pitch;
- `kt07_initial_ambiguity.png/.txt`: competing Fullscreen KT07 geometries;
- `kt08_initial_failure_1/2.png/.txt`: real KT08 acquisition with duplicate
  anchor/pilot colors;
- `kt08_initial_failure_3/4.png/.txt`: overlay-occluded KT08 captures that must
  remain rejected.

These are intentional regression assets, not disposable debug output.

- [ ] Tray starts with translator stopped.
- [ ] Start translator launches exactly one Bridge.
- [ ] NLLB initializes successfully.
- [ ] EN -> ZH translation works.
- [ ] ZH -> EN translation works.
- [ ] Protocol metadata is not translated as user text.
- [ ] Manual recent-message translation works.
- [ ] `/wi last` works.
- [ ] `/wi list` and the picker work.
- [ ] Automatic incoming translation works.
- [ ] Stop translator releases the Bridge/model process.
- [ ] Closing the overlay returns the tray to Stopped.
- [ ] Overlay cannot settle on top of the active transport.
- [ ] Idle CPU behavior is acceptable.
- [ ] No obvious capture/performance regression exists.
- [ ] Frozen PyInstaller build works.
- [ ] Inno Setup installer builds and installs.
- [ ] Installed addon loads in WoW Classic Era.
- [ ] GitHub Actions release build passes when applicable.

For protocol changes, test different WoW UI scales/resolutions when possible.

## 19. Architecture invariants

### Addon/Bridge compatibility

The encoder and decoder are one protocol. Changes to MAGIC, frame layout, grayscale levels, encoding, checksum, envelopes, or timing must be coordinated.

### Validate before translating

KT08 payload acceptance is language-independent. Geometry comes from physical
pilots, never payload plausibility. Do not send a KT08 payload to NLLB without
mandatory MAGIC/version/flags/length, matching sequence, CRC32 and UTF-8
validation. A positively identified invalid KT08 frame must not fall through to
KT07.

### Do not translate protocol metadata

Record type and author fields are metadata, not user text.

### Preserve explicit lifecycle

The tray can remain running while translation is stopped. Start creates the Bridge; Stop removes it. Closing the overlay also stops it.

### Protect capture and generations

Overlay suppression must be acknowledged before protected capture. Initial and
relocation commits are bound to the exact native generation; stale generations
cannot commit geometry or restore the overlay. Tk visibility and geometry calls
remain UI-thread-only.

### Preserve physical raster geometry

Fractional and anisotropic physical pitches are normal. Do not quantize them to
the addon's integer logical CELL, infer KT08 geometry from payload contents or
replace the independent BR consistency check.

### Keep idle work cheap

Expensive capture/calibration must not become a permanent idle loop.

### Keep post-processing conservative

WoW terminology normalization should remain source-conditioned.

### Test the frozen product

Source execution alone is insufficient for packaging/runtime changes.

### Why KT08 replaced KT07

KT07 used raster-search geometry and an additive 8-bit checksum. Real Windows
testing exposed checksum-colliding corrupted payloads, ambiguous valid-looking
geometries, fractional rasterization, incorrect anchor-to-data pitch
assumptions, overlay occlusion and relocation races. KT08 addresses those
classes with physical pilots, analytical independent X/Y geometry, CRC32,
duplicated sequence markers, double buffering, generation-bound relocation and
ACK-gated overlay suppression. KT07 remains only for compatibility.

## 20. Contribution workflow

Read `CONTRIBUTING.md` before coding.

Typical flow:

```bash
git checkout main
git pull --ff-only
git checkout -b fix/short-description
```

Example commit messages:

```text
fix: improve KT07 anchor reacquisition
fix: preserve tray state when bridge exits
feat: add WoW terminology normalization
perf: reduce idle capture overhead
docs: clarify local development setup
```

A pull request should explain:

- the problem;
- the approach;
- affected architecture/protocol invariants;
- testing performed;
- CPU/capture impact;
- useful logs/screenshots with private information removed.

Avoid unrelated refactors in focused bug/protocol changes.

## 21. Adding an application record type

1. Define semantics and fields.
2. Keep the complete UTF-8 envelope within `MAX_BYTES`.
3. Add addon-side encoding/queueing.
4. Add explicit Bridge parsing.
5. Keep metadata out of translation input.
6. Preserve checksum validation.
7. Test consecutive queued messages.
8. Update this guide.

Prefer explicit record types over ambiguous overloaded payloads.

## 22. Changing translation terminology

Collect a concrete case first:

```text
source -> raw NLLB output -> desired WoW wording
```

Then implement a narrow source-conditioned rule and verify that unrelated text is unaffected.

For Chinese WoW terminology, fluent player review is valuable because game terminology may differ from literal translation.

## 23. Security and privacy

WoWInterpreter uses screen capture to read its visual transport. Diagnostics may therefore contain other visible content.

Contributors should:

- avoid logging unnecessary chat content;
- inspect screenshots before publishing;
- avoid adding network transmission of chat/screen content without explicit design and documentation;
- never commit secrets, signing credentials, tokens, or private keys;
- follow `SECURITY.md` for security-sensitive reports.

Review `THIRD_PARTY_NOTICES.md` for model and third-party licensing considerations.

## 24. Code signing

Code signing and reproducible automated builds are separate concerns.

A future signing solution can be integrated into the release pipeline, but private signing material must never be committed.

Conceptually:

```text
build -> verify -> sign -> package/publish -> checksum final artifact
```

The published checksum must describe the exact final installer users download.

## 25. Documentation responsibilities

Update documentation when behavior changes:

- user behavior/commands -> README and user guides;
- architecture/development -> `Documentation/DEVELOPMENT.md`;
- contribution expectations -> `CONTRIBUTING.md`;
- security process -> `SECURITY.md`;
- dependencies/licenses -> `THIRD_PARTY_NOTICES.md`;
- release-visible changes -> `CHANGELOG.md`.

Keep English and Simplified Chinese user-facing documentation aligned.

## 26. Final review before merge

Run:

```text
git status
git diff --check
```

Review the complete diff for:

- generated files;
- diagnostic screenshots/logs;
- Chinese encoding corruption;
- stale version strings;
- addon/Bridge protocol mismatches;
- debug output exposing chat;
- increased capture/CPU usage;
- packaging changes not tested in a frozen build.

WoWInterpreter crosses Lua, screen pixels, Python, ML runtime, Tkinter, PyInstaller, and Inno Setup. Keeping those boundaries explicit and well tested is more important than making any one component clever.
