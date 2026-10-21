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

## What it does

The application has two integrated panels:

**Image marker panel**
- Open any image of a cryo-EM grid (TEM or CLEM atlas, photograph of the grid, etc.)
- Click to place markers at positions you want to expose; each marker records its
  position and the pulse voltage used at the time of placement
- Markers are color-coded by voltage (blue → cyan → green → yellow → orange → magenta)
  and can be assigned different shapes with custom labels — useful for distinguishing additional experimental parameters
- Laser alignment testing, done at 5 V, is automatically detected and handled differently from experiment-relevant exposures
- The image can be rotated, zoomed and panned; a counter in the toolbar shows how many
  real (non-test) markers have been placed
- Export the annotated image as PNG/JPEG with all markers and an overlaid legend/color bar

**USMELT hardware panel**
- Connects to a **TG5012A function generator** (Aim-TTi) over USB-serial to
  trigger a Cobolt 06-01 DPL laser in current-modulation mode
- Supports a standard rectangular pulse (voltage + duration, per channel) or a shaped
  two-stage waveform (V1 for T1 µs, then V2 for T2 µs) uploaded as an arbitrary waveform
- Right-clicking on the image places a marker *and* fires the pulse simultaneously
- Shaped pulse parameters are previewed as a live waveform plot
- Run with `--offline` to use the marker tool without any connected hardware

**Session management**
- Sessions are saved as human-readable JSON (`.usmark.json`) and store all marker
  positions, voltages, shapes, labels, and image rotation — enough to resume exactly
  where you left off
- An autosave file is written after every marker placement so a crash loses at most one action
- On startup, the application offers to restore the most recent autosave

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
# Normal mode — connects to the pulse generator on startup
python usmark_gui.py

# Offline mode — marker tool only, no hardware required
python usmark_gui.py --offline
```

### Basic workflow

1. **Open an image** — File → Open Image (or drag-and-drop).
2. **Configure pulse parameters** in the USMELT panel (voltage, pulse length, delay).
3. **Left-click** to place a marker without firing; **right-click** to place a marker
   *and* fire the pulse.
4. Use **Undo/Redo** (Ctrl+Z / Ctrl+Y) to correct mistakes.
5. **Save the session** (File → Save Session) to resume later.
6. **Export** the annotated image (File → Export Image) to share or archive.

### Duplicate COM ports on Windows

Windows sometimes assigns two devices to the same COM port, making communication
impossible. To fix this:

1. Open Device Manager (right-click Start → Device Manager).
2. Expand **Ports (COM & LPT)**.
3. Right-click the affected device → Properties → Port Settings → Advanced.
4. Assign a free COM port number and click OK.
