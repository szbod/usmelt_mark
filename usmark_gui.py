import sys
import math
import copy
import argparse
import configparser
from pathlib import Path

# Offline mode: set from the command line (-o / --offline).
# When True, the application never attempts to discover or open
# a connection to the external pulse generator.  Defaults to False
# so importing this module keeps the original behavior.
OFFLINE_MODE = False

try:
    import winsound
except ImportError:  # non-Windows platforms (e.g. offline testing)
    winsound = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # allow headless testing of the pure-Python parts
    Image = ImageDraw = ImageFont = None

from PySide6.QtCore import Qt, QRectF, QPoint, QPointF, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

# ----------------------------------------------------------------------
# USMELT / TG5012A
# ----------------------------------------------------------------------

import usmelt


# ----------------------------------------------------------------------
# Marker data
# ----------------------------------------------------------------------

MARKER_SHAPES = ("circle", "triangle", "square", "star")


def draw_marker_shape(draw, shape, cx, cy, size, fill, outline=(0, 0, 0),
                      width=None):
    """Draw a marker of the given shape centered at (cx, cy).

    All shapes fit inside a circle of diameter ``size`` so they look
    visually balanced next to each other.  Coloring is identical for
    every shape - only the geometry changes.
    """
    if width is None:
        width = max(1, int(size / 8))

    r = size / 2.0
    bbox = [cx - r, cy - r, cx + r, cy + r]

    if shape == "circle":
        draw.ellipse(bbox, fill=fill, outline=outline, width=width)
        return

    if shape == "square":
        # Square inscribed in the same circle as the other shapes.
        half = r / math.sqrt(2.0)
        draw.polygon(
            [
                (cx - half, cy - half),
                (cx + half, cy - half),
                (cx + half, cy + half),
                (cx - half, cy + half),
            ],
            fill=fill,
            outline=outline,
            width=width,
        )
        return

    if shape == "triangle":
        # Equilateral triangle pointing up, vertices on the circle.
        pts = []
        for k in range(3):
            ang = math.radians(-90.0 + k * 120.0)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        draw.polygon(pts, fill=fill, outline=outline, width=width)
        return

    if shape == "star":
        # Classic five-point star alternating outer/inner radii.
        inner = r * 0.45
        pts = []
        for k in range(10):
            ang = math.radians(-90.0 + k * 36.0)
            rad = r if k % 2 == 0 else inner
            pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        draw.polygon(pts, fill=fill, outline=outline, width=width)
        return

    # Unknown shape: fall back to a circle.
    draw.ellipse(bbox, fill=fill, outline=outline, width=width)


class Marker:
    def __init__(self, x, y, size=15, voltage=0.0, is_test=False,
                 shape="circle"):
        self.x = float(x)
        self.y = float(y)
        self.size = int(size)
        self.voltage = float(voltage)
        self.is_test = bool(is_test)
        self.shape = str(shape) if shape in MARKER_SHAPES else "circle"


# ----------------------------------------------------------------------
# Shape preview icon (drawn with QPainter for the toolbar rows)
# ----------------------------------------------------------------------

class ShapeIconWidget(QWidget):
    """Small fixed-size widget that paints a single marker shape."""

    def __init__(self, shape="circle", parent=None):
        super().__init__(parent)

        self.shape = shape if shape in MARKER_SHAPES else "circle"

        self.setFixedSize(28, 28)

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        cx = w / 2.0
        cy = h / 2.0

        r = min(w, h) / 2.0 - 3.0

        painter.setPen(QPen(QColor(0, 0, 0), 1.5))
        painter.setBrush(QColor(120, 120, 120))

        if self.shape == "circle":
            painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

        elif self.shape == "square":
            half = r / math.sqrt(2.0)
            painter.drawRect(
                QRectF(cx - half, cy - half, 2 * half, 2 * half))

        elif self.shape == "triangle":
            pts = QPolygonF()
            for k in range(3):
                ang = math.radians(-90.0 + k * 120.0)
                pts.append(QPointF(cx + r * math.cos(ang),
                                   cy + r * math.sin(ang)))
            painter.drawPolygon(pts)

        elif self.shape == "star":
            inner = r * 0.45
            pts = QPolygonF()
            for k in range(10):
                ang = math.radians(-90.0 + k * 36.0)
                rad = r if k % 2 == 0 else inner
                pts.append(QPointF(cx + rad * math.cos(ang),
                                   cy + rad * math.sin(ang)))
            painter.drawPolygon(pts)


# ----------------------------------------------------------------------
# Image canvas
# ----------------------------------------------------------------------

class ImageCanvas(QWidget):
    marker_added = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__()

        # The canvas is embedded inside a QScrollArea later on, so its
        # real Qt parent is NOT the main window. Keep an explicit
        # reference to the app instead; voltage_to_color() needs it to
        # read the color scale endpoints (otherwise it silently fell
        # back to hardcoded blue and every marker/legend looked blue).
        self.app = parent

        self.setMinimumSize(500, 500)
        self.setMouseTracking(True)

        self.base_image = None
        self.display_image = None
        self.display_pixmap = QPixmap()
        self.display_rect = QRectF()

        self.zoom = 1.0
        self.rotation = 0.0

        self.pan_x = 0.0
        self.pan_y = 0.0

        self.markers = []

        self.middle_dragging = False
        self.last_mouse_pos = QPoint()

    # ------------------------------------------------------------------

    def set_image(self, image):
        self.base_image = image.copy()
        self.zoom = 1.0
        self.rotation = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.markers = []
        self.render_image()

    # ------------------------------------------------------------------

    def set_markers(self, markers):
        self.markers = markers
        self.render_image()

    # ------------------------------------------------------------------

    def set_rotation(self, angle):
        self.rotation = float(angle)
        self.render_image()

    # ------------------------------------------------------------------

    def reset_view(self):
        self.zoom = 1.0
        self.rotation = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.render_image()

    # ------------------------------------------------------------------

    def zoom_by(self, factor, center=None):
        old_zoom = self.zoom

        new_zoom = max(0.05, min(old_zoom * factor, 20.0))

        if new_zoom == old_zoom:
            return

        scale = new_zoom / old_zoom
        self.zoom = new_zoom

        # The displayed image rect is always centered in the widget plus
        # the pan offset (see update_display_rect), so under a pure zoom
        # it scales about the widget center — not about the cursor. To
        # keep the image point currently under the cursor pinned there,
        # solve for the pan that places that same image point back under
        # the cursor after the zoom.
        x = self.display_rect.x()
        y = self.display_rect.y()
        w = self.display_rect.width()
        h = self.display_rect.height()

        if w <= 0 or h <= 0:
            self.render_image()
            return

        if center is not None:
            ax = float(center.x())
            ay = float(center.y())
        else:
            ax = self.width() / 2.0
            ay = self.height() / 2.0

        # Fractional position of the anchor within the current image rect.
        u = (ax - x) / w
        v = (ay - y) / h

        new_w = w * scale
        new_h = h * scale

        # New rect center is (widget_size/2 + pan); choose pan so that
        # anchor = center + (u - 1/2) * new_size.
        self.pan_x = ax - (self.width() - new_w) / 2.0 - u * new_w
        self.pan_y = ay - (self.height() - new_h) / 2.0 - v * new_h

        self.render_image()

    # ------------------------------------------------------------------

    def pil_to_qpixmap(self, image):
        rgb = image.convert("RGB")
        data = rgb.tobytes("raw", "RGB")

        qimage = QImage(
            data,
            rgb.width,
            rgb.height,
            rgb.width * 3,
            QImage.Format_RGB888,
        ).copy()

        return QPixmap.fromImage(qimage)

    # ------------------------------------------------------------------

    def render_image(self):
        if self.base_image is None:
            self.display_image = None
            self.display_pixmap = QPixmap()
            self.update()
            return

        image = self.base_image.copy()

        # Draw markers on the unrotated base image.
        draw = ImageDraw.Draw(image)

        for marker in self.markers:
            if marker.is_test:
                fill = (255, 0, 0)
            else:
                fill = self.voltage_to_color(marker.voltage)

            draw_marker_shape(
                draw,
                getattr(marker, "shape", "circle"),
                marker.x,
                marker.y,
                marker.size,
                fill,
            )

        if abs(self.rotation) > 1e-9:
            image = image.rotate(
                self.rotation,
                expand=True,
                fillcolor=(30, 30, 30),
            )

        self.display_image = image
        self.display_pixmap = self.pil_to_qpixmap(image)

        self.update_display_rect()

    # ------------------------------------------------------------------

    def voltage_to_color(self, voltage):
        # Use the explicit app reference; self.parent() is unreliable
        # here because the widget hierarchy may differ from the logical
        # owner passed in the constructor.
        app = getattr(self, "app", None)

        if app is None or not hasattr(app, "color_min"):
            return (0, 0, 255)

        vmin = app.color_min
        vmax = app.color_max

        if vmax <= vmin:
            return (0, 0, 255)

        if voltage is None:
            return (0, 0, 255)

        t = (float(voltage) - vmin) / (vmax - vmin)
        t = max(0.0, min(1.0, t))

        # Blue -> green -> yellow -> orange
        # (same colormap as markup.py; an earlier refactor replaced
        # the anchor colors with a ramp that ended in pure red).
        blue = (0, 0, 255)
        green = (0, 255, 0)
        yellow = (255, 255, 0)
        orange = (255, 165, 0)

        if t <= 1.0 / 3.0:
            u = t * 3.0
            start, end, u = blue, green, u
        elif t <= 2.0 / 3.0:
            u = (t - 1.0 / 3.0) * 3.0
            start, end, u = green, yellow, u
        else:
            u = (t - 2.0 / 3.0) * 3.0
            start, end, u = yellow, orange, u

        return tuple(
            int(start[i] + (end[i] - start[i]) * u)
            for i in range(3)
        )

    # ------------------------------------------------------------------

    def update_display_rect(self):
        if self.display_pixmap.isNull():
            self.display_rect = QRectF()
            self.update()
            return

        iw = self.display_pixmap.width()
        ih = self.display_pixmap.height()

        available_w = self.width()
        available_h = self.height()

        scale = min(
            available_w / iw,
            available_h / ih,
        )

        scale *= self.zoom

        w = iw * scale
        h = ih * scale

        x = (available_w - w) / 2.0 + self.pan_x
        y = (available_h - h) / 2.0 + self.pan_y

        self.display_rect = QRectF(x, y, w, h)

        self.update()

    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        self.update_display_rect()
        super().resizeEvent(event)

    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.fillRect(
            self.rect(),
            QColor(25, 25, 25),
        )

        if self.display_pixmap.isNull():
            painter.setPen(Qt.white)

            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "Open an image",
            )

            return

        source_rect = QRectF(
            0,
            0,
            self.display_pixmap.width(),
            self.display_pixmap.height(),
        )

        painter.drawPixmap(
            self.display_rect,
            self.display_pixmap,
            source_rect,
        )

    # ------------------------------------------------------------------

    def widget_to_rotated_image(self, pos):
        if self.display_pixmap.isNull():
            return None

        if (
            self.display_rect.width() <= 0
            or self.display_rect.height() <= 0
        ):
            return None

        x = (
            (pos.x() - self.display_rect.left())
            * self.display_pixmap.width()
            / self.display_rect.width()
        )

        y = (
            (pos.y() - self.display_rect.top())
            * self.display_pixmap.height()
            / self.display_rect.height()
        )

        return x, y

    # ------------------------------------------------------------------

    def rotated_to_base_image(self, x, y):
        if self.base_image is None or self.display_image is None:
            return None

        cx_rotated = self.display_image.width / 2.0
        cy_rotated = self.display_image.height / 2.0

        cx_base = self.base_image.width / 2.0
        cy_base = self.base_image.height / 2.0

        dx = x - cx_rotated
        dy = y - cy_rotated

        theta = math.radians(self.rotation)

        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        base_dx = dx * cos_t - dy * sin_t
        base_dy = dx * sin_t + dy * cos_t

        bx = base_dx + cx_base
        by = base_dy + cy_base

        return bx, by

    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.middle_dragging = True
            self.last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() == Qt.LeftButton:
            rotated = self.widget_to_rotated_image(
                event.position().toPoint()
            )

            if rotated is None:
                return

            base = self.rotated_to_base_image(
                *rotated
            )

            if base is None:
                return

            bx, by = base

            if (
                self.base_image is not None
                and 0 <= bx < self.base_image.width
                and 0 <= by < self.base_image.height
            ):
                self.marker_added.emit(bx, by)

    # ------------------------------------------------------------------

    def mouseMoveEvent(self, event):
        if self.middle_dragging:
            current = event.position().toPoint()

            delta = current - self.last_mouse_pos

            self.pan_x += delta.x()
            self.pan_y += delta.y()

            self.last_mouse_pos = current

            self.update_display_rect()

    # ------------------------------------------------------------------

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.middle_dragging = False
            self.setCursor(Qt.ArrowCursor)

    # ------------------------------------------------------------------

    def wheelEvent(self, event):
        delta = event.angleDelta().y()

        if delta > 0:
            self.zoom_by(
                1.15,
                event.position().toPoint(),
            )

        elif delta < 0:
            self.zoom_by(
                1 / 1.15,
                event.position().toPoint(),
            )


