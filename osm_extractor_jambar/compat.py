# -*- coding: utf-8 -*-
"""
Compatibilité PyQt5 (QGIS 3.x) / PyQt6 (QGIS 4.x).
Importer les alias depuis ce module plutôt qu'utiliser Qt directement.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAbstractItemView, QMessageBox, QSizePolicy

# ── Enums Qt ──────────────────────────────────────────────────────────────────
try:
    # PyQt6
    Qt_AlignCenter   = Qt.AlignmentFlag.AlignCenter
    Qt_AlignLeft     = Qt.AlignmentFlag.AlignLeft
    Qt_AlignVCenter  = Qt.AlignmentFlag.AlignVCenter
    Qt_Horizontal    = Qt.Orientation.Horizontal
    Qt_UserRole      = Qt.ItemDataRole.UserRole
    SP_Fixed         = QSizePolicy.Policy.Fixed
    SP_Preferred     = QSizePolicy.Policy.Preferred
    SP_Expanding     = QSizePolicy.Policy.Expanding
    MsgBox_Yes       = QMessageBox.StandardButton.Yes
    MsgBox_No        = QMessageBox.StandardButton.No
except AttributeError:
    # PyQt5
    Qt_AlignCenter   = Qt.AlignCenter
    Qt_AlignLeft     = Qt.AlignLeft
    Qt_AlignVCenter  = Qt.AlignVCenter
    Qt_Horizontal    = Qt.Horizontal
    Qt_UserRole      = Qt.UserRole
    SP_Fixed         = QSizePolicy.Fixed
    SP_Preferred     = QSizePolicy.Preferred
    SP_Expanding     = QSizePolicy.Expanding
    MsgBox_Yes       = QMessageBox.Yes
    MsgBox_No        = QMessageBox.No

# ── QgsField type ─────────────────────────────────────────────────────────────
def make_string_field(name):
    """QgsField de type texte, compatible PyQt5 et PyQt6."""
    from qgis.core import QgsField
    try:
        from qgis.PyQt.QtCore import QMetaType
        return QgsField(name, QMetaType.Type.QString)
    except (ImportError, AttributeError):
        from qgis.PyQt.QtCore import QVariant
        return QgsField(name, QVariant.String)

# ── QgsMapLayerProxyModel ──────────────────────────────────────────────────────
def vector_layer_filter():
    from qgis.core import QgsMapLayerProxyModel
    try:
        return QgsMapLayerProxyModel.Filter.VectorLayer
    except AttributeError:
        return QgsMapLayerProxyModel.VectorLayer

# ── exec() ────────────────────────────────────────────────────────────────────
def dialog_exec(dlg):
    """Appelle exec() ou exec_() selon la version."""
    if hasattr(dlg, "exec"):
        return dlg.exec()
    return dlg.exec_()
