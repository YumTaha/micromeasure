# MicroMeasure

Precision image measurement tool for quality and inspection work — measure distances, angles, and origin-relative angles directly on images, then export results to CSV for Minitab or other analysis tools.

## Download

Grab the latest `MicroMeasure.exe` from the [Releases](../../releases/latest) page — no installation needed, just run it.

## Features

- **Distance** — click two points; live preview with label pinned to the line.
- **Angle (4 pt)** — click two lines (4 points); draws the angle arc with a label.
- **Set Origin** — lock a reference line that persists across all images in a folder.
- **Angle vs Origin** — signed angle of any line relative to the origin (±45°).
- **Set Scale** — enter mm-per-pixel to read distances in mm instead of pixels.
- **Cursor magnifier** — a zoomed loupe follows the cursor for precise point placement.
- **Folder mode** — step through every image with arrows or PageUp/PageDown. The origin carries across images; each image remembers its own drawings.
- **Session backup** — drawings auto-save to `micromeasure_session.json` in the folder. Reopen later to redraw and visually QC previous measurements.
- **Readings panel** — logs every measurement with Part / Operator / Trial; **Export CSV** sends them to a file ready for Minitab.

## Usage

1. Run `MicroMeasure.exe`.
2. Click **Open** to load a single image, or **Open Folder** to load a full set.
3. Click **Set Scale** and enter your mm-per-pixel value (e.g. `0.006367`).
4. Pick a tool from the toolbar, place your points, and read the result.
5. Fill in Part / Operator fields in the Readings panel, then **Export CSV** when done.

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| Esc | Cancel current measurement |
| PageUp / PageDown | Next / previous image (folder mode) |
| Arrow keys | Nudge last-placed point |

## Configuration

Settings are stored in `config.toml` next to the executable (created on first run). You can show or hide individual tools under the `[tools]` section.

## Running from source

```bash
uv sync
uv run python main.py
```

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).
