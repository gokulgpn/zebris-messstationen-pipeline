# Messstationen-Pipeline: Python und GDAL

Lösung der Probearbeitsaufgabe „Messstationen-Pipeline (PostGIS + Python)“, ZEBRIS GmbH, 28.10.2026. Ablauf: Daten in Python bereinigen, mit GeoPandas räumlich prüfen, als GeoPackage/CSV schreiben und mit `ogr2ogr` nach PostGIS laden.

## Dateien

| Datei | Zweck |
|---|---|
| `datensichtung.md` | Ursprüngliche Datensichtung mit GDAL und QGIS |
| `pipeline.py` | Python-Verarbeitung und Aufruf der Programme, Teil A und C |
| `tabellen_vorbereiten.sql` | Tabellen mit Datentypen, Primärschlüsseln und räumlichen Indizes anlegen; bisherige Inhalte leeren |
| `auswertung.sql` | Die drei SQL-Auswertungen als Views, Teil B |
| `test_pipeline.py` | 19 Tests in einer Datei |
| `qgis_export_v1.py` | Optionaler Teil D, Version 1: erste eigene Fassung für die QGIS-Python-Konsole |
| `qgis_export_v2.py` | Optionaler Teil D, Version 2: Version 1 mit KI-Unterstützung verbessert (abzugebende Fassung) |
| `stationen_export.gpkg` | Ergebnis von Teil D: 4.900 Stationen, EPSG:25832, Kategorienstil im GeoPackage |
| `Dokumentation_Messstationen_Pipeline.pdf` | Dokumentation: Arbeitsablauf, Ergebnisse, Screenshots aus QGIS und DBeaver, KI-Einsatz |
| `stationen.csv`, `gebiete.geojson` | Eingabedaten der Aufgabe |

`pipeline.py` enthält keine SQL-Anweisungen und keine Datenbank-Cursor. Für die Tabellenvorbereitung startet Python `psql` mit der separaten SQL-Datei. Die gesamte Feldbereinigung, Lageprüfung und Duplikatbehandlung erfolgt in Python. Die Daten lädt ausschließlich `ogr2ogr`.

## Ausführen

Voraussetzungen: Python 3.10 oder neuer, PostgreSQL mit PostGIS, GDAL mit `ogr2ogr` sowie `psql` im PATH, für Teil D QGIS 3.28 oder neuer. Getestet mit Python 3.12.7, PostgreSQL 16.15, PostGIS 3.4.6, GDAL 3.7.3, GeoPandas 1.2.0, QGIS 3.44.13 auf macOS (lokale Postgres.app, kein Docker). Für diesen Mac gibt es zusätzlich einen Suchpfad zu Postgres.app. Nur eine eigene Aufgabendatenbank verwenden: Bei erfolgreicher Vorbereitung werden die bisherigen Inhalte der drei Aufgabentabellen geleert.

`requirements.txt` enthält nur die Python-Pakete (Versionen fest, so getestet). PostgreSQL/PostGIS, GDAL und QGIS sind Systemprogramme und werden separat installiert. Vorher prüfen, dass beide Befehle funktionieren:

```sh
ogr2ogr --version && psql --version
```

