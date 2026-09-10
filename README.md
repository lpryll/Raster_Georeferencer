# Raster Georeferencer (GCP)

A ground-control-point (GCP) based raster georeferencing plugin,
compatible with both QGIS 3 (Qt5/PyQt5) and QGIS 4 (Qt6/PyQt6).

## Installation
1. Copy this folder (`raster_georeferencer`) as-is into your QGIS
   plugins folder, or simply use **Install from ZIP** in the Plugin
   Manager:
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
     (on QGIS 4 the profile path follows the same pattern, typically
     under a `QGIS4` folder — check Settings > User Profiles for the
     exact path)
2. Restart QGIS and enable "Raster Georeferencer (GCP)" in the
   Plugin Manager.
3. Click the icon that appears on the toolbar, or use
   Raster menu > Raster Georeferencer.
4. Click **Help** inside the plugin window at any time to open the
   full user guide (`docs/user_guide.html`, also available as a
   standalone PDF).

## Usage
1. Click **Open Raster** to pick a file, or **From Loaded Layer...**
   to reuse a raster that is already loaded in the current QGIS
   project (only file-based/GDAL layers are listed — WMS/WMTS/XYZ
   layers can't be reopened this way). When you re-georeference a
   layer picked this way, its old coordinate information is fully
   discarded: the original layer is removed from the map and replaced
   by the newly georeferenced result under the same name — you never
   end up with two copies on the map. Large images are automatically
   shown as a downscaled preview on screen; pixel coordinates are
   always computed against the original image.
2. Toggle **Add Point** and click as many points as you need on the
   image; each click adds a new row to the table on the right.
3. For each row, fill in **X (Map)** and **Y (Map)** with that point's
   known real-world coordinate (decimal separator can be a dot or a
   comma).
4. Uncheck **Enabled** to exclude a point without deleting it, or
   select it in the table and click **Delete Selected Point** to
   remove it entirely.
5. Choose the **Target CRS**, the **Transformation Type** (Linear /
   Polynomial 2-3 / TPS), and the **Resampling Method**, then set the
   output file path.
6. Click **Run Georeferencing**. The operation runs through GDAL
   (Translate + GCPs -> Warp) and, if selected, the result is added
   to QGIS as a layer automatically.

## Notes
- Minimum point count per transformation type: Linear=3, Poly2=6,
  Poly3=10, TPS=3 (more points generally give a better result).
- Paletted/indexed TIFFs (very common for scanned topographic maps,
  e.g. Harita Genel Müdürlüğü / USGS DRG style sheets) are correctly
  expanded through their embedded color table for the on-screen
  preview, instead of the raw color-index values being stretched as
  if they were grayscale intensities (which is what caused the
  inverted/negative-looking preview).
- CMYK-encoded TIFFs (common for scanned/print-origin maps) are
  automatically converted to RGB for the on-screen preview as well.
  This requires `numpy`, which ships with QGIS's own Python
  environment by default.
- Any alpha/transparency band is dropped from the on-screen preview
  (it isn't needed there) and normal 8-bit imagery is no longer
  auto-stretched. This avoids a bug where a constant-value alpha
  band (e.g. a fully-opaque PNG, a common case) could be collapsed
  to fully transparent by the auto-stretch, making the whole preview
  appear blank.
- All of the above only affect the on-screen preview - the final
  georeferenced output still preserves the original raster data
  (including its color table, for paletted sources) as-is.
- The code goes through `qgis.PyQt` and centralizes all Qt5/Qt6 enum
  differences in `qt_compat.py`, so the same plugin code runs
  unmodified on both QGIS versions.
