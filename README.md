# usmelt_mark

`usmelt_mark` is a GUI application for **time-resolved cryo-EM experiments** using the
melt-and-revitrify approach. It lets you open an atlas of a cryo-EM
specimen, mark positions of interest directly on it, and fire voltage pulses to a laser
trigger via a connected function generator — all from a single window.

This project is forked from
[Filipe Maia's `usmelt`](https://github.com/FilipeMaia/usmelt), which provides the
underlying hardware control for the sheet-jet sample delivery system described in:

> Assalauova et al. (2024). *An improved method for sample delivery using the
> sheet-jet technique at X-ray free-electron lasers.*
> IUCrJ **10**, https://doi.org/10.1107/S2052252523007972

---

## Scripts

| Script | Purpose |
|---|---|
| `usmark_gui.py` | Full application — marker tool + pulse-generator control |
| `mark_only.py` | Offline-only marker tool optimised for rapid grid-hole marking |

---

## `usmark_gui.py` — full application

### Image marker panel

- Open any image of a cryo-EM grid (TEM or CLEM atlas, photograph of the grid, etc.)
- **Left-click** to place a marker; each marker records its position and the pulse
  voltage set at the time of placement
- **Right-click** to place a marker *and* fire the pulse simultaneously
- Markers are colour-coded by voltage (blue → cyan → green → yellow → orange → magenta)
  and can be assigned one of six shapes — **circle, triangle, square, star, diamond,
  hexagon** — each with a custom text label, useful for distinguishing experimental
  parameters
- Laser alignment tests (fired at 5 V) are detected automatically and displayed
  differently from experiment-relevant exposures; a counter above the marker panel shows
  only real (non-test) placements
- **Guide mesh** — calibrate an orthogonal grid over the image by clicking three reference
  points in a single line; the grid snaps subsequent marker placements to the nearest node
  so every exposed location can be covered systematically
- The image can be rotated, zoomed and panned
- Export the annotated image as PNG/JPEG with all markers and an overlaid legend/colour bar

### USMELT hardware panel

- Connects to a **TG5012A function generator** (Aim-TTi) over USB-serial to
  trigger a Cobolt 06-01 DPL laser in current-modulation mode
- Supports a standard rectangular pulse (voltage + duration, per channel) or a shaped
  two-stage waveform (V1 for T1 µs, then V2 for T2 µs) uploaded as an arbitrary waveform
- Shaped pulse parameters are previewed as a live waveform plot
- Run with `--offline` to use the marker tool without any connected hardware

### Session management

- Sessions are saved as human-readable JSON (`.usmark.json`) and store all marker
  positions, voltages, shapes, labels, and image rotation — enough to resume exactly
  where you left off
- An autosave file is written after every marker placement so a crash loses at most one action
- On startup, the application offers to restore the most recent autosave

---

## `mark_only.py` — offline marker tool for rapid hole marking

`mark_only.py` is a specialised copy of the full application intended for workflows
where you open an image and need to mark every area according to, for
example, ice quality — without any connected hardware.

Key differences from `usmark_gui.py`:

- **Always offline** — no pulse generator is needed and no connection is attempted
- **Click-and-drag sweep** — hold the left mouse button and drag across the image; a
  marker is placed at every guide node the cursor passes over, making it fast to cover
  an entire grid square in one stroke
- **No duplicate node markers** — when the guide mesh is applied, the same guide node
  can only hold one marker; sweeping over an already-marked node is silently ignored
- **Right-click removes** — right-clicking removes the nearest marker (snapped to the
  guide node when the guide is applied); use Undo (Ctrl+Z) to recover an accidental
  removal
- **JSON compatibility** — the session file format is identical to `usmark_gui.py`, so
  sessions started in one script can be opened in the other

---

## Installation

```bash
pip install .
```

Requires Python 3.10+. Dependencies (PySide6, Pillow, pyserial) are declared in
`pyproject.toml` and installed automatically.

---

## Usage

```bash
# Full application — connects to the pulse generator on startup
python usmark_gui.py

# Full application — marker tool only, no hardware required
python usmark_gui.py --offline

# Offline marker tool for rapid hole marking (always offline)
python mark_only.py
```

### Basic workflow — `usmark_gui.py`

1. **Open an image** — File → Open Image (or drag-and-drop).
2. **Configure pulse parameters** in the USMELT panel (voltage, pulse length, delay).
3. **Left-click** to place a marker without firing; **right-click** to place a marker
   *and* fire the pulse.
4. Optionally **calibrate the guide mesh** to snap placements to a regular grid.
5. Use **Undo/Redo** (Ctrl+Z / Ctrl+Y) to correct mistakes.
6. **Save the session** (File → Save Session) to resume later.
7. **Export** the annotated image (File → Export Image) to share or archive.

### Basic workflow — `mark_only.py`

1. **Open a grid-square image** — File → Open Image.
2. **Calibrate the guide mesh** by clicking three reference areas; the grid snaps to the
   pattern automatically.
3. **Click and drag** to sweep markers across holes, or click individual holes.
4. **Right-click** a marked hole to remove its marker.
5. **Save the session** (File → Save Session); the file is compatible with
   `usmark_gui.py`.

### Duplicate COM ports on Windows

Windows sometimes assigns two devices to the same COM port, making communication
impossible. To fix this:

1. Open Device Manager (right-click Start → Device Manager).
2. Expand **Ports (COM & LPT)**.
3. Right-click the affected device → Properties → Port Settings → Advanced.
4. Assign a free COM port number and click OK.
