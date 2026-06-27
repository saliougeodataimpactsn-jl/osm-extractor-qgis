# -*- coding: utf-8 -*-
"""
OSM Extractor by Jambar Lab -- Logique metier.
Compatible QGIS 3.40+ et QGIS 4.x.

Modifications v3.2 :
  - Securite SSL : verify=True uniquement, conflit PostgreSQL resolu par _fix_ssl_env()
  - _fix_ssl_env() neutralise le conflit de certificats PostgreSQL
  - Messages d'erreur detailles (timeout, connexion, HTTP, zone vide)
  - save_layer() : export GeoPackage ou Shapefile via QgsVectorFileWriter
"""

import json
import logging
import os

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsFields,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorFileWriter,
)
from .compat import make_string_field

try:
    import requests
    import urllib3
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

log = logging.getLogger("JambarOSM")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# ─────────────────────────────────────────────────────────────────────────────
# CATALOGUE OSM
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIES = {
    "routes": {
        "label":      "Routes",
        "selectors":  ['way["highway"]'],
        "geom_type":  "line",
        "layer_name": "OSM_Routes",
    },
    "cours_eau": {
        "label":      "Cours d'eau",
        "selectors":  ['way["waterway"]'],
        "geom_type":  "line",
        "layer_name": "OSM_Cours_deau",
    },
    "batiments": {
        "label":      "Batiments",
        "selectors":  ['way["building"]'],
        "geom_type":  "polygon",
        "layer_name": "OSM_Batiments",
    },
    "ecoles": {
        "label":      "Etablissements scolaires",
        "selectors":  [
            'node["amenity"="school"]',
            'way["amenity"="school"]',
        ],
        "geom_type":  "point",
        "layer_name": "OSM_Ecoles",
    },
    "sante": {
        "label":      "Etablissements de sante",
        "selectors":  [
            'node["amenity"~"hospital|clinic|health_centre|doctors|pharmacy"]',
            'way["amenity"~"hospital|clinic|health_centre"]',
        ],
        "geom_type":  "point",
        "layer_name": "OSM_Sante",
    },
}

