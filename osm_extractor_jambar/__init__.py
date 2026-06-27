# -*- coding: utf-8 -*-
"""OSM Extractor by Jambar Lab — Point d'entrée QGIS."""


def classFactory(iface):
    from .main import OsmExtractorJambarLab
    return OsmExtractorJambarLab(iface)
