def classFactory(iface):
    from .raster_georeferencer import RasterGeoreferencerPlugin
    return RasterGeoreferencerPlugin(iface)
