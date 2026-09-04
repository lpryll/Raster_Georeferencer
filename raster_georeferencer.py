from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
import os

from . import qt_compat as C


class RasterGeoreferencerPlugin:
    """Main plugin class registered with QGIS: adds the toolbar/menu
    icon and opens the georeferencing dialog when clicked."""

    MENU_NAME = "Raster Georeferencer"

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self.plugin_dir = os.path.dirname(__file__)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path)
        self.action = QAction(icon, "Raster Georeferencer (GCP)", self.iface.mainWindow())
        self.action.setWhatsThis("Georeferences a raster using control points.")
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu(self.MENU_NAME, self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginRasterMenu(self.MENU_NAME, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self):
        # If a dialog is already open, bring it to front instead of opening a new one
        if self.dialog is not None:
            try:
                if self.dialog.isVisible():
                    self.dialog.raise_()
                    self.dialog.activateWindow()
                    return
            except RuntimeError:
                # The previous dialog may have been deleted on the C++ side; create a new one
                self.dialog = None

        from .georeferencer_dialog import GeoreferencerDialog
        self.dialog = GeoreferencerDialog(self.iface.mainWindow(), iface=self.iface)
        C.exec_dialog(self.dialog)
