# MicroMeasure

A lightweight image measurement tool (DinoCapture / Measuro style) for measuring
on PNGs and other images — no microscope/camera required. Built for repeated,
consistent readings (e.g. Gauge R&R studies).

## Run

```bash
uv sync                 # first time only
uv run python main.py
```

## Features

- **Open** any PNG/JPG/BMP/TIFF; zoom with the mouse wheel, pan with the Pan tool.
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
