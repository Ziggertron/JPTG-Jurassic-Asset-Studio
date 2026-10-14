# Jurassic Asset Studio

<img width="1917" height="1018" alt="Screenshot 2026-10-14 051042" src="https://github.com/user-attachments/assets/a257d817-6229-42a6-b833-3196ec7dfd6b" />


A Windows asset browser and 3D model viewer for **Jurassic Park: The Game** by Telltale Games. Browse the installed game archives, preview models and skeletal animations, and export assets for use in other tools.

## Getting started

1. Extract the Windows release ZIP into a writable folder.
2. Run **Jurassic Asset Studio.exe**. The packaged application does not require Python. Microsoft Edge WebView2 Runtime is required.
3. Let the asset library finish loading. Use **Open game folder** if the game is installed elsewhere.

The default game data location is:

```text
C:\Program Files (x86)\Telltale Games\Jurassic Park The Game\GameData
```

The application reads the installed archives and stores an extracted-asset cache beside the executable. It does not modify the game files.

## Features

- Search assets and filter by category or episode.
- Orbit, zoom, pan and frame 3D models; display wireframes and skeletons.
- Play skeletal animations on the visible mesh, with pause, scrubbing and playback speed controls.
- Select individual animation clips or every matching clip for model export.
- Preview textures and listen to music, sound effects and dialogue.
- Export individual assets or selected assets in a ZIP.
- Game-inspired menu styling, Jurassic Park logo and large Jurassic Park font headings.

## Export formats

| Asset | Formats |
| --- | --- |
| Models | GLB, glTF + BIN in a ZIP, static OBJ, original file |
| Textures | PNG, DDS, JPEG, BMP, TGA, original D3DTX |
| Music, sounds and dialogue | Native playable audio, WAV, MP3, OGG, original file |
| Skeletons | JSON, original SKL |
| Animations and other assets | Original file, asset metadata JSON |

GLB and glTF exports include the model's rig, textures and selected skeletal animation clips. OBJ exports contain static positions and faces only.

Audio conversion requires FFmpeg or the `imageio-ffmpeg` Python package when running from source. Native audio export does not require conversion.

## Export a model with animations

1. Select a model in the asset library.
2. Check the desired clips, or use **Select all clips**. This also selects clips hidden by the clip filter.
3. Click **Preview selected clips** to load them into the viewer.
4. Use **Playing animation** to switch between selected clips.
5. Choose **GLB** or **glTF**, click **Export asset**, and choose a save location.

Matching animation names from all episodes are listed once per name. To export animation clips with a model, use the individual model export workflow above; the selected-assets ZIP workflow does not attach selected animation clips to models.

## Running from source

The application uses Python 3.10 or later, pywebview and a local Three.js viewport. On Windows, extract the source ZIP and open a terminal in its folder. Create a virtual environment and install the required Python packages:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

From the directory containing `desktop.py`, run:

```powershell
.\.venv\Scripts\python.exe desktop.py
```

Keep the `vendor`, `web` and `licenses` folders with the source files.

## Compatibility

- Supports the installed Windows game archives across all four episodes and available languages. Duplicate assets across archives are expected.
- Texture decoding covers DXT1, DXT3, DXT5 and RGBA8.
- Animation export preserves supported skeletal transform tracks. Scene choreography, camera tracks, lip-sync phonemes and other non-skeletal properties are not exported as bone animation.
- Unsupported encodings produce a preview or export error. Original-file export remains available.
- Music and sound categories are inferred from filenames; check **All** if an asset is not in its expected category.
- Batch ZIP exports include an `export-report.json` listing failures.

## Credits

See [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt) and the `licenses` folder for bundled library and font credits. This is an unofficial tool. Jurassic Park and the game assets belong to their respective rights holders; a game installation is required to browse its models and audio.
