# -*- coding: utf-8 -*-
"""OSM Extractor by Jambar Lab — Cycle de vie du plugin."""

import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


class OsmExtractorJambarLab:

    MENU = "OSM Extractor by Jambar Lab"

    def __init__(self, iface):
        self.iface      = iface
        self.plugin_dir = os.path.dirname(__file__)
        self._action    = None
        self._dialog    = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self._action = QAction(icon, self.MENU, self.iface.mainWindow())
        self._action.setToolTip("Extraire des données OSM par emprise de couche")
        self._action.triggered.connect(self._open)

        self.iface.addPluginToMenu(self.MENU, self._action)
        self.iface.addToolBarIcon(self._action)

    def unload(self):
        if self._action:
            self.iface.removePluginMenu(self.MENU, self._action)
            self.iface.removeToolBarIcon(self._action)
            self._action = None
        if self._dialog:
            self._dialog.close()
            self._dialog = None

    def _open(self):
        from .dialog import OsmExtractorDialog
        if self._dialog is None:
            self._dialog = OsmExtractorDialog(self.iface)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
