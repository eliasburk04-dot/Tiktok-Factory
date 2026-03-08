Du bist ein AI Coding Assistant und übernimmst die Weiterentwicklung des Projekts **Tiktok-Factory**. 

**Projekt-Überblick:**
Es handelt sich um eine Headless Python-Pipeline zur automatisierten Erstellung von Reddit-Story-TikToks. Das Projekt generiert aus Reddit-Posts Videos, indiziert Audio (Text-to-Speech), rendert kinetische Untertitel und legt Gameplay (Minecraft Parkour) in den Hintergrund.

**Derzeitiger Stand (V3):**
Wir haben das Projekt kürzlich auf eine "Premium Viral"-Strategie (V3) hochgerüstet:
- **Audio:** Nutzt die **ElevenLabs API** (Voice: `Adam`, Model: `eleven_multilingual_v2`) über den `with-timestamps` Endpoint für 100% perfekte Word-Level-Synchronität. (Der Provider heißt `ElevenLabsTTSProvider` in `src/tictoc_factory/audio/providers.py`).
- **Untertitel:** Nutzen den massiven Font `Montserrat Black` bei 56px, zentriert (`y=0.50`), strikt 3 Wörter pro Zeile, mit einer starken Bounce-Animation (`0.18`).
- **Gameplay:** Subway Surfers wurde komplett verbannt. Es wird ausschließlich 4K Minecraft Parkour Gameplay verwendet.

**Infrastruktur & Umgebung:**
- **Lokaler Code:** Liegt auf dem Mac unter `/Users/eliasburk/Developer/Tiktok-Factory`.
- **Produktion (Raspberry Pi):** Der Code wird auf einem Raspberry Pi ausgeführt. Du **MUSST** dich regelmäßig per SSH auf den Pi verbinden, um Code zu deployen, Configs anzupassen oder FFMPEG-Jobs (`regenerate`) zu triggern.
  - SSH-Befehl: `ssh milkathedog@100.69.69.19`
  - Verzeichnis auf dem Pi: `/opt/tictoc-factory/`
  - Konfigurationen auf dem Pi: `/opt/tictoc-factory/configs/` (Achtung auf `factory.local.yaml` Overrides!)
  - Input-Medien auf dem Pi: `/opt/tictoc-factory/data/input/` (Longform unter `gameplay_longform/`, Clips unter `gameplay/`)
  - Output auf dem Pi: `/opt/tictoc-factory/data/output/videos/`

---

**Deine nächsten Kernaufgaben (V4 Update):**

Bitte setze folgende Anforderungen sowohl lokal im Code als auch direkt auf dem Raspberry Pi um:

1. **Bugfix: Video friert nach 6 Sekunden ein**
   Das aktuell generierte Video friert nach ca. 6 Sekunden visuell ein (Audio/Text laufen weiter). Untersuche den FFMPEG-Filter-Complex in `src/tictoc_factory/media/composer.py`. Höchstwahrscheinlich ist die Dauer des Gameplay-Clips zu kurz geschnitten worden, der `loop`-Parameter greift nicht korrekt, oder der `zoompan`-Filter stoppt. Finde und löse die Ursache.

2. **Content: Echte 1:1 Reddit Stories (Kein KI-Gequatsche)**
   Aktuell werden die Reddit-Stories von der KI (OpenAI) umgeschrieben und ergeben teilweise keinen Sinn mehr. Ändere die Pipeline so ab, dass **nur nach echten, hochwertigen Stories gesucht wird** (Score > 1500) und diese **1:1, Wort für Wort, ohne jegliche Veränderung** durch den TTS-Provider gesprochen werden. Die Geschichten müssen authentisch bleiben. Passe dazu den `script_builder` oder die `llm`-Modelle entsprechend an, sodass der Originaltext weitergereicht wird.

3. **Gameplay: Minecraft drastisch beschleunigen**
   Das Minecraft-Gameplay fühlt sich im Hintergrund viel zu langsam / zäh an (wie Zeitlupe). Wir haben bereits versucht, es mit `setpts=0.85*PTS` in FFMPEG zu beschleunigen, aber das reicht nicht aus oder wirkt unnatürlich.
   **Deine Aufgabe:** Das rohe, 2-stündige Minecraft-Video liegt unter `/opt/tictoc-factory/data/input/gameplay_longform/`. Falls das Problem an den bereits geschnittenen Clips in `/opt/tictoc-factory/data/input/gameplay/` liegt, **lösche alle alten Clips** und schreibe das Clip-Mining-Skript so um, dass die neuen Clips beim Herausschneiden massiv beschleunigt werden (z. B. 1.5x oder 2x Speed), bevor sie im Composer verwendet werden.

4. **Masterplan: Factory Aufwertung**
   Erstelle abschließend einen Masterplan. Mache Vorschläge, wie wir die Factory qualitativ noch weiter aufwerten können (z.B. AI-generierte Hintergrundbilder für Story-Abschnitte, Sound-Effects (Swooshes/Pops) bei starken Hook-Wörtern, bessere Reddit-Card Animationen).

Bitte denke daran, nach Änderungen am Code diesen via `scp` auf den Pi zu schieben und die Queue auf dem Pi zu flushen (`rm -rf /opt/tictoc-factory/data/queue/jobs/*`), bevor du den `regenerate`-Befehl via SSH feuerst.

Starte jetzt mit der Analyse des 6-Sekunden-Freezes und des Gameplay-Speeds in `composer.py` und `clip_miner.py`.
