# MicroMeasure

A lightweight image measurement tool (DinoCapture / Measuro style) for measuring
on PNGs and other images — no microscope/camera required. Built for repeated,
consistent readings (e.g. Gauge R&R studies).

## Guided teeth lockdown mode (`--lockdown`)

Run `uv run python main.py --lockdown` for a **locked workflow for measuring
teeth across frames** (without the flag it runs the normal free-tool app):

- **Origins are pre-set.** Do an origin pass first (normal mode: set the origin
  on each frame, which auto-saves to the folder). Lockdown then **auto-loads the
  origins** on open (and errors if none are found) — the operator never sets origin.
- The schedule **repeats every 10 frames**: 6 teeth per block, each visible across
  a 5-frame window. The painted numbers (1–6) repeat each block; the **CSV records
  the real global tooth** (block×6 + painted), e.g. frames 11–20 → teeth 7–12.
- On each frame, pick the **Tooth** (only the present painted ones are offered;
  the dropdown shows `painted → #real`), then draw in fixed order:
  **line 1 → line 2 → height point**. A big red **Undo** steps back within the
  current tooth. **Next is blocked until every tooth on the frame is done.**
- Each tooth produces 4 CSV rows (line1∠origin, line2∠origin, line1∠line2,
  height), all carrying the **`Tooth`** column for per-tooth Gauge R&R.

## Run

```bash
uv sync                 # first time only
uv run python main.py
```

## Features

- **Open Folder** → step through every image with the bottom arrows or
  PageUp/PageDown. The **origin carries** to the next image (just reposition it);
  each image remembers its own drawings, so going back restores them. Readings
  accumulate across all images into one CSV (with an `Image` column, and the
  Part field auto-filled with the filename).
- **Drawing backup** — every drawing auto-saves to `micromeasure_session.json`
  inside the folder. Reopen that folder later and the app offers to redraw
  everything, so you can visually QC what an operator measured.
- **Tool visibility** — show/hide tools via the `[tools]` table in `config.toml`.
- **Open** a single PNG/JPG/BMP/TIFF; zoom with the mouse wheel, pan with the Pan tool.
- **Cursor magnifier** — a zoomed loupe follows the cursor in any measure tool so
  you can place points precisely.
- **Set Scale** — enter mm-per-pixel (e.g. `0.006367`); distances then read in mm.
- **Distance** — click two points; length shows live as you move, pinned to the line.
- **Angle (4 pt)** — click 4 points (two lines); the angle between them is drawn
  with an arc + label in the image.
- **Set Origin** — click two points to lock a reference line.
- **Angle vs Origin** — click a line; its signed angle relative to the origin is shown.
- **Readings panel** — every measurement is logged with Part / Operator / Trial
  (Trial auto-increments) and can be **exported to CSV** for Minitab.

## Tips

- Press **Esc** to cancel a measurement in progress.
- Draw lines in a consistent direction for stable angle signs across a study.

## Layout

```
main.py                         thin entry point
src/micromeasure/
  config/settings.py            frozen AppConfig + TOML loader
  services/geometry.py          pure geometry (angles, distances, intersections)
  services/measurements.py      Measurement data model
  services/export.py            CSV export
  ui/canvas.py                  interactive QGraphicsView (tools, preview)
  ui/items.py                   graphics item builders (lines, arcs, labels)
  ui/magnifier.py               cursor loupe widget
  ui/main_window.py             toolbar, readings panel, dialogs
```
