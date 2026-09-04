import os
import tempfile
import traceback

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QPushButton, QToolButton, QLabel, QFileDialog, QTableWidget,
    QTableWidgetItem, QComboBox, QMessageBox, QLineEdit,
    QAbstractItemView, QCheckBox, QGroupBox, QFormLayout, QApplication,
    QInputDialog,
)

from qgis.gui import QgsProjectionSelectionWidget
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsRasterLayer, QgsProject,
)

from .image_canvas import PointPickCanvas
from . import qt_compat as C

try:
    from osgeo import gdal
    gdal.UseExceptions()
    HAS_GDAL = True
except ImportError:
    HAS_GDAL = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# GDAL color-interpretation constants (values are stable across GDAL
# versions; getattr fallback covers older bindings that may not expose
# the names directly).
GCI_PALETTE = getattr(gdal, "GCI_PaletteIndex", 2) if HAS_GDAL else 2
GCI_CYAN = getattr(gdal, "GCI_CyanBand", 10) if HAS_GDAL else 10
GCI_MAGENTA = getattr(gdal, "GCI_MagentaBand", 11) if HAS_GDAL else 11
GCI_YELLOW = getattr(gdal, "GCI_YellowBand", 12) if HAS_GDAL else 12
GCI_BLACK = getattr(gdal, "GCI_BlackBand", 13) if HAS_GDAL else 13


# (label, gdal_key, minimum_required_points)
TRANSFORM_OPTIONS = [
    ("Linear (1st order polynomial)", "poly1", 3),
    ("Polynomial (2nd order)", "poly2", 6),
    ("Polynomial (3rd order)", "poly3", 10),
    ("Thin Plate Spline (TPS)", "tps", 3),
]

RESAMPLE_OPTIONS = [
    ("Nearest Neighbour", "near"),
    ("Bilinear", "bilinear"),
    ("Cubic", "cubic"),
]

PREVIEW_MAX_SIZE = 2200  # long edge (px) of the preview shown on screen


