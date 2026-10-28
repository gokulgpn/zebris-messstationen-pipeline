"""Teil D, Version 2: Version 1 mit KI-Unterstuetzung verbessert (Gruende in der README).

In QGIS: Plugins > Python Console > Show Editor, Datei oeffnen, Run.
Voraussetzung: gespeicherte PostgreSQL-Verbindung "zebris_task" im QGIS-Browser
(Host localhost, Port 5432, Datenbank zebris_task).
Laedt den Layer in die Karte, setzt den Stil und speichert ihn im GeoPackage (layer_styles).
"""
from pathlib import Path

from qgis.core import (QgsCategorizedSymbolRenderer, QgsDataSourceUri, QgsProject,
                       QgsProviderRegistry, QgsRendererCategory, QgsSymbol, QgsVectorLayer)
from qgis.PyQt.QtGui import QColor
import processing

# 0. Settings: saved QGIS connection and output file
CONNECTION = 'zebris_task'
OUTPUT = Path('/Users/gokulgopan/Library/CloudStorage/OneDrive-Personal/Career Growth/02_Companies/'
              '2026-09-19_ZEBRIS_GeospatialDeveloper_DE/probetag_aufgabe/stationen_export.gpkg')

if OUTPUT.exists():
    raise FileExistsError(f'{OUTPUT.name} already exists. Change OUTPUT or delete the old file.')

# 1. Connect to PostGIS through the saved connection and load the layer
provider = QgsProviderRegistry.instance().providerMetadata('postgres')
if CONNECTION not in provider.connections():
    raise RuntimeError(f'No saved PostgreSQL connection "{CONNECTION}". Create it in the Browser panel first.')
uri = QgsDataSourceUri(provider.createConnection(CONNECTION).uri())
uri.setDataSource('public', 'stationen', 'geom', '', 'station_id')
layer = QgsVectorLayer(uri.uri(False), 'Messstationen', 'postgres')
if not layer.isValid():
    raise RuntimeError('Layer could not be loaded')
QgsProject.instance().addMapLayer(layer)

# 2. Categorise by typ
idx = layer.fields().indexFromName('typ')
if idx == -1:
    raise ValueError('Field typ is missing')
colors = {'Hintergrund': '#1b9e77', 'Industrie': '#d95f02', 'Verkehr': '#7570b3'}
categories = []
for value in sorted(layer.uniqueValues(idx)):
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setColor(QColor(colors.get(value, '#999999')))
    categories.append(QgsRendererCategory(value, symbol, value))
renderer = QgsCategorizedSymbolRenderer('typ', categories)
layer.setRenderer(renderer)
layer.triggerRepaint()

# 3. Export to GeoPackage with the CRS set explicitly
params = {'INPUT': layer, 'TARGET_CRS': 'EPSG:25832', 'OUTPUT': str(OUTPUT)}
result = processing.run('native:reprojectlayer', params)

# 4. Load the export, give it the same style and save the style inside the GeoPackage
export = QgsVectorLayer(result['OUTPUT'], 'Messstationen (Export)', 'ogr')
export.setRenderer(layer.renderer().clone())
export.saveStyleToDatabaseV2('Stationstyp', 'Kategorien nach typ', True, '')
QgsProject.instance().addMapLayer(export)
print(export.featureCount(), export.crs().authid())