# ----------------------------------------------------------------------
# USMELT waveform preview
# ----------------------------------------------------------------------

class WaveformPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.v1 = 1.0
        self.t1 = 10.0
        self.v2 = 2.0
        self.t2 = 10.0
        self.delay = 0.0

        self.setMinimumSize(400, 250)

    # ------------------------------------------------------------------

    def set_values(self, v1, t1, v2, t2, delay):
        self.v1 = v1
        self.t1 = t1
        self.v2 = v2
        self.t2 = t2
        self.delay = delay

        self.update()

    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.fillRect(
            self.rect(),
            Qt.white,
        )

        width = self.width()
        height = self.height()

        left = 55
        right = 20
        top = 20
        bottom = 45

        plot_w = width - left - right
        plot_h = height - top - bottom

        if plot_w <= 0 or plot_h <= 0:
            return

        total_time = (
            max(0.0, self.delay)
            + max(0.0, self.t1)
            + max(0.0, self.t2)
            + 10.0
        )

        if total_time <= 0:
            total_time = 1.0

        max_voltage = max(
            abs(self.v1),
            abs(self.v2),
            1.0,
        )

        # Grid.
        painter.setPen(
            QPen(
                QColor(220, 220, 220),
                1,
            )
        )

        for i in range(6):
            x = left + plot_w * i / 5

            painter.drawLine(
                int(x),
                top,
                int(x),
                top + plot_h,
            )

        for i in range(5):
            y = top + plot_h * i / 4

            painter.drawLine(
                left,
                int(y),
                left + plot_w,
                int(y),
            )

        # Axes.
        painter.setPen(
            QPen(
                Qt.black,
                1,
            )
        )

        painter.drawLine(
            left,
            top,
            left,
            top + plot_h,
        )

        painter.drawLine(
            left,
            top + plot_h,
            left + plot_w,
            top + plot_h,
        )

        def tx(t):
            return left + (t / total_time) * plot_w

        def ty(v):
            return (
                top
                + plot_h / 2
                - (v / max_voltage)
                * (plot_h / 2)
            )

        points = []

        t = 0.0

        points.append(
            (
                tx(t),
                ty(0.0),
            )
        )

        # Delay.
        t += max(
            0.0,
            self.delay,
        )

        points.append(
            (
                tx(t),
                ty(0.0),
            )
        )

        # V1.
        points.append(
            (
                tx(t),
                ty(self.v1),
            )
        )

        t += max(
            0.0,
            self.t1,
        )

        points.append(
            (
                tx(t),
                ty(self.v1),
            )
        )

        # V2.
        points.append(
            (
                tx(t),
                ty(self.v2),
            )
        )

        t += max(
            0.0,
            self.t2,
        )

        points.append(
            (
                tx(t),
                ty(self.v2),
            )
        )

        # 10 us tail.
        t += 10.0

        points.append(
            (
                tx(t),
                ty(0.0),
            )
        )

        polygon = QPolygonF(
            [
                QPoint(
                    int(x),
                    int(y),
                )
                for x, y in points
            ]
        )

        # Filled waveform.
        fill_path = QPainterPath()

        fill_path.moveTo(
            points[0][0],
            top + plot_h / 2,
        )

        for x, y in points:
            fill_path.lineTo(
                x,
                y,
            )

        fill_path.lineTo(
            points[-1][0],
            top + plot_h / 2,
        )

        fill_path.closeSubpath()

        painter.fillPath(
            fill_path,
            QColor(220, 235, 255),
        )

        # Waveform line.
        painter.setPen(
            QPen(
                QColor(0, 90, 200),
                2,
            )
        )

        painter.drawPolyline(
            polygon
        )

        # Labels.
        painter.setPen(Qt.black)

        painter.setFont(
            QFont(
                "Helvetica",
                8,
            )
        )

        painter.drawText(
            5,
            top + 5,
            f"{max_voltage:.2f} V",
        )

        painter.drawText(
            5,
            top + plot_h - 2,
            f"{-max_voltage:.2f} V",
        )

        painter.drawText(
            left + plot_w // 2 - 25,
            height - 8,
            "time (us)",
        )

        painter.drawText(
            8,
            top + plot_h // 2,
            "0 V",
        )


# ----------------------------------------------------------------------
# USMELT controller
# ----------------------------------------------------------------------

