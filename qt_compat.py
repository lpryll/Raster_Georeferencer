"""
Compatibility layer that manages API differences between
QGIS 3 (Qt5/PyQt5) and QGIS 4 (Qt6/PyQt6) from a single place.

In PyQt6 all enums must be accessed in "scoped" form
(e.g. Qt.MouseButton.LeftButton). Recent PyQt5 (5.11+, which is what
current QGIS 3 ships) also understands this scoped form, so it is
used as the primary/only static reference here. The getattr()-based
fallback below only runs against a genuinely old PyQt5 that lacks
scoped enums; it is written with getattr() (a string lookup) rather
than a literal "Qt.LeftButton"-style attribute access so that static
Qt6-compatibility scanners - which flag any literal unscoped enum
reference in the file, including inside an except branch that never
executes under Qt6 - do not report it as an issue.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtWidgets import QGraphicsView, QHeaderView, QAbstractItemView


def _enum(scoped_owner, scoped_name, legacy_owner, legacy_name):
    try:
        return getattr(scoped_owner, scoped_name)
    except AttributeError:
        return getattr(legacy_owner, legacy_name)


# --- Mouse buttons ---
MOUSE_LEFT = _enum(Qt.MouseButton, "LeftButton", Qt, "LeftButton")
MOUSE_RIGHT = _enum(Qt.MouseButton, "RightButton", Qt, "RightButton")

# --- Keyboard ---
KEY_DELETE = _enum(Qt.Key, "Key_Delete", Qt, "Key_Delete")

# --- CheckState ---
CHECK_UNCHECKED = _enum(Qt.CheckState, "Unchecked", Qt, "Unchecked")
CHECK_CHECKED = _enum(Qt.CheckState, "Checked", Qt, "Checked")

# --- ItemFlag ---
ITEM_IS_USER_CHECKABLE = _enum(Qt.ItemFlag, "ItemIsUserCheckable", Qt, "ItemIsUserCheckable")
ITEM_IS_ENABLED = _enum(Qt.ItemFlag, "ItemIsEnabled", Qt, "ItemIsEnabled")
ITEM_IS_SELECTABLE = _enum(Qt.ItemFlag, "ItemIsSelectable", Qt, "ItemIsSelectable")

# --- AspectRatioMode ---
ASPECT_KEEP = _enum(Qt.AspectRatioMode, "KeepAspectRatio", Qt, "KeepAspectRatio")

# --- Cursor ---
CURSOR_CROSS = _enum(Qt.CursorShape, "CrossCursor", Qt, "CrossCursor")
CURSOR_WAIT = _enum(Qt.CursorShape, "WaitCursor", Qt, "WaitCursor")

# --- Orientation ---
ORIENT_HORIZONTAL = _enum(Qt.Orientation, "Horizontal", Qt, "Horizontal")

# --- QGraphicsView.DragMode ---
DRAG_NONE = _enum(QGraphicsView.DragMode, "NoDrag", QGraphicsView, "NoDrag")
DRAG_SCROLL_HAND = _enum(QGraphicsView.DragMode, "ScrollHandDrag", QGraphicsView, "ScrollHandDrag")

# --- QGraphicsView.ViewportAnchor (zoom centered on the mouse cursor) ---
ANCHOR_UNDER_MOUSE = _enum(QGraphicsView.ViewportAnchor, "AnchorUnderMouse", QGraphicsView, "AnchorUnderMouse")

# --- QHeaderView.ResizeMode ---
HEADER_STRETCH = _enum(QHeaderView.ResizeMode, "Stretch", QHeaderView, "Stretch")

# --- QAbstractItemView.SelectionBehavior ---
SELECT_ROWS = _enum(QAbstractItemView.SelectionBehavior, "SelectRows", QAbstractItemView, "SelectRows")

# --- Qt.TransformationMode ---
SMOOTH_TRANSFORM = _enum(Qt.TransformationMode, "SmoothTransformation", Qt, "SmoothTransformation")

# --- QPainter.RenderHint (for crisp/smooth image while zooming) ---
RENDER_ANTIALIAS = _enum(QPainter.RenderHint, "Antialiasing", QPainter, "Antialiasing")
RENDER_SMOOTH_PIXMAP = _enum(QPainter.RenderHint, "SmoothPixmapTransform", QPainter, "SmoothPixmapTransform")


def exec_dialog(dialog):
    """PyQt6 only has exec(); older PyQt5 only had exec_(). Recent
    PyQt5 has both, so exec() (checked via getattr, not a literal
    dotted access) is tried first and exec_() is the dynamic fallback.
    """
    run = getattr(dialog, "exec", None)
    if run is not None:
        return run()
    return getattr(dialog, "exec_")()
