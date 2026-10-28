"""Teil D, Version 1: erste eigene Fassung im Stil des Spatial-Thoughts-PyQGIS-Kurses.

In QGIS: Plugins > Python Console > Show Editor, Datei oeffnen, Run.
Verbesserte Fassung mit KI-Unterstuetzung: qgis_export_v2.py (Gruende in der README).
"""
from qgis.core import (QgsCategorizedSymbolRenderer, QgsDataSourceUri, QgsProject,
                       QgsRendererCategory, QgsSymbol, QgsVectorLayer)
from qgis.PyQt.QtGui import QColor
import processing

# 1. Connect to PostGIS and load the layer
uri = QgsDataSourceUri()
uri.setConnection('localhost', '5432', 'zebris_task', 'gokulgopan', '')
uri.setDataSource('public', 'stationen', 'geom', '', 'station_id')
layer = QgsVectorLayer(uri.uri(False), 'Messstationen', 'postgres')
if not layer.isValid():
    raise Exception('Layer could not be loaded')
QgsProject.instance().addMapLayer(layer)

# 2. Categorise by typ
colors = {'Hintergrund': '#1b9e77', 'Industrie': '#d95f02', 'Verkehr': '#7570b3'}
idx = layer.fields().indexFromName('typ')
categories = []
for value in sorted(layer.uniqueValues(idx)):
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setColor(QColor(colors.get(value, '#999999')))
    categories.append(QgsRendererCategory(value, symbol, value))
renderer = QgsCategorizedSymbolRenderer('typ', categories)
layer.setRenderer(renderer)
layer.triggerRepaint()

# 3. Export to GeoPackage with the CRS set explicitly
output = '/Users/gokulgopan/Desktop/stationen_export.gpkg'
params = {'INPUT': layer, 'TARGET_CRS': 'EPSG:25832', 'OUTPUT': output}
result = processing.run('native:reprojectlayer', params)

# 4. Load the export, give it the same style and save the style inside the GeoPackage
export = QgsVectorLayer(result['OUTPUT'], 'Messstationen (Export)', 'ogr')
export.setRenderer(layer.renderer().clone())
export.saveStyleToDatabaseV2('Stationstyp', 'Kategorien nach typ', True, '')
QgsProject.instance().addMapLayer(export)
print(export.featureCount(), export.crs().authid())