class MelterPanel(QGroupBox):
    voltage_high1_changed = Signal()
    # Emitted when the effective CH1 high voltage changes,
    # i.e. also when pulse shaping is toggled on/off.
    effective_voltage_changed = Signal()

    def __init__(self, parent=None, offline=False):
        super().__init__(
            "USMELT (offline)" if offline else "USMELT",
            parent,
        )

        # Offline mode: never discover/open the pulse generator.
        self.offline = bool(offline) or OFFLINE_MODE

        self.pg = None
        self.device_name = ""

        self.config_path = Path(
            "usmelt.ini"
        )

        self.config = configparser.ConfigParser()

        if self.config_path.exists():
            self.config.read(
                self.config_path
            )

        self.melt_sound = self.config.getboolean(
            "General",
            "MeltSound",
            fallback=True,
        )

        # Last valid CH1 Voltage High entered by the user.
        # Kept so that markers keep using the correct value
        # even while the entry field temporarily holds invalid
        # or empty text.
        self.last_valid_voltage_high1 = 5.0

        self.use_shaping_value = self.config.getboolean(
            "PulseShaping",
            "UseShaping",
            fallback=False,
        )

        self.shaping_v1 = self.config.getfloat(
            "PulseShaping",
            "V1",
            fallback=5.0,
        )

        self.shaping_t1 = self.config.getfloat(
            "PulseShaping",
            "T1",
            fallback=10.0,
        )

        self.shaping_v2 = self.config.getfloat(
            "PulseShaping",
            "V2",
            fallback=2.5,
        )

        self.shaping_t2 = self.config.getfloat(
            "PulseShaping",
            "T2",
            fallback=10.0,
        )

        self.build_ui()

        if self.offline:
            # IMPORTANT: in offline mode we must not touch the
            # device at all -- skip USMELT discovery/initialization.
            self.pg = None
            self.device_name = ""
        else:
            # IMPORTANT:
            # Use the original USMELT discovery and initialization path.
            self.find_and_init_pg()

        self.update_channel_states()

    # ------------------------------------------------------------------

    def build_ui(self):
        main_layout = QVBoxLayout(self)

        channels = QGridLayout()

        channels.setHorizontalSpacing(8)
        channels.setVerticalSpacing(5)

        # --------------------------------------------------------------
        # Channel 1
        # --------------------------------------------------------------

        ch1_group = QGroupBox(
            "Channel 1"
        )

        ch1_layout = QGridLayout(
            ch1_group
        )

        self.enable_ch1 = QCheckBox(
            "Enable"
        )

        self.enable_ch1.toggled.connect(
            self.toggle_ch1_elements
        )

        self.pulse_length1_entry = QLineEdit(
            "20"
        )

        self.voltage_high1_entry = QLineEdit(
            "5"
        )

        self.delay1_entry = QLineEdit(
            "0"
        )

        ch1_layout.addWidget(
            self.enable_ch1,
            0,
            0,
            1,
            2,
        )

        ch1_layout.addWidget(
            QLabel("Pulse Length (us)"),
            1,
            0,
        )

        ch1_layout.addWidget(
            self.pulse_length1_entry,
            1,
            1,
        )

        ch1_layout.addWidget(
            QLabel("Voltage High (V)"),
            2,
            0,
        )

        ch1_layout.addWidget(
            self.voltage_high1_entry,
            2,
            1,
        )

        ch1_layout.addWidget(
            QLabel("Delay (us)"),
            3,
            0,
        )

        ch1_layout.addWidget(
            self.delay1_entry,
            3,
            1,
        )

        self.use_shaping = QCheckBox(
            "Use Shaping"
        )

        self.use_shaping.setChecked(
            self.use_shaping_value
        )

        self.use_shaping.toggled.connect(
            self.on_shaping_toggled
        )

        self.setup_shaping_button = QPushButton(
            "Setup Shaping"
        )

        self.setup_shaping_button.clicked.connect(
            self.open_shaping_dialog
        )

        ch1_layout.addWidget(
            self.use_shaping,
            4,
            0,
            1,
            2,
        )

        ch1_layout.addWidget(
            self.setup_shaping_button,
            5,
            0,
            1,
            2,
        )

        # --------------------------------------------------------------
        # Channel 2
        # --------------------------------------------------------------

        ch2_group = QGroupBox(
            "Channel 2"
        )

        ch2_layout = QGridLayout(
            ch2_group
        )

        self.enable_ch2 = QCheckBox(
            "Enable"
        )

        self.enable_ch2.toggled.connect(
            self.toggle_ch2_elements
        )

        self.pulse_length2_entry = QLineEdit(
            "20"
        )

        self.voltage_high2_entry = QLineEdit(
            "5"
        )

        self.delay2_entry = QLineEdit(
            "0"
        )

        ch2_layout.addWidget(
            self.enable_ch2,
            0,
            0,
            1,
            2,
        )

        ch2_layout.addWidget(
            QLabel("Pulse Length (us)"),
            1,
            0,
        )

        ch2_layout.addWidget(
            self.pulse_length2_entry,
            1,
            1,
        )

        ch2_layout.addWidget(
            QLabel("Voltage High (V)"),
            2,
            0,
        )

        ch2_layout.addWidget(
            self.voltage_high2_entry,
            2,
            1,
        )

        ch2_layout.addWidget(
            QLabel("Delay (us)"),
            3,
            0,
        )

        ch2_layout.addWidget(
            self.delay2_entry,
            3,
            1,
        )

        channels.addWidget(
            ch1_group,
            0,
            0,
        )

        channels.addWidget(
            ch2_group,
            0,
            1,
        )

        main_layout.addLayout(
            channels
        )

        # --------------------------------------------------------------
        # Melt button
        # --------------------------------------------------------------

        self.melt_button = QPushButton(
            "Melt"
        )

        self.melt_button.setMinimumHeight(
            36
        )

        if self.offline:
            # No device in offline mode: the Melt button is
            # unavailable, but all parameter fields stay editable.
            self.melt_button.setEnabled(False)
            self.melt_button.setText(
                "Melt (offline — no device)"
            )
            self.melt_button.setToolTip(
                "Disabled because the application was started "
                "with --offline; no pulse generator is connected."
            )

        self.melt_button.clicked.connect(
            self.melt
        )

        main_layout.addWidget(
            self.melt_button
        )

        # Monitor current CH1 voltage field.
        self.voltage_high1_entry.textChanged.connect(
            self.on_voltage_high1_changed
        )

    # ------------------------------------------------------------------

    def find_and_init_pg(self):
        """
        Original USMELT device discovery and initialization.

        IMPORTANT:
        usmelt.discover() returns a dictionary keyed by device type.
        """

        self.device_name = ""

        # First find the USB device that corresponds
        # to the pulse generator.
        device = usmelt.discover(
            ["TG5012A"]
        )

        self.device_name = device[
            "TG5012A"
        ].device

        self.pg = usmelt.TG5012A(
            serial_port=self.device_name
        )

        self.init_pg()

    # ------------------------------------------------------------------

    def init_pg(self):
        """
        Original TG5012A initialization.
        """

        # --- Channel 1 settings ---
        self.pg.channel(1)
        self.pg.wave("PULSE")
        self.pg.pulse_period(
            10e-3
        )
        self.pg.high(1)
        self.pg.low(0)
        self.pg.pulse_rise(
            10e-9
        )
        self.pg.pulse_fall(
            10e-9
        )
        self.pg.pulse_delay(0)
        self.pg.burst("OFF")
        self.pg.burst_count(1)
        self.pg.trigger_src("MAN")
        self.pg.output("OFF")

        # --- Channel 2 settings ---
        self.pg.channel(2)
        self.pg.wave("PULSE")
        self.pg.pulse_period(
            10e-3
        )
        self.pg.high(1)
        self.pg.low(0)
        self.pg.pulse_rise(
            10e-9
        )
        self.pg.pulse_fall(
            10e-9
        )
        self.pg.pulse_delay(0)
        self.pg.burst("OFF")
        self.pg.burst_count(1)

        # Take trigger from channel 1.
        self.pg.trigger_src("CRC")
        self.pg.output("OFF")

    # ------------------------------------------------------------------

    def on_voltage_high1_changed(self):
        # Remember the last valid value so that markers keep using
        # a sensible voltage even while the entry temporarily holds
        # invalid or empty text (e.g. mid-edit).
        try:
            self.last_valid_voltage_high1 = float(
                self.voltage_high1_entry.text().strip()
            )
        except (TypeError, ValueError):
            pass

        self.voltage_high1_changed.emit()

    # ------------------------------------------------------------------

    def get_voltage_high1(self):
        try:
            return float(
                self.voltage_high1_entry.text().strip()
            )
        except (TypeError, ValueError):
            # Fall back to the last valid value instead of None,
            # otherwise every marker typed with an in-between edit
            # state would be treated as "no voltage" / default.
            return self.last_valid_voltage_high1

    # ------------------------------------------------------------------

    def get_effective_voltage_high1(self):
        """
        Return the CH1 high voltage actually used by the melt pulse.

        In standard mode this is the Voltage High entry. When pulse
        shaping is enabled, melt() drives the shaped waveform from
        V1/V2 instead, so the entry value must not be used for the
        marker colors (this was why markers were stuck at the
        gradient's lower bound or flagged as Test 5.00 V).
        """

        if (
            self.enable_ch1.isChecked()
            and self.use_shaping.isChecked()
        ):
            return max(
                0.0,
                float(self.shaping_v1),
                float(self.shaping_v2),
            )

        return self.get_voltage_high1()

    # ------------------------------------------------------------------

    def toggle_ch1_elements(self):
        enabled = self.enable_ch1.isChecked()
        shaping = self.use_shaping.isChecked()

        # In offline mode the Enable checkbox is only used to decide
        # whether the parameter fields are editable; it must not
        # disable the voltage / pulse-length inputs, because markers
        # still read their values from these fields.
        if self.offline:
            enabled = True

        # Delay is available whenever CH1 is enabled.
        self.delay1_entry.setEnabled(
            enabled
        )

        # Standard pulse length is disabled during shaping.
        self.pulse_length1_entry.setEnabled(
            enabled and not shaping
        )

        # Voltage remains available because the marker software
        # monitors it continuously.
        self.voltage_high1_entry.setEnabled(
            enabled
        )

        self.use_shaping.setEnabled(
            enabled
        )

        self.setup_shaping_button.setEnabled(
            enabled
        )

        # The effective CH1 voltage depends on whether shaping is
        # active, so the marker status/colors must be refreshed.
        self.effective_voltage_changed.emit()

    # ------------------------------------------------------------------

    def toggle_ch2_elements(self):
        enabled = self.enable_ch2.isChecked()

        # Same as Channel 1: keep the fields editable in offline
        # mode regardless of the Enable checkbox.
        if self.offline:
            enabled = True

        self.pulse_length2_entry.setEnabled(
            enabled
        )

        self.voltage_high2_entry.setEnabled(
            enabled
        )

        self.delay2_entry.setEnabled(
            enabled
        )

    # ------------------------------------------------------------------

    def update_channel_states(self):
        self.toggle_ch1_elements()
        self.toggle_ch2_elements()

    # ------------------------------------------------------------------

    def on_shaping_toggled(self, checked):
        self.use_shaping_value = checked

        self.toggle_ch1_elements()
        self.save_settings()

    # ------------------------------------------------------------------

    def save_settings(self):
        if not self.config.has_section(
            "General"
        ):
            self.config.add_section(
                "General"
            )

        if not self.config.has_section(
            "PulseShaping"
        ):
            self.config.add_section(
                "PulseShaping"
            )

        self.config.set(
            "General",
            "MeltSound",
            str(self.melt_sound),
        )

        self.config.set(
            "PulseShaping",
            "UseShaping",
            str(
                self.use_shaping.isChecked()
            ),
        )

        self.config.set(
            "PulseShaping",
            "V1",
            str(self.shaping_v1),
        )

        self.config.set(
            "PulseShaping",
            "T1",
            str(self.shaping_t1),
        )

        self.config.set(
            "PulseShaping",
            "V2",
            str(self.shaping_v2),
        )

        self.config.set(
            "PulseShaping",
            "T2",
            str(self.shaping_t2),
        )

        try:
            with self.config_path.open(
                "w",
                encoding="utf-8",
            ) as f:
                self.config.write(f)

        except Exception as exc:
            QMessageBox.warning(
                self,
                "USMELT",
                f"Could not save settings:\n\n{exc}",
            )

    # ------------------------------------------------------------------

    def validate_float(self, widget, name):
        text = widget.text().strip()

        try:
            return float(text)

        except ValueError:
            raise ValueError(
                f"{name} must be a valid number."
            )

    # ------------------------------------------------------------------

    def validate_inputs(self):
        try:
            # ==========================================================
            # CH1
            # ==========================================================

            delay1 = self.validate_float(
                self.delay1_entry,
                "Channel 1 delay",
            )

            if delay1 < 0:
                raise ValueError(
                    "Channel 1 delay must be >= 0."
                )

            if self.enable_ch1.isChecked():

                if self.use_shaping.isChecked():
                    pulse_length1 = 0.0
                    voltage_high1 = 0.0

                else:
                    # Read CURRENT GUI values.
                    pulse_length1 = self.validate_float(
                        self.pulse_length1_entry,
                        "Channel 1 pulse length",
                    )

                    voltage_high1 = self.validate_float(
                        self.voltage_high1_entry,
                        "Channel 1 voltage high",
                    )

                    if pulse_length1 <= 0:
                        raise ValueError(
                            "Channel 1 pulse length must be > 0."
                        )

                    if voltage_high1 <= 0:
                        raise ValueError(
                            "Channel 1 voltage high must be > 0."
                        )

            else:
                pulse_length1 = 0.0
                voltage_high1 = 0.0

            # ==========================================================
            # CH2
            # ==========================================================

            if self.enable_ch2.isChecked():

                # Read CURRENT GUI values.
                pulse_length2 = self.validate_float(
                    self.pulse_length2_entry,
                    "Channel 2 pulse length",
                )

                voltage_high2 = self.validate_float(
                    self.voltage_high2_entry,
                    "Channel 2 voltage high",
                )

                delay2 = self.validate_float(
                    self.delay2_entry,
                    "Channel 2 delay",
                )

                if pulse_length2 <= 0:
                    raise ValueError(
                        "Channel 2 pulse length must be > 0."
                    )

                if voltage_high2 <= 0:
                    raise ValueError(
                        "Channel 2 voltage high must be > 0."
                    )

                if delay2 < 0:
                    raise ValueError(
                        "Channel 2 delay must be >= 0."
                    )

            else:
                pulse_length2 = 0.0
                voltage_high2 = 0.0
                delay2 = 0.0

            return {
                "pulse_length1": pulse_length1,
                "voltage_high1": voltage_high1,
                "delay1": delay1,
                "pulse_length2": pulse_length2,
                "voltage_high2": voltage_high2,
                "delay2": delay2,
            }

        except ValueError as exc:
            QMessageBox.critical(
                self,
                "Invalid Input",
                str(exc),
            )

            return None

    # ------------------------------------------------------------------

    def read_shaping_parameters(self):
        try:
            v1 = float(
                self.shaping_v1
            )

            t1 = float(
                self.shaping_t1
            )

            v2 = float(
                self.shaping_v2
            )

            t2 = float(
                self.shaping_t2
            )

            if v1 < 0 or v2 < 0:
                raise ValueError(
                    "Shaping voltages must be >= 0."
                )

            if t1 <= 0:
                raise ValueError(
                    "T1 must be > 0."
                )

            if t2 <= 0:
                raise ValueError(
                    "T2 must be > 0."
                )

            return v1, t1, v2, t2

        except (TypeError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "Invalid Shaping Parameters",
                str(exc),
            )

            return None

    # ------------------------------------------------------------------

    def melt(self):
        """
        Program TG5012A using CURRENT GUI values.

        The hardware API calls follow the original USMELT code.
        """

        if self.offline:
            # Should not normally happen (button is disabled), but
            # guard against keyboard activation or programmatic use.
            QMessageBox.information(
                self,
                "Offline mode",
                "The application was started with --offline, "
                "so no pulse generator is connected and melting "
                "is disabled.",
            )
            return

        if self.pg is None:
            QMessageBox.critical(
                self,
                "Device Error",
                "Pulse generator not initialized.",
            )
            return

        ch1_params, ch2_params = (
            None,
            None,
        )

        params = self.validate_inputs()

        if params is None:
            return

        pulse_length1 = params[
            "pulse_length1"
        ]

        voltage_high1 = params[
            "voltage_high1"
        ]

        delay1 = params[
            "delay1"
        ]

        pulse_length2 = params[
            "pulse_length2"
        ]

        voltage_high2 = params[
            "voltage_high2"
        ]

        delay2 = params[
            "delay2"
        ]

        try:
            # ==========================================================
            # CHANNEL 1
            # ==========================================================

            if self.enable_ch1.isChecked():

                if self.use_shaping.isChecked():

                    shaping = (
                        self.read_shaping_parameters()
                    )

                    if shaping is None:
                        return

                    v1, t1, v2, t2 = shaping

                    t_tail = 10.0

                    t_total = (
                        delay1
                        + t1
                        + t2
                        + t_tail
                    )

                    num_points = 10000

                    n_delay = int(
                        round(
                            num_points
                            * delay1
                            / t_total
                        )
                    )

                    n_t1 = int(
                        round(
                            num_points
                            * t1
                            / t_total
                        )
                    )

                    n_t2 = int(
                        round(
                            num_points
                            * t2
                            / t_total
                        )
                    )

                    n_tail = (
                        num_points
                        - n_delay
                        - n_t1
                        - n_t2
                    )

                    # Keep the original waveform construction.
                    voltages = (
                        [0.0]
                        + [0.0] * n_delay
                        + [v1] * n_t1
                        + [v2] * n_t2
                        + [0.0] * n_tail
                    )

                    vmin = min(
                        0.0,
                        v1,
                        v2,
                    )

                    vmax = max(
                        0.0,
                        v1,
                        v2,
                    )

                    vpp = vmax - vmin

                    if vpp < 0.01:
                        vpp = 0.01

                    voffset = (
                        vmax + vmin
                    ) / 2.0

                    # Scale to 14-bit.
                    points = []

                    for v in voltages:
                        y = int(
                            round(
                                (2**14 - 1)
                                * (
                                    v / vpp
                                )
                            )
                        )

                        y = max(
                            0,
                            min(
                                2**14 - 1,
                                y,
                            ),
                        )

                        points.append(y)

                    print(
                        f"CH1 (Shaping): "
                        f"V1: {v1}V for {t1}us, "
                        f"V2: {v2}V for {t2}us, "
                        f"Delay: {delay1}us, "
                        f"Vpp: {vpp:.3f}V, "
                        f"Voffset: {voffset:.3f}V"
                    )

                    # Original TG5012A programming.
                    self.pg.channel(1)
                    self.pg.output_load(50)

                    self.pg.upload_arb(
                        "ARB1",
                        points,
                        interpolation="OFF",
                    )

                    self.pg.set(
                        "ARBLOAD",
                        "ARB1",
                    )

                    self.pg.wave(
                        "ARB"
                    )

                    self.pg.offset(
                        voffset
                    )

                    self.pg.amplitude(
                        vpp
                    )

                    self.pg.period(
                        t_total * 1e-6
                    )

                    self.pg.burst(
                        "NCYC"
                    )

                    self.pg.burst_count(1)

                    self.pg.trigger_src(
                        "MAN"
                    )

                    self.pg.output(
                        "ON"
                    )

                else:
                    # --------------------------------------------------
                    # STANDARD CH1
                    #
                    # These values are read immediately from the
                    # current GUI contents by validate_inputs().
                    # --------------------------------------------------

                    print(
                        f"CH1: "
                        f"Pulse: {pulse_length1}us, "
                        f"Voltage: {voltage_high1}V, "
                        f"Delay: {delay1}us"
                    )

                    self.pg.channel(1)
                    self.pg.output_load(50)
                    self.pg.wave("PULSE")
                    self.pg.burst("NCYC")
                    self.pg.burst_count(1)
                    self.pg.trigger_src("MAN")

                    self.pg.pulse_width(
                        pulse_length1 * 1e-6
                    )

                    # The order between low and high matters.
                    self.pg.low(0.0)

                    self.pg.high(
                        voltage_high1
                    )

                    self.pg.pulse_delay(
                        delay1 * 1e-6
                    )

                    self.pg.output("ON")

            else:
                self.pg.channel(1)
                self.pg.output("OFF")

            # ==========================================================
            # CHANNEL 2
            # ==========================================================

            if self.enable_ch2.isChecked():

                print(
                    f"CH2: "
                    f"Pulse: {pulse_length2}us, "
                    f"Voltage: {voltage_high2}V, "
                    f"Delay: {delay2}us"
                )

                self.pg.channel(2)
                self.pg.output_load(50)
                self.pg.wave("PULSE")
                self.pg.burst("NCYC")
                self.pg.burst_count(1)
                self.pg.trigger_src("CRC")

                self.pg.pulse_width(
                    pulse_length2 * 1e-6
                )

                # The order between low and high matters.
                self.pg.low(0.0)

                self.pg.high(
                    voltage_high2
                )

                self.pg.pulse_delay(
                    delay2 * 1e-6
                )

                self.pg.output("ON")

            else:
                self.pg.channel(2)
                self.pg.output("OFF")

            # ==========================================================
            # SOUND + TRIGGER
            # ==========================================================

            if (
                self.enable_ch1.isChecked()
                or self.enable_ch2.isChecked()
            ):

                if self.melt_sound:
                    sound_effect_path = (
                        Path(__file__).parent
                        / "sounds"
                        / "short-laser-sfx.wav"
                    )

                    winsound.PlaySound(
                        str(sound_effect_path),
                        winsound.SND_FILENAME,
                    )

                self.pg.channel(1)

                self.pg.trigger()

                # Disable both outputs after the pulse.
                self.pg.channel(1)
                self.pg.output("OFF")

                self.pg.channel(2)
                self.pg.output("OFF")

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Melt Error",
                f"Could not execute melt:\n\n{exc}",
            )

            try:
                if self.pg is not None:
                    self.pg.channel(1)
                    self.pg.output("OFF")

                    self.pg.channel(2)
                    self.pg.output("OFF")

            except Exception:
                pass

    # ------------------------------------------------------------------

    def open_shaping_dialog(self):
        dialog = QDialog(
            self
        )

        dialog.setWindowTitle(
            "Pulse Shaping"
        )

        dialog.setModal(True)

        layout = QVBoxLayout(
            dialog
        )

        content = QHBoxLayout()

        # --------------------------------------------------------------
        # Parameters
        # --------------------------------------------------------------

        parameter_group = QGroupBox(
            "Pulse Parameters"
        )

        form = QFormLayout(
            parameter_group
        )

        v1_entry = QLineEdit(
            str(self.shaping_v1)
        )

        t1_entry = QLineEdit(
            str(self.shaping_t1)
        )

        v2_entry = QLineEdit(
            str(self.shaping_v2)
        )

        t2_entry = QLineEdit(
            str(self.shaping_t2)
        )

        form.addRow(
            "V1 (V)",
            v1_entry,
        )

        form.addRow(
            "T1 (us)",
            t1_entry,
        )

        form.addRow(
            "V2 (V)",
            v2_entry,
        )

        form.addRow(
            "T2 (us)",
            t2_entry,
        )

        content.addWidget(
            parameter_group
        )

        # --------------------------------------------------------------
        # Preview
        # --------------------------------------------------------------

        preview_group = QGroupBox(
            "Waveform Preview"
        )

        preview_layout = QVBoxLayout(
            preview_group
        )

        preview = WaveformPreview()

        preview_layout.addWidget(
            preview
        )

        content.addWidget(
            preview_group
        )

        layout.addLayout(
            content
        )

        # --------------------------------------------------------------
        # Live preview
        # --------------------------------------------------------------

        def update_preview():
            try:
                v1 = float(
                    v1_entry.text()
                )

                t1 = float(
                    t1_entry.text()
                )

                v2 = float(
                    v2_entry.text()
                )

                t2 = float(
                    t2_entry.text()
                )

            except ValueError:
                return

            delay = 0.0

            try:
                delay = float(
                    self.delay1_entry.text()
                )

            except ValueError:
                pass

            preview.set_values(
                v1,
                t1,
                v2,
                t2,
                delay,
            )

        v1_entry.textChanged.connect(
            update_preview
        )

        t1_entry.textChanged.connect(
            update_preview
        )

        v2_entry.textChanged.connect(
            update_preview
        )

        t2_entry.textChanged.connect(
            update_preview
        )

        self.delay1_entry.textChanged.connect(
            update_preview
        )

        update_preview()

        # --------------------------------------------------------------
        # Buttons
        # --------------------------------------------------------------

        buttons = QHBoxLayout()

        ok_button = QPushButton(
            "OK"
        )

        cancel_button = QPushButton(
            "Cancel"
        )

        buttons.addStretch()

        buttons.addWidget(
            ok_button
        )

        buttons.addWidget(
            cancel_button
        )

        layout.addLayout(
            buttons
        )

        def accept():
            try:
                v1 = float(
                    v1_entry.text()
                )

                t1 = float(
                    t1_entry.text()
                )

                v2 = float(
                    v2_entry.text()
                )

                t2 = float(
                    t2_entry.text()
                )

                if v1 < 0 or v2 < 0:
                    raise ValueError(
                        "Voltages must be >= 0."
                    )

                if t1 <= 0:
                    raise ValueError(
                        "T1 must be greater than 0."
                    )

                if t2 <= 0:
                    raise ValueError(
                        "T2 must be greater than 0."
                    )

            except ValueError as exc:
                QMessageBox.critical(
                    dialog,
                    "Invalid Input",
                    str(exc),
                )

                return

            self.shaping_v1 = v1
            self.shaping_t1 = t1
            self.shaping_v2 = v2
            self.shaping_t2 = t2

            self.save_settings()

            # Shaping voltages feed the marker color scale when
            # shaping is active — refresh the status/colors.
            self.effective_voltage_changed.emit()

            dialog.accept()

        ok_button.clicked.connect(
            accept
        )

        cancel_button.clicked.connect(
            dialog.reject
        )

        dialog.resize(
            850,
            350,
        )

        dialog.exec()

    # ------------------------------------------------------------------

    def set_device(self):
        """
        Original USMELT Set Device behavior.
        """

        if self.offline:
            QMessageBox.information(
                self,
                "Offline mode",
                "Device connections are disabled because the "
                "application was started with --offline.",
            )
            return

        serial_port, ok = QInputDialog.getText(
            self,
            "Set Device",
            "Enter device name:",
            text=self.device_name,
        )

        if not ok:
            return

        new_device = serial_port.strip()

        if not new_device:
            return

        self.device_name = new_device

        try:
            self.pg = usmelt.TG5012A(
                serial_port=self.device_name
            )

            self.init_pg()

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Device Error",
                f"Could not connect to device: {exc}",
            )

            self.pg = None


