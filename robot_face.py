import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QRadialGradient, QLinearGradient
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
import math
import random


class RobotFaceWidget(QWidget):

    def __init__(self):
        super().__init__()
        self.setMinimumSize(260, 260)

        # State: "idle" | "listening" | "thinking" | "speaking"
        self.state = "idle"

        # --- Mouth animation ---
        self.mouth_open      = 0
        self.mouth_direction = 1

        # --- Blink ---
        self.blink_progress  = 0.0   # 0 = fully open, 1 = fully closed
        self.is_blinking     = False

        # --- Thinking dots ---
        self.think_dot       = 0     # 0‥2, which dot is "lit"
        self.think_tick      = 0

        # --- Listening pulse ---
        self.pulse_radius    = 0.0
        self.pulse_direction = 1

        # --- Idle subtle glow breathe ---
        self.breathe         = 0.0
        self.breathe_dir     = 1

        # --- Scanline offset for CRT effect ---
        self.scan_offset     = 0

        # Main animation timer (60 fps feel at 16ms)
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._animate)
        self.anim_timer.start(16)

        # Random blink timer
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._trigger_blink)
        self.blink_timer.start(random.randint(2500, 4500))

    # ------------------------------------------------------------------
    # PUBLIC
    # ------------------------------------------------------------------

    def set_state(self, new_state: str):
        self.state = new_state
        self.update()

    # ------------------------------------------------------------------
    # TIMERS
    # ------------------------------------------------------------------

    def _trigger_blink(self):
        if not self.is_blinking:
            self.is_blinking    = True
            self.blink_progress = 0.0
        self.blink_timer.setInterval(random.randint(2500, 5000))

    def _animate(self):

        changed = False

        # Mouth bounce when speaking
        if self.state == "speaking":
            self.mouth_open += 1.8 * self.mouth_direction
            if self.mouth_open >= 18:
                self.mouth_direction = -1
            elif self.mouth_open <= 1:
                self.mouth_direction = 1
            changed = True
        else:
            if self.mouth_open > 0:
                self.mouth_open = max(0, self.mouth_open - 2)
                changed = True

        # Thinking dots
        if self.state == "thinking":
            self.think_tick += 1
            if self.think_tick >= 18:
                self.think_tick  = 0
                self.think_dot   = (self.think_dot + 1) % 3
            changed = True

        # Listening pulse ring
        if self.state == "listening":
            self.pulse_radius += 0.8 * self.pulse_direction
            if self.pulse_radius >= 22:
                self.pulse_direction = -1
            elif self.pulse_radius <= 0:
                self.pulse_direction = 1
            changed = True

        # Idle breathe glow
        self.breathe += 0.015 * self.breathe_dir
        if self.breathe >= 1.0:
            self.breathe_dir = -1
        elif self.breathe <= 0.0:
            self.breathe_dir = 1
        changed = True

        # Blink animation
        if self.is_blinking:
            self.blink_progress += 0.15
            if self.blink_progress >= 2.0:
                self.blink_progress = 0.0
                self.is_blinking    = False
            changed = True

        # Scanlines slow scroll
        self.scan_offset = (self.scan_offset + 1) % 6
        changed = True

        if changed:
            self.update()

    # ------------------------------------------------------------------
    # PAINT
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        W  = self.width()
        H  = self.height()
        cx = W // 2
        cy = H // 2

        # ── Background panel ──────────────────────────────────────────
        panel_rect = QRectF(8, 8, W - 16, H - 16)

        # Dark gradient background
        bg_grad = QLinearGradient(0, 0, 0, H)
        bg_grad.setColorAt(0, QColor("#1a1a2e"))
        bg_grad.setColorAt(1, QColor("#0d0d1a"))
        painter.setBrush(QBrush(bg_grad))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(panel_rect, 18, 18)

        # Neon border glow (color changes by state)
        border_color = self._state_color()
        glow_alpha   = int(120 + 80 * self.breathe)
        border_color.setAlpha(glow_alpha)

        pen = QPen(border_color)
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(panel_rect, 18, 18)

        # Subtle inner border
        inner_color = QColor(border_color)
        inner_color.setAlpha(40)
        painter.setPen(QPen(inner_color, 1))
        painter.drawRoundedRect(QRectF(12, 12, W - 24, H - 24), 15, 15)

        # ── CRT scanlines ─────────────────────────────────────────────
        painter.setPen(Qt.NoPen)
        scan_color = QColor(0, 0, 0, 18)
        painter.setBrush(QBrush(scan_color))
        y = 8 + (self.scan_offset % 6)
        while y < H - 8:
            painter.drawRect(8, y, W - 16, 2)
            y += 6

        # ── Colors ────────────────────────────────────────────────────
        neon  = self._state_color()
        neon.setAlpha(255)

        # ── Eyes ──────────────────────────────────────────────────────
        eye_y      = cy - 34
        left_eye_x = cx - 44
        rigt_eye_x = cx + 44
        self._draw_eye(painter, left_eye_x, eye_y, neon)
        self._draw_eye(painter, rigt_eye_x, eye_y, neon)

        # ── Listening pulse rings ──────────────────────────────────────
        if self.state == "listening":
            for i, eye_x in enumerate([left_eye_x, rigt_eye_x]):
                r   = int(18 + self.pulse_radius)
                col = QColor(neon)
                col.setAlpha(max(0, 120 - int(self.pulse_radius * 5)))
                pen2 = QPen(col)
                pen2.setWidth(2)
                painter.setPen(pen2)
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(eye_x, eye_y), r, r)

        # ── Thinking dots below eyes ───────────────────────────────────
        if self.state == "thinking":
            dot_y = cy + 4
            for i in range(3):
                dot_x = cx - 20 + i * 20
                if i == self.think_dot:
                    col = QColor(neon)
                    col.setAlpha(255)
                    r = 7
                else:
                    col = QColor(neon)
                    col.setAlpha(70)
                    r = 4
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(col))
                painter.drawEllipse(QPointF(dot_x, dot_y), r, r)

        # ── Mouth ─────────────────────────────────────────────────────
        mouth_y = cy + 44
        self._draw_mouth(painter, cx, mouth_y, neon)

        # ── State label (small) ───────────────────────────────────────
        label_map = {
            "idle":      "",
            "listening": "LISTENING",
            "thinking":  "PROCESSING",
            "speaking":  "SPEAKING",
        }
        label = label_map.get(self.state, "")
        if label:
            label_color = QColor(neon)
            label_color.setAlpha(180)
            painter.setPen(label_color)
            from PyQt5.QtGui import QFont
            painter.setFont(QFont("Courier New", 8, QFont.Bold))
            painter.drawText(QRectF(0, H - 28, W, 20), Qt.AlignCenter, label)

        painter.end()

    # ------------------------------------------------------------------
    # DRAW EYE
    # ------------------------------------------------------------------

    def _draw_eye(self, painter: QPainter, ex: int, ey: int, neon: QColor):

        # Blink: progress 0→1 = closing, 1→2 = opening
        bp = self.blink_progress
        if bp <= 1.0:
            close_frac = bp
        else:
            close_frac = 2.0 - bp
        eye_height = max(2, int(26 * (1.0 - close_frac)))

        # Glow fill inside eye
        glow = QRadialGradient(ex, ey, 16)
        glow_col = QColor(neon)
        glow_col.setAlpha(40)
        glow.setColorAt(0, glow_col)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(glow))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(ex, ey), 16, 16)

        pen = QPen(neon)
        pen.setWidth(3)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if self.state == "thinking":
            # Half-squint arcs
            painter.drawArc(
                int(ex - 14), int(ey - 7), 28, 14,
                0 * 16, 180 * 16
            )
        elif self.state == "listening":
            # Wide alert eyes
            painter.drawEllipse(QPointF(ex, ey), 16, eye_height * 0.7)
        else:
            # Normal round eyes with blink
            painter.drawEllipse(
                QPointF(ex, ey),
                14,
                max(2, eye_height * 0.55)
            )

        # Pupil dot
        if not self.is_blinking or close_frac < 0.6:
            pupil_col = QColor(neon)
            pupil_col.setAlpha(200)
            painter.setBrush(QBrush(pupil_col))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(ex, ey), 4, 4)

    # ------------------------------------------------------------------
    # DRAW MOUTH
    # ------------------------------------------------------------------

    def _draw_mouth(self, painter: QPainter, mx: int, my: int, neon: QColor):

        pen = QPen(neon)
        pen.setWidth(3)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if self.state == "speaking":
            # Animated open oval
            h = max(4, int(self.mouth_open))
            glow_col = QColor(neon)
            glow_col.setAlpha(80)
            painter.setBrush(QBrush(glow_col))
            painter.drawEllipse(QRectF(mx - 22, my - h, 44, h * 2))
            painter.setBrush(Qt.NoBrush)

        elif self.state == "thinking":
            # Slight frown / tight line
            painter.drawLine(mx - 14, my + 3, mx + 14, my + 3)

        elif self.state == "listening":
            # Open smile arc
            painter.drawArc(
                int(mx - 22), int(my - 12), 44, 24,
                200 * 16, 140 * 16
            )

        else:
            # Idle: gentle smile
            painter.drawArc(
                int(mx - 20), int(my - 10), 40, 20,
                210 * 16, 120 * 16
            )

    # ------------------------------------------------------------------
    # STATE → COLOR
    # ------------------------------------------------------------------

    def _state_color(self) -> QColor:
        if self.state == "listening":
            return QColor("#00FF88")   # green
        elif self.state == "thinking":
            return QColor("#FF9500")   # orange
        elif self.state == "speaking":
            return QColor("#00CFFF")   # electric blue
        else:
            # Idle: breathe between teal and cyan
            r = int(0   + 0   * self.breathe)
            g = int(220 + 35  * self.breathe)
            b = int(180 + 75  * self.breathe)
            return QColor(r, g, b)


# ─────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app    = QApplication(sys.argv)
    window = QWidget()
    window.setStyleSheet("background-color: #121212;")
    layout = QVBoxLayout(window)

    face = RobotFaceWidget()
    face.setMinimumSize(320, 320)
    layout.addWidget(face)

    btn_layout = QHBoxLayout()
    for label, state in [("Idle","idle"),("Listen","listening"),
                          ("Think","thinking"),("Speak","speaking")]:
        btn = QPushButton(label)
        btn.setStyleSheet("color:white; background:#222; padding:10px; border:1px solid #444;")
        btn.clicked.connect(lambda _, s=state: face.set_state(s))
        btn_layout.addWidget(btn)

    layout.addLayout(btn_layout)
    window.setWindowTitle("Robot Face Test")
    window.show()
    sys.exit(app.exec_())