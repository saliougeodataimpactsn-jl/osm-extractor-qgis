# -*- coding: utf-8 -*-
"""
OSM Extractor by Jambar Lab -- Interface principale.
Compatible QGIS 3.40+ et QGIS 4.x (PyQt5 / PyQt6).

Modifications v3.2 :
  - Option "Ajouter au panneau des couches" visible et fonctionnelle
  - Nom de fichier personnalise a la sauvegarde
  - Bouton desactive tant que pas de couche + categorie cochee + pas en cours
  - Messages d'erreur detailles avec popup recapitulatif
  - Sauvegarde GeoPackage / Shapefile / Couche temporaire dans l'interface
"""

import logging
import os
import re

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QCheckBox, QPushButton, QProgressBar,
    QGroupBox, QFrame, QMessageBox, QFileDialog,
    QRadioButton, QButtonGroup, QLineEdit,
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal

from qgis.core import QgsProject, QgsVectorLayer
from qgis.gui import QgsMapLayerComboBox

from .compat import Qt_AlignCenter, vector_layer_filter
from .osm_logic import (
    CATEGORIES, SAVE_FORMATS,
    get_bbox_wgs84, build_combined_query, categorize_elements,
    fetch_overpass, osm_to_layer, clip_layer, save_layer,
)

log = logging.getLogger("JambarOSM")

# ── Palette Jambar Lab ────────────────────────────────────────────────────────
C_GREEN      = "#146C43"
C_GREEN_DARK = "#0f5233"
C_GREEN_LT   = "#e8f5ee"
C_ORANGE     = "#E85D04"
C_BG         = "#FFFFFF"
C_SURFACE    = "#f8fafb"
C_BORDER     = "#dde3e9"
C_TEXT       = "#1a2332"
C_MUTED      = "#64748b"

# ── Stylesheet ────────────────────────────────────────────────────────────────
SS = (
    "QDialog{background:%s;color:%s;font-family:'Segoe UI','Ubuntu',sans-serif;font-size:9pt;}"
    "QGroupBox{background:%s;border:1px solid %s;border-radius:5px;margin-top:10px;"
    "padding:6px 8px;font-size:8pt;font-weight:bold;color:%s;}"
    "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;background:%s;}"
    "QLabel{color:%s;background:transparent;}"
    "QgsMapLayerComboBox,QComboBox{background:%s;border:1px solid %s;border-radius:4px;"
    "padding:3px 6px;color:%s;font-size:9pt;min-height:24px;}"
    "QgsMapLayerComboBox:focus,QComboBox:focus{border-color:%s;}"
    "QComboBox::drop-down{border:none;width:18px;}"
    "QComboBox QAbstractItemView{background:%s;selection-background-color:%s;"
    "color:%s;border:1px solid %s;}"
    "QLineEdit{background:%s;border:1px solid %s;border-radius:4px;padding:3px 6px;"
    "color:%s;font-size:9pt;min-height:22px;}"
    "QLineEdit:focus{border-color:%s;}"
    "QCheckBox{color:%s;spacing:4px;font-size:9pt;padding:1px 0;}"
    "QCheckBox::indicator{width:0;height:0;}"
    "QRadioButton{color:%s;font-size:9pt;padding:2px 0;}"
    "QPushButton#btn_run{background:%s;color:#fff;border:none;border-radius:4px;"
    "padding:7px 22px;font-size:9pt;font-weight:bold;min-height:30px;}"
    "QPushButton#btn_run:hover{background:%s;}"
    "QPushButton#btn_run:pressed{background:#0a3d26;}"
    "QPushButton#btn_run:disabled{background:#adb5bd;color:#e9ecef;}"
    "QProgressBar{border:1px solid %s;border-radius:3px;background:%s;"
    "text-align:center;color:%s;font-size:8pt;max-height:16px;}"
    "QProgressBar::chunk{background:%s;border-radius:2px;}"
    "QFrame#sep{color:%s;}"
) % (
    C_BG, C_TEXT,
    C_BG, C_BORDER, C_GREEN, C_BG,
    C_TEXT,
    C_SURFACE, C_BORDER, C_TEXT, C_GREEN,
    C_BG, C_GREEN_LT, C_TEXT, C_BORDER,
    C_SURFACE, C_BORDER, C_TEXT, C_GREEN,
    C_TEXT,
    C_TEXT,
    C_GREEN, C_GREEN_DARK,
    C_BORDER, C_SURFACE, C_MUTED, C_GREEN,
    C_BORDER,
)


