# Third-party notices

WoWInterpreter uses third-party software and a separately licensed translation model. This file is informational and does not replace the original license texts.

## NLLB-200 distilled 600M

- Project/model: `facebook/nllb-200-distilled-600M`
- Used for: English ↔ Simplified Chinese machine translation
- Obtained at runtime through Hugging Face Transformers
- License reported by the model publisher: **CC BY-NC 4.0**
- The model card describes NLLB-200 as a research model and states that it is not released for production deployment.

The model is not relicensed under WoWInterpreter's MIT License. Review the model's current license and model card before commercial use, redistribution, or other use where its terms matter.

Model page: https://huggingface.co/facebook/nllb-200-distilled-600M

## Python/runtime dependencies

The Windows build uses third-party packages including PyTorch, Transformers, Pillow, pyperclip, sentencepiece, sacremoses and pystray. Each dependency remains subject to its own license and notices.

The release build intentionally preserves runtime package metadata needed by Transformers while pruning some non-runtime development trees to keep the Windows installer practical.

## Inno Setup language file

The project bundles a Simplified Chinese Inno Setup language file for the bilingual installer. That file retains the terms/notices applicable to its upstream source.

## Trademarks

World of Warcraft, Blizzard Entertainment, Meta, Hugging Face, and other names/marks belong to their respective owners. Their appearance here is descriptive and does not imply affiliation or endorsement.