class GeoreferencerDialog(QDialog):
    def __init__(self, parent=None, iface=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Raster Georeferencer (GCP)")
        self.resize(1150, 720)

        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.raster_path = None
        self.preview_path = None
        self.preview_scale = 1.0  # source_pixel = preview_pixel * preview_scale
        # each point: {"px":..,"py":.. (original raster pixel), "mx":..,"my":.., "enabled":True}
        self.points = []
        # set when the source raster was picked via "From Loaded Layer...";
        # on success this existing layer is replaced instead of adding a duplicate
        self.source_layer_id = None
        self.source_layer_name = None

        self._build_ui()
        self._connect_signals()

        if not HAS_GDAL:
            QMessageBox.warning(
                self, "GDAL not found",
                "The osgeo.gdal module could not be imported. This plugin "
                "requires GDAL; please check your QGIS Python environment."
            )

    # ============================================================ UI ====
    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.btn_open_raster = QPushButton("Open Raster...")
        self.btn_open_loaded = QPushButton("From Loaded Layer...")
        self.lbl_raster_path = QLabel("No raster selected yet.")
        self.lbl_raster_path.setStyleSheet("color: gray;")
        top_row.addWidget(self.btn_open_raster)
        top_row.addWidget(self.btn_open_loaded)
        top_row.addWidget(self.lbl_raster_path, 1)
        main_layout.addLayout(top_row)

        splitter = QSplitter(C.ORIENT_HORIZONTAL)

        # ---- Left side: canvas ----
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        canvas_toolbar = QHBoxLayout()
        self.btn_pick_mode = QToolButton()
        self.btn_pick_mode.setText("Add Point")
        self.btn_pick_mode.setCheckable(True)
        self.btn_fit = QToolButton()
        self.btn_fit.setText("Fit to View")
        canvas_toolbar.addWidget(self.btn_pick_mode)
        canvas_toolbar.addWidget(self.btn_fit)
        canvas_toolbar.addStretch(1)
        left_layout.addLayout(canvas_toolbar)

        self.canvas = PointPickCanvas()
        left_layout.addWidget(self.canvas, 1)
        splitter.addWidget(left_widget)

        # ---- Right side: table + settings ----
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["#", "Pixel X", "Pixel Y", "X (Map)", "Y (Map)", "Enabled"]
        )
        self.table.horizontalHeader().setSectionResizeMode(C.HEADER_STRETCH)
        self.table.setSelectionBehavior(C.SELECT_ROWS)
        right_layout.addWidget(self.table, 1)

        row_btns = QHBoxLayout()
        self.btn_delete_point = QPushButton("Delete Selected Point")
        row_btns.addWidget(self.btn_delete_point)
        right_layout.addLayout(row_btns)

        settings_box = QGroupBox("Georeferencing Settings")
        form = QFormLayout(settings_box)

        self.crs_selector = QgsProjectionSelectionWidget()
        self.crs_selector.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        form.addRow("Target CRS:", self.crs_selector)

        self.combo_transform = QComboBox()
        for label, _key, _min_pts in TRANSFORM_OPTIONS:
            self.combo_transform.addItem(label)
        form.addRow("Transformation Type:", self.combo_transform)

        self.combo_resample = QComboBox()
        for label, _key in RESAMPLE_OPTIONS:
            self.combo_resample.addItem(label)
        form.addRow("Resampling Method:", self.combo_resample)

        out_row = QHBoxLayout()
        out_row.setContentsMargins(0, 0, 0, 0)
        self.edit_output = QLineEdit()
        self.btn_browse_output = QPushButton("...")
        self.btn_browse_output.setMaximumWidth(30)
        out_row.addWidget(self.edit_output)
        out_row.addWidget(self.btn_browse_output)
        out_wrap = QWidget()
        out_wrap.setLayout(out_row)
        form.addRow("Output File:", out_wrap)

        self.chk_add_to_map = QCheckBox("Add result to QGIS as a layer")
        self.chk_add_to_map.setChecked(True)
        form.addRow("", self.chk_add_to_map)

        right_layout.addWidget(settings_box)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        right_layout.addWidget(self.lbl_status)

        self.btn_run = QPushButton("Run Georeferencing")
        right_layout.addWidget(self.btn_run)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, 1)

    def _connect_signals(self):
        self.btn_open_raster.clicked.connect(self.open_raster)
        self.btn_open_loaded.clicked.connect(self.open_from_loaded_layer)
        self.btn_pick_mode.toggled.connect(self.canvas.set_pick_mode)
        self.btn_fit.clicked.connect(self.canvas.fit_to_view)
        self.canvas.pointAdded.connect(self.on_point_added)
        self.btn_delete_point.clicked.connect(self.delete_selected_point)
        self.table.itemChanged.connect(self.on_table_item_changed)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.btn_browse_output.clicked.connect(self.browse_output)
        self.btn_run.clicked.connect(self.run_georeference)

    # ================================================= Opening a raster ====
    def open_raster(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select Raster File", "",
            "Raster Files (*.tif *.tiff *.jpg *.jpeg *.png *.img *.bmp);;All Files (*.*)"
        )
        if not path:
            return
        self.source_layer_id = None
        self._update_add_to_map_ui()
        self._open_path(path)

    def open_from_loaded_layer(self):
        candidates = self._get_loaded_raster_layers()
        if not candidates:
            QMessageBox.information(
                self, "Info",
                "No file-based (GDAL) raster layers are currently loaded in QGIS."
            )
            return

        names = [lyr.name() for lyr in candidates]
        name, ok = QInputDialog.getItem(
            self, "Select Raster Layer",
            "Choose a raster layer currently loaded in QGIS:",
            names, 0, False
        )
        if not ok or not name:
            return

        layer = candidates[names.index(name)]
        self.source_layer_id = layer.id()
        self.source_layer_name = layer.name()
        self._update_add_to_map_ui()
        self._open_path(layer.source())

    def _update_add_to_map_ui(self):
        if self.source_layer_id is not None:
            self.chk_add_to_map.setChecked(True)
            self.chk_add_to_map.setEnabled(False)
            self.chk_add_to_map.setText(
                "Will replace existing layer \"%s\" (old coordinates discarded)" % self.source_layer_name
            )
        else:
            self.chk_add_to_map.setEnabled(True)
            self.chk_add_to_map.setText("Add result to QGIS as a layer")

    @staticmethod
    def _get_loaded_raster_layers():
        """Returns loaded raster layers backed by a real file/GDAL dataset
        (excludes WMS/WMTS/XYZ and other non-file providers, which GDAL
        cannot reopen directly by path)."""
        layers = []
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsRasterLayer) and lyr.isValid() and lyr.providerType() == "gdal":
                layers.append(lyr)
        return layers

    def _open_path(self, path):
        if not HAS_GDAL:
            QMessageBox.critical(self, "Error", "GDAL (osgeo) module not found.")
            return
        self.lbl_status.setText("Loading raster and building preview...")
        QApplication.setOverrideCursor(C.CURSOR_WAIT)
        QApplication.processEvents()
        try:
            self._load_raster(path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Error", "Could not open raster:\n%s" % exc)
        finally:
            QApplication.restoreOverrideCursor()

    @staticmethod
    def _is_palette(ds):
        """Detects paletted/indexed rasters (PhotometricInterpretation
        'Palette'), where pixel values are color-table indices rather
        than direct intensities."""
        band = ds.GetRasterBand(1)
        return band.GetColorInterpretation() == GCI_PALETTE and band.GetColorTable() is not None

    @staticmethod
    def _is_cmyk(ds):
        """Detects CMYK-separated TIFFs (Adobe 'Separated' photometric),
        which GDAL exposes as four bands with Cyan/Magenta/Yellow/Black
        color interpretation instead of RGB."""
        if ds.RasterCount < 4:
            return False
        interps = {ds.GetRasterBand(i + 1).GetColorInterpretation() for i in range(ds.RasterCount)}
        return {GCI_CYAN, GCI_MAGENTA, GCI_YELLOW, GCI_BLACK}.issubset(interps)

    def _write_cmyk_preview(self, ds, target_w, target_h):
        """Reads a downsampled CMYK array and converts it to RGB before
        saving the preview, instead of writing the raw C/M/Y/K channels
        straight to PNG (which produces a negative-looking image)."""
        band_index = {}
        for i in range(ds.RasterCount):
            ci = ds.GetRasterBand(i + 1).GetColorInterpretation()
            if ci == GCI_CYAN:
                band_index["c"] = i
            elif ci == GCI_MAGENTA:
                band_index["m"] = i
            elif ci == GCI_YELLOW:
                band_index["y"] = i
            elif ci == GCI_BLACK:
                band_index["k"] = i

        arr = ds.ReadAsArray(buf_xsize=target_w, buf_ysize=target_h).astype("float32")

        band_dtype = ds.GetRasterBand(1).DataType
        max_val = 255.0
        if band_dtype != gdal.GDT_Byte:
            max_val = float((2 ** gdal.GetDataTypeSize(band_dtype)) - 1)

        c = arr[band_index["c"]] / max_val
        m = arr[band_index["m"]] / max_val
        y = arr[band_index["y"]] / max_val
        k = arr[band_index["k"]] / max_val

        r = 255.0 * (1.0 - c) * (1.0 - k)
        g = 255.0 * (1.0 - m) * (1.0 - k)
        b = 255.0 * (1.0 - y) * (1.0 - k)

        rgb = np.clip(np.stack([r, g, b], axis=0), 0, 255).astype("uint8")

        mem_ds = gdal.GetDriverByName("MEM").Create("", target_w, target_h, 3, gdal.GDT_Byte)
        for band_i in range(3):
            mem_ds.GetRasterBand(band_i + 1).WriteArray(rgb[band_i])

        gdal.GetDriverByName("PNG").CreateCopy(self.preview_path, mem_ds)
        mem_ds = None

    def _load_raster(self, path):
        ds = gdal.Open(path)
        if ds is None:
            raise RuntimeError("GDAL could not read this file.")

        width = ds.RasterXSize
        height = ds.RasterYSize

        self.raster_path = path
        self.points = []
        self.table.setRowCount(0)
        self.canvas.clear_markers()

        preview_dir = tempfile.mkdtemp(prefix="georef_preview_")
        self.preview_path = os.path.join(preview_dir, "preview.png")

        long_edge = max(width, height)
        if long_edge > PREVIEW_MAX_SIZE:
            self.preview_scale = long_edge / float(PREVIEW_MAX_SIZE)
            target_w = max(1, int(round(width / self.preview_scale)))
            target_h = max(1, int(round(height / self.preview_scale)))
        else:
            self.preview_scale = 1.0
            target_w, target_h = width, height

        if self._is_cmyk(ds) and HAS_NUMPY:
            # CMYK-encoded TIFFs (common for scanned/print-origin maps) look
            # inverted/negative if their four raw channels are written to a
            # PNG as if they were plain RGB(A) - convert to RGB properly.
            self._write_cmyk_preview(ds, target_w, target_h)
        else:
            translate_kwargs = dict(format="PNG")
            if long_edge > PREVIEW_MAX_SIZE:
                translate_kwargs.update(width=target_w, height=target_h, resampleAlg="average")

            if self._is_palette(ds):
                # Paletted/indexed rasters (common for scanned topo maps
                # such as USGS DRGs) store a per-pixel color-table index,
                # not a raw intensity. Stretching those index values with
                # scaleParams (as done below for normal imagery) ignores
                # the color table and produces wrong/negative-looking
                # colors - expand through the color table to RGB instead.
                translate_kwargs["rgbExpand"] = "rgb"
            else:
                translate_kwargs["scaleParams"] = [[]]
                translate_kwargs["outputType"] = gdal.GDT_Byte

            translate_opts = gdal.TranslateOptions(**translate_kwargs)
            gdal.Translate(self.preview_path, ds, options=translate_opts)

        ds = None

        self.canvas.load_preview(self.preview_path)
        self.lbl_raster_path.setText(path)
        self.lbl_raster_path.setStyleSheet("")

        base, _ext = os.path.splitext(path)
        self.edit_output.setText(base + "_georef.tif")

        self.lbl_status.setText("Raster loaded: %d x %d px." % (width, height))

    # ======================================================== Points ====
    def on_point_added(self, scene_x, scene_y):
        px = scene_x * self.preview_scale
        py = scene_y * self.preview_scale
        index = len(self.points)
        self.points.append({"px": px, "py": py, "mx": None, "my": None, "enabled": True})
        self.canvas.add_marker(index, scene_x, scene_y)
        self._add_table_row(index, px, py)
        self.table.selectRow(index)

    def _add_table_row(self, index, px, py):
        row = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(row)

        item_no = QTableWidgetItem(str(index + 1))
        item_no.setFlags(C.ITEM_IS_ENABLED | C.ITEM_IS_SELECTABLE)
        self.table.setItem(row, 0, item_no)

        item_px = QTableWidgetItem("%.2f" % px)
        item_px.setFlags(C.ITEM_IS_ENABLED | C.ITEM_IS_SELECTABLE)
        self.table.setItem(row, 1, item_px)

        item_py = QTableWidgetItem("%.2f" % py)
        item_py.setFlags(C.ITEM_IS_ENABLED | C.ITEM_IS_SELECTABLE)
        self.table.setItem(row, 2, item_py)

        self.table.setItem(row, 3, QTableWidgetItem(""))
        self.table.setItem(row, 4, QTableWidgetItem(""))

        item_chk = QTableWidgetItem()
        item_chk.setFlags(C.ITEM_IS_ENABLED | C.ITEM_IS_SELECTABLE | C.ITEM_IS_USER_CHECKABLE)
        item_chk.setCheckState(C.CHECK_CHECKED)
        self.table.setItem(row, 5, item_chk)

        self.table.blockSignals(False)

    def on_table_item_changed(self, item):
        row = item.row()
        col = item.column()
        if row >= len(self.points):
            return
        if col == 3:
            self.points[row]["mx"] = self._parse_float(item.text())
        elif col == 4:
            self.points[row]["my"] = self._parse_float(item.text())
        elif col == 5:
            self.points[row]["enabled"] = (item.checkState() == C.CHECK_CHECKED)

    @staticmethod
    def _parse_float(text):
        text = text.strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def on_table_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.canvas.highlight_marker(rows[0].row())

    def delete_selected_point(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "Info", "Select a point to delete.")
            return
        for row in rows:
            self.canvas.remove_marker(row)
            del self.points[row]
            self.table.removeRow(row)
        self._renumber()

    def _renumber(self):
        self.canvas.clear_markers()
        self.table.blockSignals(True)
        for i, pt in enumerate(self.points):
            self.table.item(i, 0).setText(str(i + 1))
            self.canvas.add_marker(
                i, pt["px"] / self.preview_scale, pt["py"] / self.preview_scale, label=i + 1
            )
        self.table.blockSignals(False)

    # ========================================================= Output ====
    def browse_output(self):
        path, _filter = QFileDialog.getSaveFileName(
            self, "Select Output Raster", self.edit_output.text() or "",
            "GeoTIFF (*.tif)"
        )
        if path:
            if not path.lower().endswith(".tif"):
                path += ".tif"
            self.edit_output.setText(path)

    # =============================================== Georeferencing ====
    def run_georeference(self):
        if not HAS_GDAL:
            QMessageBox.critical(self, "Error", "GDAL (osgeo) module not found.")
            return
        if not self.raster_path:
            QMessageBox.warning(self, "Warning", "Open a raster file first.")
            return

        bad_rows = [
            i + 1 for i, p in enumerate(self.points)
            if p["enabled"] and (p["mx"] is None or p["my"] is None)
        ]
        if bad_rows:
            QMessageBox.warning(
                self, "Warning",
                "The following point(s) are missing or have an invalid X/Y coordinate: "
                + ", ".join(str(r) for r in bad_rows)
            )
            return

        _label, transform_key, min_points = TRANSFORM_OPTIONS[self.combo_transform.currentIndex()]
        valid_points = [
            p for p in self.points
            if p["enabled"] and p["mx"] is not None and p["my"] is not None
        ]

        if len(valid_points) < min_points:
            QMessageBox.warning(
                self, "Warning",
                "The selected transformation type requires at least %d control points "
                "(currently %d enabled/valid points)." % (min_points, len(valid_points))
            )
            return

        output_path = self.edit_output.text().strip()
        if not output_path:
            QMessageBox.warning(self, "Warning", "Specify an output file.")
            return

        crs = self.crs_selector.crs()
        if not crs.isValid():
            QMessageBox.warning(self, "Warning", "Select a valid target CRS.")
            return

        resample_key = RESAMPLE_OPTIONS[self.combo_resample.currentIndex()][1]

        self.btn_run.setEnabled(False)
        self.lbl_status.setText("Running georeferencing...")
        QApplication.setOverrideCursor(C.CURSOR_WAIT)
        QApplication.processEvents()
        try:
            self._do_warp(valid_points, crs.toWkt(), transform_key, resample_key, output_path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Error", "Georeferencing failed:\n%s" % exc)
            self.lbl_status.setText("Operation failed.")
            self.btn_run.setEnabled(True)
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.btn_run.setEnabled(True)
        self.lbl_status.setText("Done: %s" % output_path)

        if self.source_layer_id is not None and self.iface is not None:
            self._replace_source_layer(output_path)
        else:
            QMessageBox.information(self, "Done", "Raster was georeferenced successfully.")
            if self.chk_add_to_map.isChecked() and self.iface is not None:
                layer_name = os.path.splitext(os.path.basename(output_path))[0]
                layer = QgsRasterLayer(output_path, layer_name)
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                else:
                    QMessageBox.warning(self, "Warning", "Layer was created but could not be added to QGIS.")

    def _replace_source_layer(self, output_path):
        """Removes the original loaded layer this raster came from and adds
        the freshly georeferenced result in its place, so the old
        coordinate information is fully discarded instead of ending up
        with two layers on the map."""
        project = QgsProject.instance()
        layer_name = self.source_layer_name or os.path.splitext(os.path.basename(output_path))[0]

        old_layer = project.mapLayer(self.source_layer_id)
        if old_layer is not None:
            project.removeMapLayer(self.source_layer_id)

        new_layer = QgsRasterLayer(output_path, layer_name)
        if new_layer.isValid():
            project.addMapLayer(new_layer)
            QMessageBox.information(
                self, "Done",
                "Raster was georeferenced successfully. The old layer's "
                "coordinates were replaced with the new ones."
            )
        else:
            QMessageBox.warning(
                self, "Warning",
                "Georeferencing succeeded but the updated layer could not "
                "be reloaded into QGIS. The output file is available at:\n%s" % output_path
            )

        # This dialog's raster source no longer matches a layer in the
        # project (it was just replaced); treat the next run as a fresh file.
        self.source_layer_id = None
        self.source_layer_name = None
        self._update_add_to_map_ui()

    def _do_warp(self, points, dst_wkt, transform_key, resample_key, output_path):
        gcps = [gdal.GCP(p["mx"], p["my"], 0, p["px"], p["py"]) for p in points]

        src_ds = gdal.Open(self.raster_path)
        if src_ds is None:
            raise RuntimeError("Could not reopen the source raster.")

        # If the requested output path is the same file we are reading from
        # (e.g. re-georeferencing a loaded layer in place), write to a
        # temporary file first and swap it in at the end - writing directly
        # over a file that is also the read source would corrupt it.
        overwrite_in_place = os.path.abspath(output_path) == os.path.abspath(self.raster_path)
        final_output_path = output_path
        if overwrite_in_place:
            tmp_out_dir = tempfile.mkdtemp(prefix="georef_out_")
            final_output_path = os.path.join(tmp_out_dir, os.path.basename(output_path))

        # Building the intermediate VRT with new GCPs discards any
        # pre-existing geotransform/GCPs from the source - a GDAL dataset
        # can only have one or the other, never both - so old coordinate
        # information cannot leak into the result.
        tmp_vrt = os.path.join(tempfile.mkdtemp(prefix="georef_vrt_"), "with_gcps.vrt")
        translate_opts = gdal.TranslateOptions(format="VRT", GCPs=gcps, outputSRS=dst_wkt)
        gdal.Translate(tmp_vrt, src_ds, options=translate_opts)
        src_ds = None

        warp_kwargs = dict(
            dstSRS=dst_wkt,
            resampleAlg=resample_key,
            multithread=True,
        )
        if transform_key == "tps":
            warp_kwargs["tps"] = True
        else:
            order = {"poly1": 1, "poly2": 2, "poly3": 3}[transform_key]
            warp_kwargs["polynomialOrder"] = order

        warp_opts = gdal.WarpOptions(**warp_kwargs)
        result = gdal.Warp(final_output_path, tmp_vrt, options=warp_opts)
        if result is None:
            raise RuntimeError("GDAL Warp produced no result.")
        result = None

        if overwrite_in_place:
            os.replace(final_output_path, output_path)
