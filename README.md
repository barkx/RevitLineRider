# Revit Line Rider (pyRevit)

Sled down your own Revit lines. Every detail line and model line in the active
2D view becomes track, and a little sled rider is drawn live in the view with
DirectContext3D. Nothing is added to the model while you ride.

**Requirements:** Revit 2022 or newer (built for 2025+ on .NET 8) with pyRevit
(IronPython 2.7 or 3.4).

## Install

Clone or download this repository, then copy `RevitLineRider.extension` into a
pyRevit extensions folder (or add the repository folder under pyRevit > Settings >
Custom Extension Directories) and click **Reload**. A new **LineRider** tab appears.

```
git clone https://github.com/barkx/RevitLineRider.git
```

## Quick start

1. Open a section, elevation, plan or drafting view.
2. Click **Demo Track** (draws a ready-made course) or draw your own detail lines.
3. Click **Ride**, then press **Space**.

## Buttons

| Button | What it does |
|---|---|
| **Ride** | Starts the game in the active view and opens the HUD. |
| **Set Start** | Click where the sled starts in this view (clicking right on a line puts the sled on top of it). Shift+Click forgets it (the sled then drops onto the highest line). |
| **Demo Track** | Draws a long test course (start slope, gap jump, booster, rollers, climb, tabletop, waves, big drop, second booster, rollers, long climb to the FINISH summit) with labels, sets its start point and opens the game zoomed in on the rider. It offers to delete older Line Rider lines in the view, is placed next to any other lines, and clicking it again replaces the previous demo. Undo removes it. Turns off the view's crop region. |
| **Line Styles** | Creates the four LR line styles. With lines selected, applies one of them. |
| **Flip Lines** | Reverses the drawing direction of the selected lines (boost direction / one-way side). |

## Line types

The line style name decides how a line behaves. Any other style is normal track.

| Style | Behaviour |
|---|---|
| `LR Track` (blue) | Solid from both sides. |
| `LR Accel` (red) | Solid, and boosts the sled in the line's drawing direction. Red chevrons show the direction. |
| `LR One-way` (purple) | Solid only from one side: draw it left-to-right and you ride on top. Ticks show the solid side; the rider passes through from the other side. |
| `LR Scenery` (green) | Drawn, never touched. Styles containing "Invisible" are ignored too. |

Names are matched loosely ("accel", "boost", "one-way", "scenery"), so you can make your own styles.

## HUD controls

Click the HUD once so it has the keyboard.

| Key | Action |
|---|---|
| Space | Play / pause |
| R | Back to the flag (or the start). Shift+R always goes to the start. |
| F | Place a flag at the current moment. Shift+F removes it. |
| ← / → | Rewind / step one frame (Shift = 4 frames) |
| 1 – 4 | Playback speed 0.25× / 0.5× / 1× / 2× |
| C | Follow camera on/off |
| S | Pick a new start point |
| Esc | Pause |

Also in the HUD: **Ride left**, **Rider size** (×0.25 … ×8) and **Reload track from view**
(after you edit lines). Close the HUD with ✕ to remove the rider from the view.

## How it works

* **Physics** (`lib/linerider/physics.py`, pure Python) follows the classic Line Rider
  model: 10 Verlet points (sled + rider), 6 constraint iterations per frame,
  40 frames per second, gravity 0.175 units/frame². Mount joints break when
  overstretched or when the sled flips: the rider crashes off the sled.
  Lines are two-sided by default (Revit users don't care about drawing direction);
  one-way and accelerator lines use the drawing direction.
* **Demo course:** `lib/linerider/demo.py` (about 6100 rider units + a long finish summit, ~20 s to the finish at 1x). Checked in simulation: 130 runs with the start nudged by up to ±4 units all reach the summit without crashing.
* **Camera:** with Follow camera on, Ride / Reset / Play zoom the view so about 360 rider units are visible, then the view pans to keep the rider in the middle.
* **Scale:** at ×1 the sled is 12 mm long on paper, so it scales with the view scale
  (1.2 m at 1:100). The km/h readout uses that real-world size.
* **Rendering:** a DirectContext3D server registered for the one view; it draws filled
  triangles for the rider and markers (start flag, flag, accelerator chevrons,
  one-way ticks) just behind the cut plane.
* **Loop:** a WPF DispatcherTimer raises an ExternalEvent; each tick steps the physics
  on a fixed 40 Hz clock, updates the geometry, pans the view (`ZoomAndCenterRectangle`)
  and calls `RefreshActiveView`.
* **Updates:** every button calls `linerider.fresh()` first, so after you copy new extension files the next click runs the new code (pyRevit's persistent engine would otherwise keep the old modules).
* **Settings & log:** `%APPDATA%\RevitLineRider\settings.json` (start points per view,
  HUD position, preferences) and `linerider.log`.

## Known limits

* 2D views only (no 3D views). Lines hidden by the view (crop, filters, hidden
  categories) are not track.
* In sections the rider is drawn just behind the cut plane, so cut model elements
  can hide it.
* The frame rate depends on how fast Revit redraws the view.
* Loops are hard: with one-way lines you can build them, but the rider must never
  meet a line from its solid side on the way out.

## Files

```
RevitLineRider.extension/
  LineRider.tab/Ride.panel/      Ride, Set Start
  LineRider.tab/Track.panel/     Demo Track, Line Styles, Flip Lines
  lib/linerider/physics.py       rider + line physics (pure Python)
  lib/linerider/demo.py          demo course (validated in simulation)
  lib/linerider/revitio.py       view frame, reading lines, styles, demo drawing, picking
  lib/linerider/render.py        DirectContext3D server
  lib/linerider/game.py          HUD, game loop, camera
  lib/linerider/settings.py      settings + log
```