SAVE_FORMATS = {
    "gpkg": {
        "label":     "GeoPackage (*.gpkg)",
        "driver":    "GPKG",
        "extension": ".gpkg",
    },
    "shp": {
        "label":     "Shapefile (*.shp)",
        "driver":    "ESRI Shapefile",
        "extension": ".shp",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. CORRECTION ENVIRONNEMENT SSL (conflit PostgreSQL)
# ─────────────────────────────────────────────────────────────────────────────

def _fix_ssl_env():
    """
    Supprime les variables d'environnement SSL invalides avant chaque requete.

    PostgreSQL peut definir SSL_CERT_FILE ou REQUESTS_CA_BUNDLE vers un fichier
    inexistant (ex: C:\\Program Files\\PostgreSQL\\16\\ssl\\certs\\ca-bundle.crt).
    Cela provoque une erreur dans requests meme avec verify=True.
    Cette fonction nettoie ces variables si le fichier cible n'existe pas.
    """
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        path = os.environ.get(var, "")
        if path and not os.path.isfile(path):
            log.warning(
                "Variable d'environnement SSL ignoree : %s -> '%s' (fichier introuvable)",
                var, path
            )
            del os.environ[var]

# ─────────────────────────────────────────────────────────────────────────────
# 2. BBOX
# ─────────────────────────────────────────────────────────────────────────────

def get_bbox_wgs84(layer):
    """Retourne (south, west, north, east) en WGS84. None si couche invalide."""
    if layer is None or not layer.isValid():
        return None
    try:
        extent  = layer.extent()
        wgs84   = QgsCoordinateReferenceSystem("EPSG:4326")
        src_crs = layer.crs()
        if src_crs.authid() != "EPSG:4326":
            tr     = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
            extent = tr.transformBoundingBox(extent)
        buf = 0.0005
        return (
            round(extent.yMinimum() - buf, 6),
            round(extent.xMinimum() - buf, 6),
            round(extent.yMaximum() + buf, 6),
            round(extent.xMaximum() + buf, 6),
        )
    except Exception as exc:
        log.error("Erreur bbox : %s", exc)
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 3. REQUETES OVERPASS
# ─────────────────────────────────────────────────────────────────────────────

def build_combined_query(bbox, keys):
    """
    Construit UNE SEULE requete Overpass pour toutes les categories selectionnees.
    Evite le HTTP 429 (trop de requetes) en remplacant N requetes par une seule.
    """
    s, w, n, e = bbox
    bbox_str = "%s,%s,%s,%s" % (s, w, n, e)
    lines = []
    for key in keys:
        for sel in CATEGORIES[key]["selectors"]:
            lines.append("  %s(%s);" % (sel, bbox_str))
    body = "\n".join(lines)
    return "[out:json][timeout:90];\n(\n%s\n);\nout geom;\n" % body


def build_query(bbox, category_key):
    """Construit la requete Overpass QL pour une seule categorie (usage interne)."""
    s, w, n, e = bbox
    bbox_str  = "%s,%s,%s,%s" % (s, w, n, e)
    selectors = CATEGORIES[category_key]["selectors"]
    lines     = "\n".join("  %s(%s);" % (sel, bbox_str) for sel in selectors)
    return "[out:json][timeout:60];\n(\n%s\n);\nout geom;\n" % lines


def categorize_elements(elements, keys):
    """
    Repartit les elements OSM bruts dans leurs categories respectives.
    Retourne un dict {category_key: [elements]}.
    """
    buckets = {k: [] for k in keys}

    for el in elements:
        tags = el.get("tags", {})
        for key in keys:
            matched = False
            if key == "routes" and tags.get("highway"):
                matched = True
            elif key == "cours_eau" and tags.get("waterway"):
                matched = True
            elif key == "batiments" and tags.get("building"):
                matched = True
            elif key == "ecoles" and tags.get("amenity") == "school":
                matched = True
            elif key == "sante" and tags.get("amenity") in (
                "hospital", "clinic", "health_centre", "doctors", "pharmacy"
            ):
                matched = True
            if matched:
                buckets[key].append(el)
                break  # un element = une seule categorie

    return buckets

# ─────────────────────────────────────────────────────────────────────────────
# 4. TELECHARGEMENT OVERPASS (verify=True uniquement)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_overpass(query):
    """
    Envoie la requete POST a Overpass API.

    Toujours avec verify=True (exige par le depot QGIS / Bandit).
    Le conflit de certificats PostgreSQL est resolu en amont par _fix_ssl_env().

    Retourne (dict_data, None) ou (None, message_erreur).
    """
    if not HAS_REQUESTS:
        return None, (
            "La bibliotheque 'requests' est absente du Python de QGIS.\n"
            "Ouvrez la Console Python (Extensions > Console Python) et tapez :\n"
            "  import subprocess, sys\n"
            "  subprocess.run([sys.executable, '-m', 'pip', 'install', 'requests',\n"
            "      '--trusted-host', 'pypi.org',\n"
            "      '--trusted-host', 'files.pythonhosted.org'])"
        )

    # Nettoyer les variables SSL invalides (conflit PostgreSQL / QGIS)
    _fix_ssl_env()

    try:
        resp = requests.post(
            OVERPASS_URL,
            data={"data": query},
            timeout=60,
            verify=True,
            headers={"User-Agent": "QGIS OSM Extractor Jambar Lab/3.2"},
        )
        resp.raise_for_status()
        data = resp.json()
        log.info("Overpass : %d elements recus", len(data.get("elements", [])))
        return data, None

    except requests.exceptions.Timeout:
        return None, (
            "Timeout depasse : la zone est trop grande ou votre connexion est lente.\n"
            "Conseil : reduisez la zone d'extraction ou relancez dans quelques minutes."
        )
    except requests.exceptions.SSLError as exc:
        return None, (
            "Erreur SSL : impossible de verifier le certificat du serveur.\n"
            "Detail : %s\n"
            "Verifiez vos parametres reseau dans QGIS (Preferences > Options > Reseau)." % exc
        )
    except requests.exceptions.ConnectionError as exc:
        return None, (
            "Erreur de connexion : verifiez votre connexion Internet.\n"
            "Si vous utilisez un proxy, configurez-le dans QGIS "
            "(Preferences > Options > Reseau).\nDetail : %s" % exc
        )
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        if code == 429:
            return None, (
                "Erreur HTTP 429 : trop de requetes envoyees.\n"
                "Attendez quelques secondes avant de relancer."
            )
        if code == 504:
            return None, (
                "Erreur HTTP 504 : delai serveur depasse.\n"
                "La zone est probablement trop grande. Reduisez-la et reessayez."
            )
        return None, "Erreur serveur HTTP %s. Reessayez ulterieurement." % code
    except ValueError as exc:
        return None, (
            "Reponse invalide du serveur Overpass.\n"
            "Le serveur est peut-etre temporairement indisponible. Detail : %s" % exc
        )
    except Exception as exc:
        return None, "Erreur inattendue : %s" % exc

# ─────────────────────────────────────────────────────────────────────────────
# 5. CONVERSION OSM JSON -> QgsVectorLayer memoire
# ─────────────────────────────────────────────────────────────────────────────

def osm_to_layer(data, category_key):
    """
    Convertit les donnees Overpass en QgsVectorLayer memoire avec index spatial.
    Retourne (layer, None) ou (None, message_erreur).
    """
    cat       = CATEGORIES[category_key]
    geom_type = cat["geom_type"]
    elements  = data.get("elements", [])

    if not elements:
        return None, "Aucune donnee trouvee dans cette zone."

    wkb_map = {"point": "Point", "line": "LineString", "polygon": "Polygon"}
    layer    = QgsVectorLayer(
        "%s?crs=EPSG:4326" % wkb_map[geom_type],
        cat["layer_name"],
        "memory",
    )
    provider = layer.dataProvider()

    fields = QgsFields()
    for col in ("osm_id", "osm_type", "name", "category", "tags"):
        fields.append(make_string_field(col))
    provider.addAttributes(fields)
    layer.updateFields()

    count = 0
    for el in elements:
        geom = _to_geom(el, geom_type)
        if geom is None or geom.isEmpty() or not geom.isGeosValid():
            continue
        tags    = el.get("tags", {})
        el_name = (tags.get("name") or tags.get("name:fr")
                   or tags.get("name:en") or "")
        cat_val = (tags.get("highway") or tags.get("waterway")
                   or tags.get("building") or tags.get("amenity") or "")

        feat = QgsFeature(layer.fields())
        feat.setGeometry(geom)
        feat["osm_id"]   = str(el.get("id", ""))
        feat["osm_type"] = el.get("type", "")
        feat["name"]     = el_name
        feat["category"] = cat_val
        feat["tags"]     = json.dumps(tags, ensure_ascii=False)[:1000]
        provider.addFeature(feat)
        count += 1

    if count == 0:
        return None, (
            "Donnees recues mais aucune geometrie valide extraite.\n"
            "La zone contient peut-etre des donnees non georeferenceees."
        )

    layer.updateExtents()
    provider.createSpatialIndex()
    log.info("'%s' : %d entites extraites", cat["layer_name"], count)
    return layer, None


def _to_geom(el, target):
    """Convertit un element Overpass en QgsGeometry."""
    try:
        el_type = el.get("type")
        if el_type == "node":
            lat, lon = el.get("lat"), el.get("lon")
            if lat is None:
                return None
            return QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
        if el_type == "way":
            nodes = el.get("geometry", [])
            if len(nodes) < 2:
                return None
            pts = [QgsPointXY(g["lon"], g["lat"]) for g in nodes]
            if target == "line":
                return QgsGeometry.fromPolylineXY(pts)
            if target == "polygon":
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                if len(pts) < 4:
                    return None
                g = QgsGeometry.fromPolygonXY([pts])
                return g if g.isGeosValid() else g.makeValid()
            if target == "point":
                g = QgsGeometry.fromPolygonXY([pts])
                return g.centroid() if g.isGeosValid() else QgsGeometry.fromPointXY(pts[0])
    except Exception as exc:
        log.warning("Geometrie ignoree (id=%s) : %s", el.get("id"), exc)
    return None

# ─────────────────────────────────────────────────────────────────────────────
# 6. CLIP
# ─────────────────────────────────────────────────────────────────────────────

def clip_layer(layer, clip_source):
    """Decoupe layer selon l'emprise de clip_source via native:clip."""
    try:
        import processing
        if hasattr(clip_source.dataProvider(), "createSpatialIndex"):
            clip_source.dataProvider().createSpatialIndex()
        result  = processing.run(
            "native:clip",
            {"INPUT": layer, "OVERLAY": clip_source, "OUTPUT": "memory:"},
        )
        clipped = result.get("OUTPUT")
        if clipped and clipped.isValid() and clipped.featureCount() > 0:
            clipped.setName(layer.name())
            log.info("Clip OK : %d entites", clipped.featureCount())
            return clipped
        log.warning("Clip vide, couche originale conservee")
        return layer
    except Exception as exc:
        log.warning("Clip echoue (%s), couche originale conservee", exc)
        return layer

# ─────────────────────────────────────────────────────────────────────────────
# 7. SAUVEGARDE -- GeoPackage ou Shapefile
# ─────────────────────────────────────────────────────────────────────────────

def save_layer(layer, file_path, fmt_key="gpkg"):
    """
    Sauvegarde une QgsVectorLayer sur le disque.

    Parametres
    ----------
    layer     : QgsVectorLayer
    file_path : chemin complet avec ou sans extension
    fmt_key   : "gpkg" ou "shp"

    Retourne (chemin_final, None) ou (None, message_erreur).
    """
    if layer is None or not layer.isValid():
        return None, "Couche invalide, impossible de sauvegarder."

    fmt = SAVE_FORMATS.get(fmt_key)
    if fmt is None:
        return None, "Format inconnu : %s" % fmt_key

    if not file_path.lower().endswith(fmt["extension"]):
        file_path = file_path + fmt["extension"]

    dest_dir = os.path.dirname(file_path)
    if dest_dir and not os.path.exists(dest_dir):
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError as exc:
            return None, (
                "Impossible de creer le dossier de destination.\n"
                "Verifiez vos permissions sur : %s\nDetail : %s" % (dest_dir, exc)
            )

    try:
        # API moderne -- QGIS 3.40+ / 4.x
        options              = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName   = fmt["driver"]
        options.fileEncoding = "UTF-8"
        if fmt_key == "gpkg":
            options.layerName = layer.name()
        result   = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            file_path,
            QgsProject.instance().transformContext(),
            options,
        )
        err_code = result[0]
        err_msg  = result[1] if len(result) > 1 else ""
    except AttributeError:
        # Fallback API ancienne (QGIS < 3.10)
        err_code, err_msg = QgsVectorFileWriter.writeAsVectorFormat(
            layer, file_path, "UTF-8", layer.crs(), fmt["driver"],
        )

    if err_code == QgsVectorFileWriter.NoError:
        log.info("Couche sauvegardee : %s", file_path)
        return file_path, None

    return None, (
        "Echec de la sauvegarde : %s\n"
        "Verifiez vos permissions dans : %s" % (err_msg, os.path.dirname(file_path))
    )
