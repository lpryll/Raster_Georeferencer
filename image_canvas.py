from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QPixmap, QPen, QBrush, QColor, QFont
from qgis.PyQt.QtWidgets import QGraphicsView, QGraphicsScene

from . import qt_compat as C


class PointPickCanvas(QGraphicsView):
    """View that shows the raster preview and lets the user click on it
    to add points. Pixel <-> screen conversion is handled inside this
    class even though a differently-scaled preview image is used; only
    "scene" (preview) coordinates are exposed to the outside.
    """

    pointAdded = pyqtSignal(float, float)  # preview (scene) coordinates

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setDragMode(C.DRAG_SCROLL_HAND)
        self.setMouseTracking(True)
        self.setRenderHint(C.RENDER_ANTIALIAS, True)
        self.setRenderHint(C.RENDER_SMOOTH_PIXMAP, True)
        self.setTransformationAnchor(C.ANCHOR_UNDER_MOUSE)
        self._pixmap_item = None
        self._markers = {}  # index -> (ellipse_item, text_item)
        self._pick_mode = False
        self._point_radius = 5

    # ------------------------------------------------------------ Loading --
    def load_preview(self, preview_path):
        self._scene.clear()
        self._markers.clear()
        pixmap = QPixmap(preview_path)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._pixmap_item.setTransformationMode(C.SMOOTH_TRANSFORM)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self.fit_to_view()

    def fit_to_view(self):
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, C.ASPECT_KEEP)

    # -------------------------------------------------------- Pick mode --
    def set_pick_mode(self, enabled):
        self._pick_mode = bool(enabled)
        if self._pick_mode:
            self.setDragMode(C.DRAG_NONE)
            self.setCursor(C.CURSOR_CROSS)
        else:
            self.setDragMode(C.DRAG_SCROLL_HAND)
            self.unsetCursor()

    def mousePressEvent(self, event):
        if self._pick_mode and event.button() == C.MOUSE_LEFT and self._pixmap_item is not None:
            scene_pos = self.mapToScene(event.pos())
            if self._pixmap_item.boundingRect().contains(scene_pos):
                self.pointAdded.emit(scene_pos.x(), scene_pos.y())
                return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    # ------------------------------------------------------------- Marker --
    def add_marker(self, index, x, y, label=None):
        r = self._point_radius
        ellipse = self._scene.addEllipse(
            x - r, y - r, r * 2, r * 2,
            QPen(QColor(255, 0, 0), 2),
            QBrush(QColor(255, 0, 0, 90)),
        )
        ellipse.setZValue(10)

        text = self._scene.addSimpleText(str(label if label is not None else index + 1))
        text.setBrush(QBrush(QColor(255, 255, 0)))
        font = QFont()
        font.setBold(True)
        text.setFont(font)
        text.setZValue(11)
        text.setPos(x + r, y - r - 14)

        self._markers[index] = (ellipse, text)

    def remove_marker(self, index):
        pair = self._markers.pop(index, None)
        if pair:
            self._scene.removeItem(pair[0])
            self._scene.removeItem(pair[1])

    def clear_markers(self):
        for idx in list(self._markers.keys()):
            self.remove_marker(idx)

    def highlight_marker(self, index):
        for i, (ellipse, _text) in self._markers.items():
            ellipse.setPen(QPen(QColor(0, 200, 0) if i == index else QColor(255, 0, 0), 2))