# ─────────────────────────────────────────────────────────────────────────────
# CHECKBOX avec indicateur visuel
# ─────────────────────────────────────────────────────────────────────────────

class IndicatorCheckBox(QCheckBox):
    ON  = "\u2714  "
    OFF = "\u25cb  "

    def __init__(self, label, parent=None):
        self._label = label
        super().__init__(self.OFF + label, parent)
        self.toggled.connect(lambda c: self.setText((self.ON if c else self.OFF) + self._label))


# ─────────────────────────────────────────────────────────────────────────────
# THREAD D'EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

class ExtractionWorker(QThread):
    progress     = pyqtSignal(int)
    status       = pyqtSignal(str)
    layer_ready  = pyqtSignal(object, str)
    error_detail = pyqtSignal(str, str)
    finished     = pyqtSignal(bool, str)

    def __init__(self, bbox, keys, parent=None):
        super().__init__(parent)
        self.bbox  = bbox
        self.keys  = keys
        self._stop = False

    def cancel(self):
        self._stop = True

    def run(self):
        n_ok = n_empty = 0
        total = len(self.keys)

        if self._stop:
            self.finished.emit(False, "Extraction annulee.")
            return

        # ── UNE seule requete pour toutes les categories ──────────────────────
        # Evite le HTTP 429 (rate limiting Overpass)
        self.progress.emit(10)
        self.status.emit("Telechargement en cours (%d categorie(s))..." % total)

        query        = build_combined_query(self.bbox, self.keys)
        data, err    = fetch_overpass(query)
        self.progress.emit(50)

        if err:
            self.error_detail.emit("Telechargement", err)
            self.finished.emit(False, "Echec du telechargement.")
            return

        if self._stop:
            self.finished.emit(False, "Extraction annulee.")
            return

        # ── Repartition des elements par categorie ────────────────────────────
        self.status.emit("Tri et conversion des donnees...")
        elements = data.get("elements", [])
        buckets  = categorize_elements(elements, self.keys)
        self.progress.emit(60)

        for i, key in enumerate(self.keys):
            if self._stop:
                self.finished.emit(False, "Extraction annulee.")
                return

            label = CATEGORIES[key]["label"]
            self.status.emit("Conversion : %s..." % label)

            cat_data = {"elements": buckets.get(key, [])}
            layer, cerr = osm_to_layer(cat_data, key)
            self.progress.emit(60 + int((i + 1) / total * 38))

            if cerr:
                self.status.emit("Vide : %s" % label)
                self.error_detail.emit(label, cerr)
                n_empty += 1
                continue

            self.layer_ready.emit(layer, key)
            n_ok += 1

        self.progress.emit(100)
        parts = []
        if n_ok:    parts.append("%d couche(s) extraite(s)" % n_ok)
        if n_empty: parts.append("%d sans donnees" % n_empty)
        self.finished.emit(n_ok > 0, " - ".join(parts) or "Aucun resultat.")


