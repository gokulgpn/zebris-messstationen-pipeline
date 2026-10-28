# Schritt 1: Datensichtung mit GDAL (vor der Verarbeitung)

Bevor die Pipeline geschrieben wurde, habe ich beide Dateien mit `ogrinfo` (GDAL 3.7.3) gesichtet.
Aus diesen Befunden sind die Bereinigungsregeln in `pipeline.py` abgeleitet.
Alle Befehle im Ordner der Daten ausführen.

## gebiete.geojson

```
ogrinfo -so gebiete.geojson gebiete
```

| Eigenschaft | Befund |
|---|---|
| Geometrie | Polygon |
| Anzahl | 4 (G1 Nordwest, G2 Nordost, G3 Südwest, G4 Südost) |
| Koordinatensystem | EPSG:25832 (ETRS89 / UTM 32N), im `crs`-Eintrag der Datei angegeben |
| Ausdehnung | 460107 / 5916936 bis 652912 / 6097211 (Meter) |
| Felder | gebiet_id (Text), name (Text) |

Bewertung: sauber. Die Polygone sind gültig und überlappen sich nicht (geprüft mit `ST_IsValid` und `ST_Intersection`).

## stationen.csv

```
ogrinfo -so stationen.csv stationen -oo X_POSSIBLE_NAMES=lon -oo Y_POSSIBLE_NAMES=lat -oo AUTODETECT_TYPE=YES
```

| Eigenschaft | Befund |
|---|---|
| Format | UTF-8 **mit BOM**, Windows-Zeilenenden (CRLF), Trennzeichen `;` |
| Anzahl Zeilen | 5010 |
| Spalten | station_id, name, lat, lon, betreiber, typ, inbetriebnahme, pm10_ugm3 |
| Koordinatensystem | keines in der Datei; lat/lon sind Grad, also WGS84 (EPSG:4326) |
| Ausdehnung laut GDAL | 0 / 0 bis 54.89 / 545160: **offensichtlich fehlerhaft** (Nullwerte, vertauschte und kaputte Koordinaten) |
| pm10_ugm3 | von GDAL als **Text** erkannt, nicht als Zahl: Hinweis auf Platzhalter im Feld |

Zählungen mit SQL direkt auf der Datei (`ogrinfo stationen.csv -dialect SQLite -sql "..."`):

| Befund | Anzahl | Abfrage (gekürzt) |
|---|---|---|
| Zeilen / verschiedene IDs / verschiedene IDs nach Entfernen von Leerzeichen | 5010 / 4980 / 4970 | `COUNT(DISTINCT station_id)`, `COUNT(DISTINCT trim(station_id))` |
| station_id mit Leerzeichen | 10 | `station_id <> trim(station_id)` |
| lat leer / lon leer | 25 / 15 | `lat IS NULL OR lat = ''` |
| Koordinate 0 | 15 | `lat IN ('0','0.0') OR lon IN ('0','0.0')` |
| Dezimalkomma in lat oder lon | 60 | `lat LIKE '%,%' OR lon LIKE '%,%'` |
| lat/lon vertauscht (lat 7 bis 12, lon 53 bis 56) | 40 | `CAST(replace(lat, ',', '.') AS REAL) BETWEEN 7 AND 12 ...` |
| lat größer 90 (Dezimalpunkt fehlt, z. B. 541073) | 5 | `CAST(... AS REAL) > 90` |
| PM10 = -999 / 'n/a' / leer | 21 / 30 / 81 | `pm10_ugm3 = '-999'` usw. |
| PM10 gültige Werte | 5 bis 46.3 | `MIN`, `MAX` ohne Platzhalter |
| Datum im Format TT.MM.JJJJ / JJJJ-MM-TT | 504 / 4506 | `LIKE '__.__.____'`, `LIKE '____-__-__'` |
| unmögliches Datum (30. Februar) | 5 | `LIKE '%-02-30'` |
| typ | Hintergrund 1620, Industrie 1711, Verkehr 1679 | `GROUP BY typ` (sauber) |
| betreiber | Ingenieurbüro Nord 1187, LfU SH 1256, Stadtwerke 1284, Uni Kiel 1283 | `GROUP BY betreiber` (sauber) |

## Sichtprüfung in QGIS

`stationen.csv` als Textebene (Trennzeichen `;`, X = lon, Y = lat, EPSG:4326) zusammen mit `gebiete.geojson`:
die meisten Punkte liegen in den vier Gebieten, vertauschte Punkte liegen weit außerhalb (nahe Äquator),
Nullkoordinaten im Atlantik vor Afrika.

## Was daraus folgt (Regeln in pipeline.py)

| Befund | Regel |
|---|---|
| BOM, `;`, CRLF | Einlesen mit `encoding="utf-8-sig"`, `delimiter=";"`, `newline=""` |
| Leerzeichen in station_id | entfernen, danach Duplikate prüfen |
| Koordinate fehlt oder 0 | verwerfen |
| Dezimalkomma, fehlender Dezimalpunkt | reparieren |
| vertauschte Koordinaten | über die Lage gegen die Gebiete mit GeoPandas erkennen und tauschen |
| Punkt in keinem Gebiet | verwerfen |
| zwei Datumsformate, 30. Februar | beide Formate lesen; unmögliches Datum wird NULL, Station bleibt |
| PM10 -999 und n/a | NULL, Station bleibt (sonst wäre der Mittelwert falsch) |
| doppelte IDs | identisch: eine behalten; widersprüchlich: beide verwerfen |
| typ, betreiber | keine Bereinigung nötig |

Hinweis: Dass 20 Stationen unter einer zweiten ID ("Messcontainer") doppelt vorkommen, zeigte sich erst
in der Auswertung (Abstand 0 m zur nächsten Station) und wurde danach als Regel ergänzt.
