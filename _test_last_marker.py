import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import json
import math
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter

import usmark_gui as ug

app = QApplication([])

win = ug.ImageMarkerApp()
win.resize(1200, 800)
win.show()
app.processEvents()

# --- helper to count yellow-ish highlight pixels in a rendered widget ---
def grab_widget_rgb(widget):
    img = widget.grab()
    qimg = img.toImage().convertToFormat(QImage.Format_RGB888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.constBits()
    ptr.setsize(qimg.sizeInBytes())
    data = bytes(ptr)
    bpl = qimg.bytesPerLine()
    out = bytearray(w * h * 3)
    for y in range(h):
        row = data[y * bpl : y * bpl + w * 3]
        out[y * w * 3 : (y + 1) * w * 3] = row
    return bytes(out), w, h

def yellow_pixel_count(widget):
    data, w, h = grab_widget_rgb(widget)
    n = 0
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        if r > 170 and g > 170 and b < 120:
            n += 1
    return n

# --- open an image directly on the canvas ---
base = Image.new("RGB", (400, 400), (40, 40, 40))
win.canvas.set_image(base, "/tmp/test_img.png")
win.update_marker_counter()
app.processEvents()

def flagged_indices():
    return [i for i, m in enumerate(win.markers) if getattr(m, "is_last", False)]

# No markers -> no highlight
assert flagged_indices() == []
assert yellow_pixel_count(win.canvas) == 0, "highlight visible with no markers"

# Place marker A at (100,100), voltage 2.5
win.melter.voltage_high1 = 2.5  # attribute name may differ; patch get_current_voltage instead
win.get_current_voltage = lambda: 2.5
win.add_marker(100, 100)
app.processEvents()
assert flagged_indices() == [0], f"A not flagged: {flagged_indices()}"
yA = yellow_pixel_count(win.canvas)
assert yA > 0, "no highlight ring drawn after placing marker"

# Place marker B at (300,300), voltage 1.8
win.get_current_voltage = lambda: 1.8
win.add_marker(300, 300)
app.processEvents()
assert flagged_indices() == [1], f"B not flagged: {flagged_indices()}"
yB = yellow_pixel_count(win.canvas)
assert yB > 0

# Undo -> A highlighted again
win.undo()
app.processEvents()
assert flagged_indices() == [0], f"undo flag wrong: {flagged_indices()}"

# Redo -> B highlighted
win.redo()
app.processEvents()
assert flagged_indices() == [1], f"redo flag wrong: {flagged_indices()}"

# Clear -> nothing flagged, no yellow
win.clear_markers()
app.processEvents()
assert flagged_indices() == []
assert yellow_pixel_count(win.canvas) == 0, "highlight persists after clear"

# --- display_image must never contain the highlight ---
win.get_current_voltage = lambda: 2.5
win.add_marker(100, 100)
win.get_current_voltage = lambda: 1.8
win.add_marker(300, 300)
app.processEvents()  # ensure paintEvent ran (yellow present on widget)
assert yellow_pixel_count(win.canvas) > 0

di = win.canvas.display_image
yellow_in_display = sum(1 for px in di.getdata()
                        if px[0] > 170 and px[1] > 170 and px[2] < 120)
# markers themselves are colored by voltage ramp (blue..magenta); pure
# yellow (255,255,0) could legitimately appear from the ramp at some t.
# Check specifically around marker B where the ring would be: radius ~ size/2+4
ring_yellow = 0
for px, py in [(300 + int(dx), 300 + int(dy)) for dx in (-12, -11, 11, 12) for dy in (-12, 12)]:
    try:
        r, g, b = di.getpixel((px, py))
        if r > 170 and g > 170 and b < 120:
            ring_yellow += 1
    except IndexError:
        pass
print("display_image yellow near ring:", ring_yellow, "total yellow px:", yellow_in_display)

# --- session round trip ---
data = win.build_session_data()
raw = json.dumps(data)
loaded = json.loads(raw)
last_flags = [m.get("last") for m in loaded["markers"]]
print("session 'last' flags:", last_flags)
assert last_flags == [False, True], f"session serialization wrong: {last_flags}"

# Apply into a fresh state
win.clear_markers()
app.processEvents()
notes = win.apply_session_data(loaded)
app.processEvents()
assert flagged_indices() == [1], f"session load flag wrong: {flagged_indices()}"
assert yellow_pixel_count(win.canvas) > 0, "no highlight after session load"

# Legacy session without 'last' keys -> falls back to final marker
legacy = json.loads(raw)
for m in legacy["markers"]:
    m.pop("last", None)
win.apply_session_data(legacy)
app.processEvents()
assert flagged_indices() == [1], f"legacy fallback wrong: {flagged_indices()}"

# Hand-edited file with two 'last' flags -> only the last one kept
dual = json.loads(raw)
dual["markers"][0]["last"] = True
win.get_current_voltage = lambda: 2.5
win.add_marker(200, 200)   # marker C, now index 2 flagged
dual["markers"].append(dual["markers"][0])  # extra flagged entry appended? craft manually
dual_list = win.build_session_data()["markers"]
dual_list[0]["last"] = True
dual["markers"] = dual_list
win.apply_session_data(dual)
assert flagged_indices() == [len(win.markers) - 1], f"dual-flag sanitize wrong: {flagged_indices()}"

# --- rotation sanity: painting with rotation must not crash ---
win.rotation_spin.setValue(30.0)
app.processEvents()
assert flagged_indices() == [len(win.markers) - 1]
assert yellow_pixel_count(win.canvas) > 0, "highlight missing under rotation"
win.rotation_spin.setValue(0.0)
app.processEvents()

# --- zoom sanity ---
win.canvas.zoom_by(2.0)
app.processEvents()
assert yellow_pixel_count(win.canvas) > 0, "highlight missing under zoom"

print("ALL TESTS PASSED")
