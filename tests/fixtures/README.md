# Real transport regression fixtures

These files are preserved real-Windows captures. They exercise rasterization
and occlusion behavior that synthetic renderers cannot fully reproduce.

- `kt07_relocation_failure_6_validation.png`: Windowed KT07 relocation with a
  fractional data pitch that differs from its anchor hint.
- `kt07_initial_ambiguity.png` and `.txt`: stationary Fullscreen KT07 capture
  with multiple structurally valid geometries; calibration must reject the
  ambiguity rather than choose by enumeration order.
- `kt08_initial_failure_1.png/.txt` and `2.png/.txt`: unobstructed KT08 frames
  containing both the RGB/YCM presence colors and the four pilot colors. Joint
  pilot geometry and strict frame validation must select the real rectangle.
- `kt08_initial_failure_3.png/.txt` and `4.png/.txt`: initial Windowed captures
  physically occluded by the overlay. They must remain rejected; integration
  tests ensure protected acquisition waits for overlay suppression instead of
  weakening the decoder.

Do not recompress, crop or otherwise edit fixture pixels. Runtime diagnostics
generated outside this directory are not release assets.