# ─────────────────────────────────────────────────────────────────────────────
# DIALOGUE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class OsmExtractorDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface       = iface
        self.worker      = None
        self._running    = False
        self._extracted  = []   # (layer, category_key)
        self._errors     = []   # (label, message)
        self._save_dir   = ""

        self.setWindowTitle("OSM Extractor")
        self.setFixedWidth(430)
        self.setStyleSheet(SS)

        self._build_ui()
        self._update_btn()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(14, 12, 14, 12)

        root.addWidget(self._make_header())
        root.addWidget(self._make_layer_group())

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._make_categories_group())
        row.addWidget(self._make_options_group())
        root.addLayout(row)

        root.addWidget(self._make_save_group())

        # Barre de progression
        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        self.prog.setFormat("Pret")
        self.prog.setVisible(False)
        root.addWidget(self.prog)

        # Statut
        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt_AlignCenter)
        self.lbl_status.setStyleSheet("font-size:8pt;color:%s;" % C_MUTED)
        self.lbl_status.setVisible(False)
        root.addWidget(self.lbl_status)

        # Bouton principal
        self.btn_run = QPushButton("Lancer l'extraction")
        self.btn_run.setObjectName("btn_run")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._on_run)
        root.addWidget(self.btn_run)

        sep = QFrame()
        sep.setObjectName("sep")
        sep.setFrameShape(QFrame.Shape.HLine if hasattr(QFrame, "Shape") else QFrame.HLine)
        root.addWidget(sep)

        pied = QLabel("Donnees (c) OpenStreetMap contributors - ODbL")
        pied.setAlignment(Qt_AlignCenter)
        pied.setStyleSheet("font-size:7pt;color:%s;" % C_MUTED)
        root.addWidget(pied)

    def _make_header(self):
        frame = QFrame()
        frame.setStyleSheet("QFrame{background:transparent;border:none;}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 4)
        lbl = QLabel(
            '<span style="font-size:14pt;font-weight:bold;color:%s;">OSM Extractor</span>'
            '<span style="font-size:9pt;color:%s;"> by </span>'
            '<span style="font-size:9pt;font-weight:bold;color:%s;">Jambar Lab</span>'
            % (C_GREEN, C_MUTED, C_ORANGE)
        )
        lbl.setTextFormat(Qt.TextFormat.RichText if hasattr(Qt, "TextFormat") else Qt.RichText)
        ver = QLabel("v3.2")
        ver.setStyleSheet(
            "font-size:7pt;color:#adb5bd;background:%s;"
            "border:1px solid %s;border-radius:3px;padding:1px 5px;" % (C_SURFACE, C_BORDER)
        )
        lay.addWidget(lbl, 1)
        lay.addWidget(ver, 0)
        return frame

    def _make_layer_group(self):
        grp = QGroupBox("Zone d'extraction")
        lay = QVBoxLayout(grp)
        lay.setSpacing(4)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.addWidget(QLabel("Choisir une couche :"))
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(vector_layer_filter())
        self.layer_combo.setAllowEmptyLayer(False)
        self.layer_combo.layerChanged.connect(self._update_btn)
        lay.addWidget(self.layer_combo)
        return grp

    def _make_categories_group(self):
        grp = QGroupBox("Types de donnees")
        lay = QVBoxLayout(grp)
        lay.setSpacing(2)
        lay.setContentsMargins(6, 4, 6, 6)
        self.cat_checks = {}
        for key, cat in CATEGORIES.items():
            cb = IndicatorCheckBox(cat["label"])
            cb.toggled.connect(self._update_btn)
            self.cat_checks[key] = cb
            lay.addWidget(cb)
        lay.addStretch()
        return grp

    def _make_options_group(self):
        grp = QGroupBox("Options")
        lay = QVBoxLayout(grp)
        lay.setSpacing(4)
        lay.setContentsMargins(6, 4, 6, 6)

        # Option : ajouter au panneau des couches
        self.chk_add = IndicatorCheckBox("Ajouter au panneau\ndes couches QGIS")
        self.chk_add.setChecked(True)

        # Option : decouper selon l'emprise
        self.chk_clip = IndicatorCheckBox("Decouper selon\nl'emprise exacte")
        self.chk_clip.setChecked(True)

        lay.addWidget(self.chk_add)
        lay.addWidget(self.chk_clip)
        lay.addStretch()
        return grp

    def _make_save_group(self):
        grp = QGroupBox("Enregistrement sur le disque")
        lay = QVBoxLayout(grp)
        lay.setSpacing(4)
        lay.setContentsMargins(6, 4, 6, 8)

        # Boutons radio de format
        self.rbg         = QButtonGroup(self)
        self.radio_tmp   = QRadioButton("Couche temporaire")
        self.radio_gpkg  = QRadioButton("GeoPackage  (.gpkg)")
        self.radio_shp   = QRadioButton("Shapefile   (.shp)")
        self.radio_tmp.setChecked(True)
        for i, rb in enumerate([self.radio_tmp, self.radio_gpkg, self.radio_shp]):
            self.rbg.addButton(rb, i)
            lay.addWidget(rb)

        # Nom de fichier personnalise
        self.lbl_name = QLabel("Nom de base des fichiers (ex: Dakar_centre) :")
        self.lbl_name.setStyleSheet("font-size:8pt;color:%s;margin-top:4px;" % C_MUTED)
        self.lbl_name.setVisible(False)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Laisser vide pour utiliser le nom par defaut")
        self.edit_name.setVisible(False)

        lay.addWidget(self.lbl_name)
        lay.addWidget(self.edit_name)

        # Choix du dossier
        self.btn_dir = QPushButton("Choisir le dossier de destination...")
        self.btn_dir.setStyleSheet(
            "QPushButton{background:%s;border:1px solid %s;border-radius:4px;"
            "padding:4px 10px;font-size:8pt;color:%s;}"
            "QPushButton:hover{background:%s;}" % (C_SURFACE, C_BORDER, C_TEXT, C_GREEN_LT)
        )
        self.btn_dir.setVisible(False)
        self.btn_dir.clicked.connect(self._pick_dir)

        self.lbl_dir = QLabel("")
        self.lbl_dir.setStyleSheet("font-size:8pt;color:%s;" % C_GREEN)
        self.lbl_dir.setVisible(False)

        lay.addWidget(self.btn_dir)
        lay.addWidget(self.lbl_dir)

        self.radio_gpkg.toggled.connect(self._update_save_ui)
        self.radio_shp.toggled.connect(self._update_save_ui)
        self.radio_tmp.toggled.connect(self._update_save_ui)

        return grp

    # ── Mise a jour de l'interface sauvegarde ────────────────────────────────

    def _update_save_ui(self):
        file_save = self.radio_gpkg.isChecked() or self.radio_shp.isChecked()
        self.lbl_name.setVisible(file_save)
        self.edit_name.setVisible(file_save)
        self.btn_dir.setVisible(file_save)
        self.lbl_dir.setVisible(file_save and bool(self._save_dir))

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de destination", os.path.expanduser("~")
        )
        if d:
            self._save_dir = d
            self.lbl_dir.setText("Dossier : %s" % d)
            self.lbl_dir.setVisible(True)

    # ── Etat du bouton ────────────────────────────────────────────────────────

    def _update_btn(self):
        if self._running:
            self.btn_run.setEnabled(False)
            self.btn_run.setToolTip("Extraction en cours...")
            return
        layer_ok = (
            self.layer_combo.currentLayer() is not None
            and self.layer_combo.currentLayer().isValid()
        )
        cats_ok = any(cb.isChecked() for cb in self.cat_checks.values())
        ok = layer_ok and cats_ok
        self.btn_run.setEnabled(ok)
        if not layer_ok:
            self.btn_run.setToolTip("Selectionnez une couche vecteur.")
        elif not cats_ok:
            self.btn_run.setToolTip("Cochez au moins un type de donnees.")
        else:
            self.btn_run.setToolTip("Lancer l'extraction OSM.")

    # ── Lancement ─────────────────────────────────────────────────────────────

    def _on_run(self):
        layer = self.layer_combo.currentLayer()
        if not layer or not layer.isValid():
            self.iface.messageBar().pushWarning("OSM Extractor", "Aucune couche valide.")
            return

        keys = [k for k, cb in self.cat_checks.items() if cb.isChecked()]
        if not keys:
            self.iface.messageBar().pushWarning("OSM Extractor", "Cochez au moins un type.")
            return

        # Verifier le dossier si sauvegarde demandee
        if (self.radio_gpkg.isChecked() or self.radio_shp.isChecked()) and not self._save_dir:
            QMessageBox.warning(
                self, "Dossier manquant",
                "Vous avez choisi un format de sauvegarde mais aucun dossier\n"
                "de destination n'a ete selectionne.\n\n"
                "Cliquez sur 'Choisir le dossier de destination' ou\n"
                "selectionnez 'Couche temporaire'."
            )
            return

        bbox = get_bbox_wgs84(layer)
        if bbox is None:
            self.iface.messageBar().pushCritical(
                "OSM Extractor", "Impossible de calculer l'emprise (SCR manquant ?)."
            )
            return

        self._clip_src  = layer
        self._extracted = []
        self._errors    = []
        self._set_running(True)
        self.iface.messageBar().pushInfo(
            "OSM Extractor", "Extraction de %d type(s) en cours..." % len(keys)
        )

        self.worker = ExtractionWorker(bbox, keys, parent=self)
        self.worker.progress.connect(self.prog.setValue)
        self.worker.status.connect(self._on_status)
        self.worker.layer_ready.connect(self._on_layer_ready)
        self.worker.error_detail.connect(lambda l, m: self._errors.append((l, m)))
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_status(self, msg):
        self.lbl_status.setText(msg)
        self.prog.setFormat(msg[:40] + "..." if len(msg) > 40 else msg)

    def _on_layer_ready(self, layer, key):
        if self.chk_clip.isChecked():
            layer = clip_layer(layer, self._clip_src)
        # Stocker la couche sans l'ajouter a QGIS pour l'instant.
        # C'est _do_save() qui decide quoi ajouter selon le mode choisi.
        # (Si on addMapLayer ici, QGIS prend ownership et save_layer echoue.)
        self._extracted.append((layer, key))

    def _on_finished(self, success, summary):
        self._set_running(False)
        self.prog.setFormat("Termine")
        self.lbl_status.setText(summary)

        # Popup des erreurs detaillees
        if self._errors:
            detail = "\n\n".join("[ %s ]\n%s" % (l, m) for l, m in self._errors)
            QMessageBox.warning(
                self, "Details des erreurs",
                "Les problemes suivants ont ete rencontres :\n\n" + detail
            )

        if success:
            self.iface.messageBar().pushSuccess("OSM Extractor", summary)
            self._do_save()
        else:
            self.iface.messageBar().pushWarning("OSM Extractor", summary)

    # ── Sauvegarde ────────────────────────────────────────────────────────────

    def _build_filename(self, layer, key):
        """
        Construit le nom de fichier final.
        Si l'utilisateur a saisi un nom de base, on l'utilise comme prefixe.
        Sinon on utilise le nom par defaut de la couche.
        """
        base = self.edit_name.text().strip()
        # Nettoyer les caracteres interdits dans un nom de fichier
        base = re.sub(r'[\\/:*?"<>|]', "_", base)

        if base:
            # Ajouter le nom de la couche comme suffixe pour differencier
            # ex: "Dakar_centre_OSM_Routes"
            return "%s_%s" % (base, layer.name())
        return layer.name()

    def _do_save(self):
        if not self._extracted:
            return

        # ── Mode couche temporaire : ajouter directement dans QGIS ──────────
        if self.radio_tmp.isChecked():
            if self.chk_add.isChecked():
                for layer, key in self._extracted:
                    # Appliquer le nom personnalise meme en mode temporaire
                    nom_tmp = self._build_filename(layer, key)
                    layer.setName(nom_tmp)
                    QgsProject.instance().addMapLayer(layer)
            return

        # ── Mode fichier (GeoPackage ou Shapefile) ───────────────────────────
        fmt_key = "gpkg" if self.radio_gpkg.isChecked() else "shp"
        dossier = self._save_dir
        sauves  = []
        erreurs = []

        for layer, key in self._extracted:
            # Capturer le nom AVANT save_layer car QgsVectorFileWriter
            # peut liberer l'objet C++ de la couche apres ecriture,
            # rendant layer.name() inaccessible ensuite.
            nom        = self._build_filename(layer, key)
            layer_name = layer.name()   # str Python pur, toujours accessible
            chemin     = os.path.join(dossier, nom)

            # 1. Sauvegarder sur le disque
            ok, err = save_layer(layer, chemin, fmt_key)

            if ok:
                sauves.append(os.path.basename(ok))
                log.info("Sauvegarde : %s", ok)
                if self.chk_add.isChecked():
                    # 2. Charger le fichier depuis le disque dans QGIS
                    file_layer = QgsVectorLayer(ok, nom, "ogr")
                    if file_layer.isValid():
                        QgsProject.instance().addMapLayer(file_layer)
                        log.info("Couche chargee dans QGIS : %s", nom)
                    else:
                        log.warning("Fichier invalide apres sauvegarde : %s", ok)
                        try:
                            layer.setName(nom)
                            QgsProject.instance().addMapLayer(layer)
                        except RuntimeError:
                            log.warning("Couche memoire inaccessible pour fallback.")
            else:
                erreurs.append("%s : %s" % (nom, err))
                log.error("Echec sauvegarde %s : %s", nom, err)
                if self.chk_add.isChecked():
                    try:
                        layer.setName(nom)
                        QgsProject.instance().addMapLayer(layer)
                    except RuntimeError:
                        log.warning("Impossible d'ajouter la couche memoire : %s", nom)

        if sauves:
            self.iface.messageBar().pushSuccess(
                "OSM Extractor",
                "%d fichier(s) sauvegardes dans : %s" % (len(sauves), dossier)
            )
        if erreurs:
            QMessageBox.warning(
                self, "Erreur de sauvegarde",
                "Certaines couches n'ont pas pu etre sauvegardees :\n\n"
                + "\n".join(erreurs)
                + "\n\nVerifiez vos permissions dans :\n%s" % dossier
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_running(self, running):
        self._running = running
        self._update_btn()
        for w in (
            self.layer_combo, self.chk_add, self.chk_clip,
            self.radio_tmp, self.radio_gpkg, self.radio_shp,
            self.btn_dir, self.edit_name,
        ):
            w.setEnabled(not running)
        for cb in self.cat_checks.values():
            cb.setEnabled(not running)
        self.prog.setVisible(True)
        self.lbl_status.setVisible(True)
        if running:
            self.prog.setValue(0)
            self.prog.setFormat("Demarrage...")
            self.lbl_status.setText("Connexion a Overpass API...")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        event.accept()