Im Ordner dieser README:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PGHOST=localhost
export PGDATABASE=zebris_task
createdb "$PGDATABASE"                         # nur einmal, wenn die Datenbank noch fehlt
psql -X -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS postgis'
python pipeline.py stationen.csv gebiete.geojson
psql -X -v ON_ERROR_STOP=1 -f auswertung.sql
python -m unittest -v test_pipeline
```

Der Pipeline-Aufruf führt die Tabellenvorbereitung automatisch aus. `auswertung.sql` einmal ausführen, um die Views anzulegen; sie bleiben bei weiteren Pipeline-Läufen erhalten. Verbindungsdaten kommen aus `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` oder `.pgpass`. Standard: localhost und `zebris_task`. Kein Passwort steht im Code. Die lokale Postgres.app akzeptiert localhost ohne Passwort (`trust`); für einen Server mit Passwort `PGPASSWORD` setzen oder besser `~/.pgpass` verwenden (Rechte 600).

## Teil D: QGIS-Export (optional)

Einmalig im QGIS-Browser unter PostgreSQL eine Verbindung `zebris_task` anlegen (localhost, 5432, Datenbank `zebris_task`). Dann in QGIS: Erweiterungen > Python-Konsole > Editor, `qgis_export_v2.py` öffnen, `OUTPUT` bei Bedarf anpassen, starten.

Ablauf: PostGIS-Layer `stationen` laden, nach `typ` kategorisieren (Hintergrund, Industrie, Verkehr), mit `native:reprojectlayer` als GeoPackage in EPSG:25832 schreiben und den Stil mit `saveStyleToDatabaseV2` in der Tabelle `layer_styles` des GeoPackage speichern. Beim Öffnen der GeoPackage-Datei erscheinen die Kategorien direkt.

**Version 1** (`qgis_export_v1.py`) habe ich im Stil meines PyQGIS-Kurses (Spatial Thoughts) geschrieben und in QGIS ausgeführt: 4.900 Stationen, EPSG:25832, Stil im GeoPackage.

**Version 2** (`qgis_export_v2.py`) entstand mit KI-Unterstützung aus Version 1. Die Logik ist gleich, geändert wurde:

| Änderung | Grund |
|---|---|
| Gespeicherte QGIS-Verbindung statt Host und Benutzer im Code | Keine Verbindungsdaten im Skript; läuft auch auf einem anderen Rechner ohne Codeänderung |
| Abbruch, wenn die Ausgabedatei schon existiert | Ein vorhandenes Ergebnis wird nicht unbemerkt überschrieben |
| Prüfung, ob das Feld `typ` existiert | Klare Fehlermeldung statt eines unverständlichen Folgefehlers |
| Klare Meldung, wenn die Verbindung fehlt | Zeigt direkt, was einzurichten ist |
| `RuntimeError`/`ValueError` statt allgemeinem `Exception` | Genauere Fehlertypen |
| Ausgabe im Aufgabenordner statt auf dem Schreibtisch | Ergebnis liegt bei den übrigen Abgabedateien |

Unbekannte Werte in `typ` werden weiterhin grau dargestellt und brechen das Skript nicht ab.


## Ergebnis

5.010 gelesen, 4.900 übernommen, 110 verworfen, 4 Gebiete.

| Ablehnung | Anzahl |
|---|---:|
| Koordinate fehlt | 25 |
| Identische Zeile | 20 |
| Gleiche ID, unterschiedliche Werte | 20 |
| Gleiche Orts-/Fachwerte, andere ID | 20 |
| Koordinate ist 0 | 15 |
| Nach Bereinigung identisch | 10 |

Übernommene Korrekturen: 60 Dezimalkommas, 49 ungültige PM10-Einträge zu NULL, 40 Achsentausche, 5 fehlende Dezimalpunkte, 5 ungültige Daten zu NULL und 5 IDs mit entfernten Leerzeichen. Leere PM10-Felder werden ebenfalls NULL, aber nicht als Reparatur gezählt.

## Bereinigungsentscheidungen

- CSV: UTF-8 mit BOM, Semikolon als Trennzeichen. Fehlende/doppelte Spalten oder eine falsche Anzahl Felder stoppen die Verarbeitung vor dem Datenbankzugriff.
- Fehlende oder nicht endliche Koordinaten werden abgelehnt. Nullkoordinaten gelten für diese Aufgabe ebenfalls als Fehler. Dezimalkommas werden ersetzt. Überdimensionierte Gradwerte werden schrittweise durch zehn geteilt und anschließend räumlich geprüft.
- `lat`/`lon` werden als WGS84 interpretiert. GeoPandas transformiert die Punkte nach EPSG:25832. Die gelieferten Gebiete haben bereits diesen CRS. Die Felder `lat` und `lon` enthalten nach der Bereinigung die korrigierten Gradwerte.
- Beide Achsenreihenfolgen werden gegen die Gebiete geprüft. Nur vertauscht passend: tauschen. Keine passend: ablehnen. Beide passend: wegen Mehrdeutigkeit ablehnen.
- Ungültige Datumswerte und fehlende/ungültige PM10-Werte werden NULL. Die Station bleibt für Zählungen nutzbar; NULL wird beim SQL-Mittelwert nicht als null Mikrogramm interpretiert.
- Duplikate werden nach der Bereinigung verglichen. Identische Datensätze einmal behalten; widersprüchliche gültige Kandidaten mit gleicher ID vollständig ablehnen.
- Die Zusatzregel für verschiedene IDs vergleicht gerundete Koordinaten, Betreiber, Typ, Datum und PM10. Die lexikografisch kleinste ID bleibt. Das ist eine Annahme für diese Daten, kein Beweis einer identischen Sensorstation. Der Name wird dabei nicht verglichen.
- Die vier Gebiete gelten hier als Untersuchungsraum. Außerhalb liegende Stationen werden abgelehnt. Für einen anderen Auftrag müsste diese fachliche Regel bestätigt werden.
- SQL verwendet `ST_Covers`, passend zur Randbehandlung in Python. Gemeinsame Grenzen können in beiden Gebieten zählen. Eine einzelne Station bleibt auch ohne nächsten Nachbarn in der Auswertung; die 500-m-Grenze ist eingeschlossen.

## Grenzen

Alle Ausgabedateien werden vor dem Leeren der Tabellen erzeugt. Ein Fehler beim Lesen, Bereinigen oder Schreiben verändert deshalb noch keine Datenbankinhalte. Die Tabellenvorbereitung und die drei `ogr2ogr`-Aufrufe bilden jedoch **keine gemeinsame Transaktion**. Ein später Ladefehler kann einen unvollständigen Stand hinterlassen. Nach Beheben des Fehlers muss der vollständige Lauf wiederholt werden. Das Verfahren ist für die eigene Aufgabendatenbank gedacht, nicht für einen unterbrechungsfreien Produktivbetrieb. Nicht parallel starten.

Die Dezimalpunktreparatur bleibt eine begrenzte Heuristik. `541073` wird zu `54.1073`, aber beispielsweise `lon=990609` wird nicht automatisch zu `9.90609`. Eine Lageprüfung beweist auch nicht die ursprüngliche Messposition. Der Dublettenschlüssel verwendet gerundete Gradwerte, keinen echten Ein-Meter-Abstand. Beide Regeln sind für andere Daten fachlich zu prüfen.

## Prüfung und KI-Unterstützung

Am 28.10.2026: 19 Tests bestanden. Der tatsächliche GDAL-Import wurde in separaten Testdatenbanken geprüft: Wiederholung mit identischem Tabelleninhalt, bestehende Views, leere Eingabe, keine Ablehnungen, ausschließlich Ablehnungen, gültige Geometrien und EPSG:25832. Die Originaldatenbank `zebris_task` wurde dabei nicht verändert.

KI war für die Aufgabe erlaubt und wurde gezielt eingesetzt, alle Werkzeuge lokal in VS Code:

| Schritt | Werkzeug | Anteil |
|---|---|---|
| Datensichtung | GDAL (`ogrinfo`), QGIS | selbst durchgeführt, siehe `datensichtung.md` |
| Fachliche Entscheidungen | | selbst getroffen: EPSG:25832, NULL-Regeln, Lageprüfung gegen die Gebiete, nur Python und `ogr2ogr` |
| Datenanalyse, Pipeline, Tests, SQL-Views | Claude Code, Claude Opus 5.5 („medium“) | KI-unterstützt ausgearbeitet; jede Regel an den Daten nachvollzogen |
| Abschließendes Review, Vergleich der Fassungen | ChatGPT, Modell Astra („high“) | Befunde einzeln geprüft, nur bestätigte übernommen |
| Ausführen und Prüfen | Terminal, DBeaver, QGIS | selbst durchgeführt |
| PyQGIS | QGIS-Python-Konsole | Version 1 selbst, Version 2 KI-unterstützt |
| Dokumentation | Claude Code | KI-unterstützter Entwurf, Inhalte selbst geprüft |

Referenz für den Import: [GDAL PostgreSQL/PostGIS-Treiber](https://gdal.org/en/stable/drivers/vector/pg.html).

Die PyQGIS-Lernfassung wurde zusätzlich mit einer temporär gespeicherten QGIS-Verbindung geprüft: 4.900 Punkte, EPSG:25832, drei Kategorien aus QML, Layer im Projekt und Schutz vor Überschreiben. Beispielausgabe: `stationen_lernversion.gpkg` und `.qml`.
