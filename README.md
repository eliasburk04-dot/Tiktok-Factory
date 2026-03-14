# Tictoc Factory

Headless TikTok content factory intended for unattended deployment on Raspberry Pi.

Key commands:

- `tictoc-factory cycle`
- `tictoc-factory regenerate`
- `tictoc-factory publish-due`
- `tictoc-factory preview-subtitles --output-path artifacts/subtitle-preview.mp4`

Subtitle styling for Reddit-story videos lives in the `subtitles:` section of [`configs/factory.local.yaml`](/Users/eliasburk/Developer/Tiktok-Factory/configs/factory.local.yaml) and [`configs/factory.example.yaml`](/Users/eliasburk/Developer/Tiktok-Factory/configs/factory.example.yaml). The premium preset now uses short caption groups, a centered safe-area backdrop, strong outline/shadow treatment, and a highlighted active-word plate.

Word-level highlighting works by taking TTS/transcription word timestamps, regrouping them into punchy caption windows in [`layout.py`](/Users/eliasburk/Developer/Tiktok-Factory/src/tictoc_factory/subtitles/layout.py), writing those groups into the kinetic subtitle manifest in [`generator.py`](/Users/eliasburk/Developer/Tiktok-Factory/src/tictoc_factory/subtitles/generator.py), and rendering the currently spoken word with a scaled yellow highlight in [`composer.py`](/Users/eliasburk/Developer/Tiktok-Factory/src/tictoc_factory/media/composer.py).

For a quick visual check without a full pipeline run, render a short preview clip with:

```bash
tictoc-factory preview-subtitles --output-path artifacts/subtitle-preview.mp4
```

Current limitation: truly top-tier subtitle sync still depends on the quality of upstream word timestamps from the active TTS/transcription provider and the locally available bold font file.