# ----------------------------------------------------------------------
# Main Image Marker application
# ----------------------------------------------------------------------

class ImageMarkerApp(QMainWindow):
    def __init__(self, offline=None):
        super().__init__()

        # Resolve offline mode: explicit argument wins, otherwise
        # fall back to the module-level flag set from argv.
        if offline is None:
            offline = OFFLINE_MODE

        self.offline = bool(offline)

        self.setWindowTitle(
            "USMELT + Image Marker (offline)"
            if self.offline
            else "USMELT + Image Marker"
        )

        self.resize(
            1500,
            900,
        )

        self.markers = []

        self.undo_stack = []
        self.redo_stack = []

        self.marker_size = 15

        self.color_min = 1.0
        self.color_max = 2.0

        self.current_voltage = None
        self.current_is_test = False

        self.build_menu()
        self.build_ui()

    # ------------------------------------------------------------------

    def build_menu(self):
        settings_menu = (
            self.menuBar().addMenu(
                "Settings"
            )
        )

        set_device_action = QAction(
            "Set Device",
            self,
        )

        set_device_action.triggered.connect(
            self.set_device
        )

        settings_menu.addAction(
            set_device_action
        )

        self.melt_sound_action = QAction(
            "Melt sound",
            self,
        )

        self.melt_sound_action.setCheckable(
            True
        )

        settings_menu.addAction(
            self.melt_sound_action
        )

        settings_menu.addSeparator()

        exit_action = QAction(
            "Exit",
            self,
        )

        exit_action.triggered.connect(
            self.close
        )

        settings_menu.addAction(
            exit_action
        )

    # ------------------------------------------------------------------

    def build_ui(self):
        central = QWidget()

        self.setCentralWidget(
            central
        )

        main_layout = QHBoxLayout(
            central
        )

        main_layout.setContentsMargins(
            6,
            6,
            6,
            6,
        )

        # ==============================================================
        # LEFT TASK BAR
        # ==============================================================

        scroll = QScrollArea()

        scroll.setWidgetResizable(
            True
        )

        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        scroll.setFixedWidth(
            400
        )

        left_widget = QWidget()

        left_layout = QVBoxLayout(
            left_widget
        )

        left_layout.setAlignment(
            Qt.AlignTop
        )

        scroll.setWidget(
            left_widget
        )

        # --------------------------------------------------------------
        # USMELT
        # --------------------------------------------------------------

        self.melter = MelterPanel(
            offline=self.offline
        )

        left_layout.addWidget(
            self.melter
        )

        if self.offline:
            # Grey out the Settings / "Set Device" menu entry, since
            # no device connection can be made in offline mode.
            for action in self.menuBar().actions():
                if action.text() == "Settings":
                    for act in action.menu().actions():
                        if act.text() == "Set Device":
                            act.setEnabled(False)
                            break
                    break

        self.melt_sound_action.setChecked(
            self.melter.melt_sound
        )

        self.melt_sound_action.toggled.connect(
            self.on_melt_sound_toggled
        )

        # --------------------------------------------------------------
        # MARKER CONTROLS
        # --------------------------------------------------------------

        marker_group = QGroupBox(
            "Image Marking"
        )

        marker_layout = QVBoxLayout(
            marker_group
        )

        open_button = QPushButton(
            "Open Image"
        )

        open_button.clicked.connect(
            self.open_image
        )

        marker_layout.addWidget(
            open_button
        )

        # Marker size.
        size_row = QHBoxLayout()

        size_row.addWidget(
            QLabel("Marker Size")
        )

        self.marker_size_slider = QSlider(
            Qt.Horizontal
        )

        self.marker_size_slider.setMinimum(
            2
        )

        self.marker_size_slider.setMaximum(
            100
        )

        self.marker_size_slider.setValue(
            15
        )

        self.marker_size_slider.valueChanged.connect(
            self.marker_size_changed
        )

        self.marker_size_label = QLabel(
            "15 px"
        )

        self.marker_size_label.setFixedWidth(
            45
        )

        size_row.addWidget(
            self.marker_size_slider
        )

        size_row.addWidget(
            self.marker_size_label
        )

        marker_layout.addLayout(
            size_row
        )

        # --------------------------------------------------------------
        # Marker shapes
        #
        # One row per shape in the left tool bar: selection bubble
        # (radio button), a drawn preview of the shape, and a text
        # box for a short description that appears in the exported
        # figure legend when more than one shape is used.
        # --------------------------------------------------------------

        shape_group = QGroupBox(
            "Marker Shapes"
        )

        shape_grid = QGridLayout(
            shape_group
        )

        self.shape_buttons = {}
        self.shape_descriptions = {}

        self.shape_button_group = QButtonGroup(
            self
        )

        self.shape_button_group.setExclusive(
            True
        )

        for row_index, shape_name in enumerate(MARKER_SHAPES):
            radio = QRadioButton()

            radio.setToolTip(
                f"Place new markers as a {shape_name}."
            )

            self.shape_button_group.addButton(
                radio
            )

            self.shape_buttons[shape_name] = radio

            icon = ShapeIconWidget(
                shape_name
            )

            desc_edit = QLineEdit()

            desc_edit.setPlaceholderText(
                f"Description for {shape_name} markers…"
            )

            desc_edit.setToolTip(
                "Short label shown next to this shape in the "
                "exported figure legend (used when multiple "
                "shapes appear on the image)."
            )

            self.shape_descriptions[shape_name] = desc_edit

            shape_grid.addWidget(
                radio,
                row_index,
                0,
            )

            shape_grid.addWidget(
                icon,
                row_index,
                1,
            )

            shape_grid.addWidget(
                desc_edit,
                row_index,
                2,
            )

        shape_grid.setColumnStretch(
            2,
            1,
        )

        # Circle is the default shape.
        self.shape_buttons["circle"].setChecked(
            True
        )

        self.current_shape = "circle"

        self.shape_button_group.buttonClicked.connect(
            self._on_shape_selected
        )

        marker_layout.addWidget(
            shape_group
        )

        # --------------------------------------------------------------
        # Voltage / Test status
        # --------------------------------------------------------------

        voltage_row = QHBoxLayout()

        self.voltage_status_label = QLabel(
            "Voltage: —"
        )

        self.test_checkbox = QCheckBox(
            "Test"
        )

        self.test_checkbox.setEnabled(
            False
        )

        self.test_checkbox.setToolTip(
            "Automatically active when Channel 1 "
            "Voltage High is exactly 5.0 V."
        )

        voltage_row.addWidget(
            self.voltage_status_label
        )

        voltage_row.addStretch()

        voltage_row.addWidget(
            self.test_checkbox
        )

        marker_layout.addLayout(
            voltage_row
        )

        # --------------------------------------------------------------
        # Color scale
        # --------------------------------------------------------------

        color_group = QGroupBox(
            "Voltage Color Scale"
        )

        color_layout = QGridLayout(
            color_group
        )

        self.color_min_spin = QDoubleSpinBox()

        self.color_min_spin.setRange(
            0.0,
            100.0,
        )

        self.color_min_spin.setDecimals(
            2
        )

        self.color_min_spin.setSingleStep(
            0.05
        )

        self.color_min_spin.setValue(
            self.color_min
        )

        self.color_max_spin = QDoubleSpinBox()

        self.color_max_spin.setRange(
            0.0,
            100.0,
        )

        self.color_max_spin.setDecimals(
            2
        )

        self.color_max_spin.setSingleStep(
            0.05
        )

        self.color_max_spin.setValue(
            self.color_max
        )

        self.color_min_spin.valueChanged.connect(
            self.color_range_changed
        )

        self.color_max_spin.valueChanged.connect(
            self.color_range_changed
        )

        color_layout.addWidget(
            QLabel("Min"),
            0,
            0,
        )

        color_layout.addWidget(
            self.color_min_spin,
            0,
            1,
        )

        color_layout.addWidget(
            QLabel("Max"),
            1,
            0,
        )

        color_layout.addWidget(
            self.color_max_spin,
            1,
            1,
        )

        marker_layout.addWidget(
            color_group
        )

        # --------------------------------------------------------------
        # Rotation
        # --------------------------------------------------------------

        rotation_group = QGroupBox(
            "Rotation"
        )

        rotation_layout = QGridLayout(
            rotation_group
        )

        self.rotation_spin = QDoubleSpinBox()

        self.rotation_spin.setRange(
            -360.0,
            360.0,
        )

        self.rotation_spin.setDecimals(
            2
        )

        self.rotation_spin.setSingleStep(
            1.0
        )

        self.rotation_spin.setValue(
            0.0
        )

        self.rotation_spin.valueChanged.connect(
            self.rotation_changed
        )

        rotation_layout.addWidget(
            QLabel("Angle"),
            0,
            0,
        )

        rotation_layout.addWidget(
            self.rotation_spin,
            0,
            1,
        )

        reset_rotation_button = QPushButton(
            "Reset Rotation"
        )

        reset_rotation_button.clicked.connect(
            self.reset_rotation
        )

        rotation_layout.addWidget(
            reset_rotation_button,
            1,
            0,
            1,
            2,
        )

        marker_layout.addWidget(
            rotation_group
        )

        # --------------------------------------------------------------
        # Undo / Redo / Clear
        # --------------------------------------------------------------

        history_row = QHBoxLayout()

        undo_button = QPushButton(
            "Undo"
        )

        undo_button.clicked.connect(
            self.undo
        )

        redo_button = QPushButton(
            "Redo"
        )

        redo_button.clicked.connect(
            self.redo
        )

        clear_button = QPushButton(
            "Clear"
        )

        clear_button.clicked.connect(
            self.clear_markers
        )

        history_row.addWidget(
            undo_button
        )

        history_row.addWidget(
            redo_button
        )

        history_row.addWidget(
            clear_button
        )

        marker_layout.addLayout(
            history_row
        )

        # --------------------------------------------------------------
        # Export
        # --------------------------------------------------------------

        export_button = QPushButton(
            "Export Annotated Image"
        )

        export_button.clicked.connect(
            self.export_image
        )

        marker_layout.addWidget(
            export_button
        )

        left_layout.addWidget(
            marker_group
        )

        # ==============================================================
        # IMAGE CANVAS
        # ==============================================================

        self.canvas = ImageCanvas(
            self
        )

        self.canvas.marker_added.connect(
            self.add_marker
        )

        main_layout.addWidget(
            scroll
        )

        main_layout.addWidget(
            self.canvas,
            1,
        )

        self.melter.voltage_high1_changed.connect(
            self.update_marker_voltage_state
        )

        # Shaping toggles / shaping voltage changes also modify the
        # effective CH1 voltage used for marker colors.
        self.melter.effective_voltage_changed.connect(
            self.update_marker_voltage_state
        )

        self.update_marker_voltage_state()

    # ------------------------------------------------------------------

    def set_device(self):
        self.melter.set_device()

    # ------------------------------------------------------------------

    def on_melt_sound_toggled(self, checked):
        self.melter.melt_sound = checked
        self.melter.save_settings()

    # ------------------------------------------------------------------

    def _on_shape_selected(self, button):
        for name, btn in self.shape_buttons.items():
            if btn is button:
                self.current_shape = name
                return

    # ------------------------------------------------------------------

    def get_current_voltage(self):
        # Use the effective CH1 voltage (shaping-aware), not just
        # whatever the Voltage High entry happens to contain.
        return self.melter.get_effective_voltage_high1()

    # ------------------------------------------------------------------

    def update_marker_voltage_state(self):
        voltage = self.get_current_voltage()

        self.current_voltage = voltage

        if voltage is None:
            self.current_is_test = False

            self.voltage_status_label.setText(
                "Voltage: —"
            )

            self.test_checkbox.setChecked(
                False
            )

            return

        self.current_is_test = math.isclose(
            voltage,
            5.0,
            abs_tol=1e-9,
        )

        self.voltage_status_label.setText(
            f"Voltage: {voltage:.2f} V"
            + (" (offline)" if getattr(self, "offline", False) else "")
        )

        self.test_checkbox.setChecked(
            self.current_is_test
        )

        # Refresh marker rendering so the voltage/status shown in
        # the panel always matches the colors of the markers.
        if self.canvas.base_image is not None:
            self.canvas.render_image()

    # ------------------------------------------------------------------

    def save_undo_state(self):
        self.undo_stack.append(
            copy.deepcopy(
                self.markers
            )
        )

        self.redo_stack.clear()

        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)

    # ------------------------------------------------------------------

    def add_marker(self, x, y):
        voltage = self.get_current_voltage()

        if voltage is None:
            self.voltage_status_label.setText(
                "Voltage: invalid CH1 value"
            )

            return

        self.save_undo_state()

        marker = Marker(
            x=x,
            y=y,
            size=self.marker_size,
            voltage=voltage,
            is_test=math.isclose(
                voltage,
                5.0,
                abs_tol=1e-9,
            ),
            shape=getattr(self, "current_shape", "circle"),
        )

        self.markers.append(
            marker
        )

        self.canvas.set_markers(
            self.markers
        )

    # ------------------------------------------------------------------

    def undo(self):
        if not self.undo_stack:
            return

        self.redo_stack.append(
            copy.deepcopy(
                self.markers
            )
        )

        self.markers = (
            self.undo_stack.pop()
        )

        self.canvas.set_markers(
            self.markers
        )

    # ------------------------------------------------------------------

    def redo(self):
        if not self.redo_stack:
            return

        self.undo_stack.append(
            copy.deepcopy(
                self.markers
            )
        )

        self.markers = (
            self.redo_stack.pop()
        )

        self.canvas.set_markers(
            self.markers
        )

    # ------------------------------------------------------------------

    def clear_markers(self):
        if not self.markers:
            return

        self.save_undo_state()

        self.markers = []

        self.canvas.set_markers(
            self.markers
        )

    # ------------------------------------------------------------------

    def marker_size_changed(self, value):
        self.marker_size = int(
            value
        )

        self.marker_size_label.setText(
            f"{value} px"
        )

    # ------------------------------------------------------------------

    def color_range_changed(self):
        # Always keep the app-level endpoints in sync with the
        # spin boxes; voltage_to_color() reads these values and
        # silently falls back to blue when vmax <= vmin, which is
        # exactly the "all markers are blue" symptom.
        self.color_min = (
            self.color_min_spin.value()
        )

        self.color_max = (
            self.color_max_spin.value()
        )

        if self.color_max <= self.color_min:
            QMessageBox.warning(
                self,
                "Color Scale",
                "Maximum voltage must be greater than "
                "minimum voltage.",
            )

            return

        self.canvas.render_image()

    # ------------------------------------------------------------------

    def rotation_changed(self, value):
        self.canvas.set_rotation(
            value
        )

    # ------------------------------------------------------------------

    def reset_rotation(self):
        self.rotation_spin.blockSignals(
            True
        )

        self.rotation_spin.setValue(
            0.0
        )

        self.rotation_spin.blockSignals(
            False
        )

        self.canvas.set_rotation(
            0.0
        )

    # ------------------------------------------------------------------

    def open_image(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image",
            "",
            "Images (*.jpg *.jpeg *.png)",
        )

        if not file_name:
            return

        try:
            image = Image.open(
                file_name
            ).convert("RGB")

            # Crop equally to square.
            width, height = image.size

            side = min(
                width,
                height,
            )

            left = (
                width - side
            ) // 2

            top = (
                height - side
            ) // 2

            image = image.crop(
                (
                    left,
                    top,
                    left + side,
                    top + side,
                )
            )

            # The color-scale range no longer prompts on import;
            # the current Min/Max spin-box values are kept and can
            # be adjusted later in the Color Scale panel.
            self.markers = []
            self.undo_stack = []
            self.redo_stack = []

            self.rotation_spin.blockSignals(
                True
            )

            self.rotation_spin.setValue(
                0.0
            )

            self.rotation_spin.blockSignals(
                False
            )

            self.canvas.set_image(
                image
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Open Image",
                f"Could not open image:\n\n{exc}",
            )

    # ------------------------------------------------------------------

    def export_image(self):
        if self.canvas.base_image is None:
            QMessageBox.warning(
                self,
                "Export",
                "No image is open.",
            )

            return

        file_name, selected_filter = (
            QFileDialog.getSaveFileName(
                self,
                "Export Annotated Image",
                "",
                "PNG (*.png);;JPEG (*.jpg *.jpeg)",
            )
        )

        if not file_name:
            return

        try:
            image = (
                self.canvas.base_image.copy()
            )

            draw = ImageDraw.Draw(
                image
            )

            # Draw markers.
            for marker in self.markers:
                if marker.is_test:
                    fill = (
                        255,
                        0,
                        0,
                    )

                else:
                    fill = (
                        self.canvas.voltage_to_color(
                            marker.voltage
                        )
                    )

                draw_marker_shape(
                    draw,
                    getattr(marker, "shape", "circle"),
                    marker.x,
                    marker.y,
                    marker.size,
                    fill,
                )

            # Rotate.
            if abs(
                self.canvas.rotation
            ) > 1e-9:

                image = image.rotate(
                    self.canvas.rotation,
                    expand=True,
                    fillcolor=(
                        30,
                        30,
                        30,
                    ),
                )

            # ----------------------------------------------------------
            # Legend (compact box in the top-right corner of the
            # image).  The canvas is never widened, so the exported
            # picture keeps its original size and background.
            # ----------------------------------------------------------

            key_items = self.shape_key_items()

            (
                canvas_w,
                canvas_h,
                legend_w,
                legend_h,
                legend_x,
                legend_y,
            ) = self.legend_layout(
                image.width, image.height, key_items=key_items
            )

            image = self.create_legend(
                image,
                key_items=key_items,
                place=(legend_w, legend_h, legend_x, legend_y),
            )

            image.save(
                file_name
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export",
                f"Could not export image:\n\n{exc}",
            )

    # ------------------------------------------------------------------
    # Voltage legend (drawn onto exported images)
    # ------------------------------------------------------------------

    def used_shapes(self):
        """Distinct marker shapes present on the current image."""
        seen = []
        for marker in self.markers:
            shape = getattr(marker, "shape", "circle")
            if shape not in seen:
                seen.append(shape)
        return seen

    def shape_key_items(self):
        """
        Build the shape/description key entries for the figure legend.

        Returns a list of ``(shape_name, description)`` tuples, or an
        empty list when no key is needed (fewer than two distinct
        shapes on the image).  Shapes without a user description fall
        back to their name.
        """
        shapes = self.used_shapes()

        if len(shapes) < 2:
            return []

        items = []
        for shape in shapes:
            edit = self.shape_descriptions.get(shape)
            desc = edit.text().strip() if edit is not None else ""
            if not desc:
                desc = shape.capitalize()
            items.append((shape, desc))

        return items

    @staticmethod
    def legend_size(image_width, image_height, extra_rows=0):
        """
        Legend box size scaled to the exported image.

        The legend is a compact box: it keeps a fixed design aspect
        ratio (width:height = 5:7 for the base grid) and grows only
        with the image diagonal, capped so it stays a small annotation
        in the top-right corner instead of dominating the figure.
        Base design grid: 150 x 210 units for a 640 x 480 image, plus
        28 vertical units per shape-key row added below the color
        scale.
        """
        design_w = 150.0
        design_h = 210.0 + 28.0 * max(0, int(extra_rows))

        scale = math.sqrt(
            image_width * image_height / (640.0 * 480.0)
        )

        width = int(round(design_w * scale))
        height = int(round(design_h * scale))

        # Compactness cap: keep the legend small relative to the
        # picture (~1/6 of the width, ~1/4 of the height) so it reads
        # as an annotation rather than covering the image.
        cap_w = max(1, image_width // 6)
        cap_h = max(1, image_height // 4)

        k = min(1.0, cap_w / width, cap_h / height)
        width = max(1, int(round(width * k)))
        height = max(1, int(round(height * k)))

        # Ceiling: the legend should never dominate the figure.
        max_w = max(1, image_width // 3)
        max_h = max(1, image_height)

        if width > max_w or height > max_h:
            k = min(max_w / width, max_h / height)
            width = max(1, int(round(width * k)))
            height = max(1, int(round(height * k)))

        # Re-impose the design aspect ratio after any clamping above
        # (shrink the offending dimension so the box stays sane).
        if width / height > design_w / design_h:
            width = max(1, int(round(height * design_w / design_h)))
        else:
            height = max(1, int(round(width * design_h / design_w)))

        return width, height

    def legend_layout(self, image_width, image_height, key_items=None):
        """
        Compute where the legend belongs for an export of an
        ``image_width x image_height`` source image with ``key_items``
        shape rows.

        Returns ``(canvas_w, canvas_h, lw, lh, legend_x, legend_y)``.
        The legend is always a compact box anchored to the top-right
        corner of the image; the canvas is never widened (no white
        strip is added around the picture).
        """
        n_rows = len(key_items) if key_items else 0

        lw, lh = self.legend_size(image_width, image_height,
                                  extra_rows=n_rows)

        # Safety clamp: even for tiny images the legend must fit
        # inside the picture with a small margin.
        margin = max(4, int(round(lw * 0.10)))

        while (lw + 2 * margin > image_width or
               lh + 2 * margin > image_height) and lw > 10:
            lw = max(1, int(round(lw * 0.9)))
            lh = max(1, int(round(lh * 0.9)))
            margin = max(4, int(round(lw * 0.10)))

        return (
            image_width,
            image_height,
            lw,
            lh,
            image_width - lw - margin,
            margin,
        )

    @staticmethod
    def _legend_font(size):
        # Prefer a real TrueType font (crisper at large sizes); fall
        # back to PIL's default bitmap/scaled font if unavailable.
        for path in (
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue

        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # older Pillow without the size parameter
            return ImageFont.load_default()

    def create_legend(self, image, key_items=None, place=None):
        """
        Composite a semi-transparent voltage-gradient legend onto the
        top-right corner of ``image`` (an RGB PIL.Image).  Returns a new
        RGB image; the input is not modified.

        ``key_items`` is an optional list of ``(shape_name, text)``
        tuples drawn beneath the color scale as a shape legend.

        ``place`` optionally overrides the geometry with a tuple
        ``(lw, lh, legend_x, legend_y)`` - used by the export path to
        position the compact legend box in the top-right corner.
        """
        if key_items is None:
            key_items = []

        if place is not None:
            lw, lh, legend_x, legend_y = place
        else:
            lw, lh = self.legend_size(
                image.width, image.height, extra_rows=len(key_items)
            )

            # Layout unit: fit a 150 x 210 design grid (+28 units per key
            # row) inside the box while keeping content proportions correct.
            margin = max(4, int(round(lw * 0.10)))

            legend_x = image.width - lw - margin
            legend_y = margin

        # Layout unit: fit a 150 x 210 design grid (+28 units per key
        # row) inside the box while keeping content proportions correct.
        design_h = 210.0 + 28.0 * len(key_items)
        s = min(lw / 150.0, lh / design_h)

        # Center the design horizontally when the box is wider than tall
        # proportions imply (e.g. after a height clamp).
        ox = max(0.0, (lw - 150.0 * s) / 2.0)

        overlay = Image.new(
            "RGBA",
            (lw, lh),
            (255, 255, 255, 235),
        )

        od = ImageDraw.Draw(overlay)

        border = max(2, int(round(2 * s)))

        od.rectangle(
            [0, 0, lw - 1, lh - 1],
            outline=(0, 0, 0, 255),
            width=border,
        )

        title_font = self._legend_font(max(10, int(round(20 * s))))
        label_font = self._legend_font(max(9, int(round(16 * s))))

        title = "Voltage (kV)"

        tb = od.textbbox((0, 0), title, font=title_font)

        od.text(
            ((lw - (tb[2] - tb[0])) / 2.0, 12 * s),
            title,
            fill=(0, 0, 0, 255),
            font=title_font,
        )

        # ----------------------------------------------------------
        # Content is laid out in non-overlapping vertical bands:
        #   title -> color scale -> shape-key rows -> Test line.
        # The gradient bar only occupies the space left between the
        # title and the bottom text block, so the scale and the
        # description segments can never collide.
        # ----------------------------------------------------------

        # Bottom block height (shape-key rows + the Test line).
        bottom_block = 30.0 * s if key_items else 24.0 * s
        bottom_block += 28.0 * s * len(key_items)

        band_top = 45 * s
        band_bottom = lh - bottom_block

        # Gradient bar: blue (bottom, Min) -> green -> yellow -> orange
        # (top, Max).  Narrower than before (bar takes ~1/3 of width).
        bar_left = ox + 40 * s
        bar_top = band_top
        bar_width = 45 * s
        bar_height = max(18.0 * s, band_bottom - band_top)

        vmax = self.color_max
        vmin = self.color_min

        for i in range(int(bar_height)):
            t = i / max(1.0, bar_height - 1.0)

            color = self.canvas.voltage_to_color(
                vmax - t * (vmax - vmin)
            )

            y = int(bar_top + i)

            od.line(
                [bar_left, y, bar_left + bar_width, y],
                fill=(*color, 255),
                width=1,
            )

        od.rectangle(
            [
                int(bar_left),
                int(bar_top),
                int(bar_left + bar_width),
                int(bar_top + bar_height),
            ],
            outline=(0, 0, 0, 255),
            width=1,
        )

        label_x = bar_left + bar_width + 12 * s

        def draw_label(text, cy):
            bbox = od.textbbox((0, 0), text, font=label_font)
            th = bbox[3] - bbox[1]

            od.text(
                (label_x, cy - th / 2.0 - bbox[1]),
                text,
                fill=(0, 0, 0, 255),
                font=label_font,
            )

        draw_label(f"{vmax:.2f}", bar_top)
        draw_label(f"{(vmin + vmax) / 2.0:.2f}", bar_top + bar_height / 2.0)
        draw_label(f"{vmin:.2f}", bar_top + bar_height)

        # ----------------------------------------------------------
        # Bottom block: shape-key rows (if any) stacked above the
        # "Test" line.  Rows are laid out sequentially from the bottom
        # of the box upward, each in its own band, so nothing can
        # collide with the color scale above or with each other.
        # ----------------------------------------------------------
        row_h = 28.0 * s
        icon_r = 8.0 * s
        dot_r = 9.0 * s
        icon_cx = ox + 15 * s

        def draw_centered_text(text, cx_left, cy):
            bbox = od.textbbox((0, 0), text, font=label_font)
            od.text(
                (cx_left, cy - (bbox[3] - bbox[1]) / 2.0 - bbox[1]),
                text,
                fill=(0, 0, 0, 255),
                font=label_font,
            )

        # "Test = 5.00 V" line: always the last (bottom-most) row,
        # vertically centered in its reserved band at the box bottom.
        test_cy = lh - (15.0 * s if key_items else 12.0 * s)

        od.ellipse(
            [
                icon_cx - dot_r,
                test_cy - dot_r,
                icon_cx + dot_r,
                test_cy + dot_r,
            ],
            fill=(255, 0, 0, 255),
            outline=(0, 0, 0, 255),
            width=1,
        )

        draw_centered_text(
            "Test = 5.00 V", icon_cx + dot_r + 10 * s, test_cy
        )

        # Shape key: one row per (shape, description) directly above
        # the Test line.
        for index, (shape_name, text) in enumerate(reversed(key_items)):
            cy = test_cy - row_h * (index + 1)

            # Draw the shape itself (gray fill, black outline) so
            # the key matches what appears on the image.
            poly = None

            if shape_name == "circle":
                od.ellipse(
                    [
                        icon_cx - icon_r,
                        cy - icon_r,
                        icon_cx + icon_r,
                        cy + icon_r,
                    ],
                    fill=(120, 120, 120, 255),
                    outline=(0, 0, 0, 255),
                    width=1,
                )

            elif shape_name == "square":
                half = icon_r / math.sqrt(2.0)
                od.polygon(
                    [
                        (icon_cx - half, cy - half),
                        (icon_cx + half, cy - half),
                        (icon_cx + half, cy + half),
                        (icon_cx - half, cy + half),
                    ],
                    fill=(120, 120, 120, 255),
                    outline=(0, 0, 0, 255),
                    width=1,
                )

            elif shape_name == "triangle":
                poly = [
                    (
                        icon_cx + icon_r * math.cos(
                            math.radians(-90.0 + k * 120.0)
                        ),
                        cy + icon_r * math.sin(
                            math.radians(-90.0 + k * 120.0)
                        ),
                    )
                    for k in range(3)
                ]
                od.polygon(
                    poly,
                    fill=(120, 120, 120, 255),
                    outline=(0, 0, 0, 255),
                    width=1,
                )

            elif shape_name == "star":
                inner = icon_r * 0.45
                poly = []
                for k in range(10):
                    ang = math.radians(-90.0 + k * 36.0)
                    rad = icon_r if k % 2 == 0 else inner
                    poly.append(
                        (
                            icon_cx + rad * math.cos(ang),
                            cy + rad * math.sin(ang),
                        )
                    )
                od.polygon(
                    poly,
                    fill=(120, 120, 120, 255),
                    outline=(0, 0, 0, 255),
                    width=1,
                )

            text_x = icon_cx + icon_r + 10 * s

            bbox = od.textbbox((0, 0), text, font=label_font)

            od.text(
                (
                    text_x,
                    cy - (bbox[3] - bbox[1]) / 2.0 - bbox[1],
                ),
                text,
                fill=(0, 0, 0, 255),
                font=label_font,
            )

        rgba = image.convert("RGBA")

        rgba.alpha_composite(overlay, (int(legend_x), int(legend_y)))

        return rgba.convert("RGB")


# ----------------------------------------------------------------------
# Application entry point
# ----------------------------------------------------------------------

def parse_args(argv=None):
    """
    Parse command-line options.

    The only current option is offline mode (-o / --offline), which
    starts the GUI without ever attempting to connect to the external
    pulse generator (Melt is disabled, all parameter fields remain
    editable for marking images).
    """

    parser = argparse.ArgumentParser(
        prog="usmark_gui",
        description=(
            "USMELT + Image Marker. Combine image marking with "
            "pulse-generator control."
        ),
    )

    parser.add_argument(
        "-o",
        "--offline",
        action="store_true",
        help=(
            "Run without connecting to the external pulse "
            "generator. The Melt button is disabled, but images "
            "can still be marked and exported."
        ),
    )

    # Qt occasionally leaves extra args in sys.argv; ignore unknown
    # options instead of erroring out on them.
    args, _unknown = parser.parse_known_args(argv)

    return args


def main():
    args = parse_args()

    # Make the flag available module-wide so any component created
    # later (e.g. MelterPanel via its default) picks it up too.
    global OFFLINE_MODE

    OFFLINE_MODE = args.offline

    if OFFLINE_MODE:
        print(
            "Offline mode: no attempt will be made to connect "
            "to the pulse generator."
        )

    # QApplication takes a *clean* argv (no our flags), otherwise
    # Qt may choke on the unrecognized -o/--offline arguments.
    app = QApplication(
        [sys.argv[0]]
    )

    window = ImageMarkerApp(
        offline=OFFLINE_MODE
    )

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()