# OSM Extractor — QGIS Plugin

[![QGIS Plugin](https://img.shields.io/badge/QGIS-Plugin-green)](https://plugins.qgis.org/plugins/osm_extractor_jambar/)
[![License](https://img.shields.io/badge/License-GPLv2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)

Extract OpenStreetMap data directly from any layer extent in QGIS.

## Features

- 🌍 **Worldwide** — Use anywhere on the planet
- 📍 **From any layer** — Extract OSM data from polygon layers, point layers, or the canvas extent
- 🚀 **Optimized** — Works even on slow/unstable connections (Africa, rural areas)
- 🗺️ **Overpass API** — Uses the latest OpenStreetMap data
- 📊 **Multiple outputs** — Export as GeoPackage, Shapefile, or temporary layer

## Installation

### From QGIS Official Repository (recommended)

1. Open QGIS
2. Go to **Plugins → Manage and Install Plugins**
3. Search for `OSM Extractor`
4. Click **Install**

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/saliougeodataimpactsn-jl/osm-extractor-qgis/releases)
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**
3. Select the downloaded ZIP file

## Usage

1. Load a vector layer (polygon or point) in QGIS
2. Go to **Plugins → OSM Extractor**
3. Choose the layer or the current canvas extent
4. Select what to extract:
   - Buildings
   - Roads
   - Amenities
   - Custom OSM tags
5. Click **Extract**
6. Choose output format (GeoPackage recommended)

## Requirements

- QGIS 3.16 or higher
- Internet connection (to query Overpass API)

## Development

This plugin is maintained by **Jambar Lab** — Geospatial solutions for Africa.

- 📧 Contact: saliougeodataimpact.sn@gmail.com
- 🐛 Report issues: [GitHub Issues](https://github.com/saliougeodataimpactsn-jl/osm-extractor-qgis/issues)

## License

GNU General Public License v2.0

## Changelog

See [CHANGELOG.md](CHANGELOG.md)