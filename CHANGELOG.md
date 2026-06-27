# Changelog

## [3.2] - June 2026
### Fixed
- SSL security vulnerability (verify=True, PostgreSQL certificate conflict resolved)
- HTTP 429 error eliminated by using a single combined Overpass query

### Added
- Direct save to GeoPackage or Shapefile with custom filename
- Layers loaded from disk file in QGIS (not temporary memory layers)
- Run button disabled until a layer and category are selected
- Detailed error messages (timeout, connection, empty zone, permissions)

### Improved
- Compatibility QGIS 3.16 to 4.x
- Spatial index created automatically to avoid clip warnings

# Changelog

## [3.1] - March 2026

### Added
- First public release
- Extract OSM data from any layer extent
- Optimized queries for unstable internet connections (Africa focus)
- Multiple tag selection (buildings, roads, amenities)
- Export to GeoPackage, Shapefile, or temporary layer
- Support for QGIS 3.16 to 4.0
- Progress bar and error handling
