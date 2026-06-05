from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class Magnifier(QWidget):
    """A floating loupe that shows a zoomed crop of the source image around the
    cursor, with a crosshair marking the exact point under the cursor."""

    def __init__(self, parent: QWidget | None = None, size: int = 170, zoom: float = 5.0) -> None:
        super().__init__(parent)
        self._zoom = zoom
        self._src: QPixmap | None = None
        self._pt: QPointF | None = None
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def set_source(self, pixmap: QPixmap | None) -> None:
        self._src = pixmap

    def set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        self.update()

    def update_point(self, scene_pt: QPointF | None) -> None:
        self._pt = scene_pt
        if scene_pt is None:
            self.hide()
        else:
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(25, 25, 25))
        if self._src is not None and self._pt is not None:
            side = self.width() / self._zoom
            src_rect = QRectF(self._pt.x() - side / 2, self._pt.y() - side / 2, side, side)
            painter.drawPixmap(QRectF(0, 0, self.width(), self.height()), self._src, src_rect)
            cx = self.width() / 2.0
            cy = self.height() / 2.0
            painter.setPen(QPen(QColor(255, 0, 0), 1))
            painter.drawLine(int(cx - 12), int(cy), int(cx + 12), int(cy))
            painter.drawLine(int(cx), int(cy - 12), int(cx), int(cy + 12))
        painter.setPen(QPen(QColor(210, 210, 210), 1))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
