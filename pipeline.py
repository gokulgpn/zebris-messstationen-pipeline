"""Messstationen-Pipeline (Teil A und C).

Aufruf:  python3 pipeline.py stationen.csv gebiete.geojson

Ablauf:
  1. CSV lesen (UTF-8 mit BOM, Trennzeichen ;).
  2. Jede Zeile Feld fuer Feld pruefen (Python):
       station_id    -> Leerzeichen entfernen; fehlt sie, wird verworfen
       lat, lon      -> fehlt oder 0: verworfen; Dezimalkomma und fehlender Dezimalpunkt: repariert
       inbetriebnahme-> zwei Formate; unlesbar oder unmoeglich (30.02.): NULL, Station bleibt
       pm10_ugm3     -> '-999' und 'n/a' bedeuten 'kein Messwert': NULL, Station bleibt
  3. Lage pruefen (GeoPandas/Shapely) gegen die gelieferten Gebiete: liegt der Punkt in einem Gebiet,
     ist er gut. Liegt er nur mit vertauschtem lat/lon in einem Gebiet, wird getauscht. Sonst: verworfen.
  4. Duplikate pruefen: gleiche ID (identisch oder widerspruechlich), gleiche Station unter anderer ID.
  5. Ergebnis als GeoPackage schreiben und mit ogr2ogr in PostGIS laden: Tabellen werden einmal angelegt
     durch tabellen_vorbereiten.sql, vor jedem Lauf geleert und mit
     ogr2ogr -append befuellt. Dadurch kann das Skript beliebig oft laufen, ohne Duplikate zu erzeugen;
     Views auf den Tabellen bleiben erhalten.
  6. Bericht ausgeben.

Verbindung ueber PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD. Standard: localhost, zebris_task.
Abhaengigkeiten: geopandas (requirements.txt), ogr2ogr (GDAL) und psql.
SQL steht ausschliesslich in separaten .sql-Dateien, nicht in dieser Pipeline.
"""
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import geopandas as gpd

PM10_KEIN_WERT = -999.0          # Platzhalter in den Daten fuer "kein Messwert"
ZIEL_SRID = 25832                # ETRS89 / UTM 32N, metrisch: Distanzen in Metern


class Abgelehnt(Exception):
    """Ein Datensatz ist nicht brauchbar. Die Meldung ist der Grund."""


# ------------------------------------------------------------------ Feldregeln (Python, getestet)

def zahl(text):
    """'54,3' oder '54.3' -> 54.3; leer oder unlesbar -> None."""
    if text is None or str(text).strip() == "":
        return None
    try:
        wert = float(str(text).strip().replace(",", "."))
        if not math.isfinite(wert):  # NaN und Unendlich sind keine verwendbaren Messwerte.
            return None
        return wert
    except ValueError:
        return None


def dezimalpunkt_reparieren(wert, grenze):
    """Fehlender Dezimalpunkt: 541073 -> 54.1073. Grenze 90 (Breite) bzw. 180 (Laenge) ist die
    mathematische Grenze fuer Grad. Dies ist eine Heuristik fuer die gelieferten Daten.
    Die Lagepruefung danach ist keine Garantie fuer die urspruengliche Messposition."""
    if not math.isfinite(wert):
        raise Abgelehnt("Koordinate ist nicht endlich")
    repariert = False
    while abs(wert) > grenze:
        wert /= 10
        repariert = True
    return wert, repariert


def koordinaten(lat_text, lon_text):
    """Nur das Format: gibt (lat, lon, [Korrekturen]) zurueck oder wirft Abgelehnt.
    Ob der Punkt am richtigen Ort liegt, entscheidet danach GeoPandas mit den Gebieten."""
    lat, lon = zahl(lat_text), zahl(lon_text)
    korrekturen = []
    if lat is None or lon is None:
        raise Abgelehnt("Koordinate fehlt")
    if lat == 0 or lon == 0:
        raise Abgelehnt("Koordinate ist 0")
    if "," in str(lat_text) or "," in str(lon_text):
        korrekturen.append("Dezimalkomma")
    lat, rep_lat = dezimalpunkt_reparieren(lat, 90)
    lon, rep_lon = dezimalpunkt_reparieren(lon, 180)
    if rep_lat or rep_lon:
        korrekturen.append("Dezimalpunkt fehlte")
    return lat, lon, korrekturen


def lage_entscheiden(liegt_im_gebiet, liegt_vertauscht_im_gebiet):
    """Ergebnis der Lagepruefung: 'ok', 'tauschen' oder Abgelehnt."""
    if liegt_im_gebiet and liegt_vertauscht_im_gebiet:
        raise Abgelehnt("Achsenreihenfolge mehrdeutig")
    if liegt_im_gebiet:
        return "ok"
    if liegt_vertauscht_im_gebiet:
        return "tauschen"
    raise Abgelehnt("ausserhalb der Gebiete")


def datum(text):
    """'03.03.2024' und '2024-03-03' -> date(2024, 3, 3). Leer, unlesbar oder unmoeglich (30.02.) -> None."""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def pm10(text):
    """'-999' und 'n/a' bedeuten 'kein Messwert' -> None. Negative Werte ebenso."""
    wert = zahl(text)
    if wert is None or wert == PM10_KEIN_WERT or wert < 0:
        return None
    return wert


def bereinigen(zeile):
    """Eine CSV-Zeile -> bereinigtes dict, oder Abgelehnt. Prueft Feld fuer Feld."""
    korrekturen = []

    roh_id = zeile.get("station_id") or ""
    sid = roh_id.strip()
    if not sid:
        raise Abgelehnt("station_id fehlt")
    if sid != roh_id:
        korrekturen.append("Leerzeichen in station_id entfernt")

    lat, lon, korr_koord = koordinaten(zeile.get("lat"), zeile.get("lon"))
    korrekturen += korr_koord

    roh_datum = (zeile.get("inbetriebnahme") or "").strip()
    inbetriebnahme = datum(roh_datum)
    if inbetriebnahme is None and roh_datum:
        korrekturen.append("Datum ungueltig -> NULL")

    roh_pm = (zeile.get("pm10_ugm3") or "").strip()
    pm = pm10(roh_pm)
    if pm is None and roh_pm:
        korrekturen.append("PM10 fehlt oder ungueltig -> NULL")

    return {
        "station_id": sid,
        "name": (zeile.get("name") or "").strip(),
        "betreiber": (zeile.get("betreiber") or "").strip(),
        "typ": (zeile.get("typ") or "").strip(),
        "inbetriebnahme": inbetriebnahme,
        "pm10_ugm3": pm,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "korrektur": korrekturen,
    }


# Verworfene Datensaetze: (zeilennr, rohzeile, grund, hinweis)

def bereinigen_alle(zeilen):
    """Feldpruefung aller Zeilen -> (kandidaten [(zeilennr, roh, dict)], abgelehnt)."""
    kandidaten, abgelehnt = [], []
    for nr, zeile in enumerate(zeilen, start=2):          # Zeile 1 ist die Kopfzeile
        try:
            kandidaten.append((nr, zeile, bereinigen(zeile)))
        except Abgelehnt as e:
            abgelehnt.append((nr, zeile, str(e), None))
    return kandidaten, abgelehnt


def lage_anwenden(kandidaten, pruefung):
    """pruefung: {zeilennr: (liegt_im_gebiet, liegt_vertauscht_im_gebiet)} aus GeoPandas."""
    gut, abgelehnt = [], []
    for nr, roh, d in kandidaten:
        try:
            if lage_entscheiden(*pruefung[nr]) == "tauschen":
                d["lat"], d["lon"] = d["lon"], d["lat"]
                d["korrektur"].append("lat/lon vertauscht")
            gut.append((nr, roh, d))
        except Abgelehnt as e:
            abgelehnt.append((nr, roh, str(e), None))
    return gut, abgelehnt


def fachwerte(d):
    """Alle Werte ausser der Korrekturliste: zum Vergleich zweier Zeilen mit gleicher ID."""
    werte = []
    for feld in ("station_id", "name", "betreiber", "typ", "inbetriebnahme", "pm10_ugm3", "lat", "lon"):
        werte.append(d[feld])
    return tuple(werte)


def ortsschluessel(d):
    """Gerundete Gradwerte und Fachwerte: Dublettenannahme fuer diese Daten, kein Identitaetsbeweis."""
    return (round(d["lat"], 5), round(d["lon"], 5), d["typ"], d["betreiber"], d["inbetriebnahme"], d["pm10_ugm3"])


def duplikate(kandidaten):
    """Duplikate pruefen, nach Feld- und Lagepruefung (so sind '54,3' und '54.3' gleich).
    -> (angenommen [dict], abgelehnt)"""
    abgelehnt = []
    nach_id = {}
    for nr, roh, d in kandidaten:
        sid = d["station_id"]
        if sid not in nach_id:
            nach_id[sid] = []
        nach_id[sid].append((nr, roh, d))

    eindeutig = {}
    for eintraege in nach_id.values():
        erster_datensatz = eintraege[0][2]
        widerspruch = False
        for nr, roh, d in eintraege:
            if fachwerte(d) != fachwerte(erster_datensatz):
                widerspruch = True
        if widerspruch:
            for nr, roh, d in eintraege:
                abgelehnt.append((nr, roh, "station_id mehrfach mit unterschiedlichen Werten", None))
            continue
        erster_nr, erster_roh, _ = eintraege[0]
        eindeutig[erster_datensatz["station_id"]] = eintraege[0]
        for nr, roh, _ in eintraege[1:]:
            grund = "doppelte Zeile" if roh == erster_roh else "doppelte Zeile (nach Bereinigung identisch)"
            abgelehnt.append((nr, roh, grund, f"gleich wie Zeile {erster_nr}"))

    # Dieselbe Station unter anderer ID (zweite Quelle): gleicher Ort und gleiche Fachwerte.
    # Behalten wird die kleinste ID.
    erste, angenommen = {}, []
    for sid in sorted(eindeutig):
        nr, roh, d = eindeutig[sid]
        schluessel = ortsschluessel(d)
        if schluessel in erste:
            abgelehnt.append((nr, roh, "Dublette: gleiche Station unter anderer ID", f"gleich wie {erste[schluessel]}"))
        else:
            erste[schluessel] = d["station_id"]
            angenommen.append(d)
    return angenommen, abgelehnt


def verarbeiten(zeilen):
    """Feldpruefung und Duplikate ohne Datenbank (fuer Tests). Die Pipeline prueft dazwischen die Lage mit GeoPandas."""
    kandidaten, abgelehnt = bereinigen_alle(zeilen)
    angenommen, dup = duplikate(kandidaten)
    return angenommen, abgelehnt + dup


def lese_csv(pfad):
    """CSV lesen; ein falscher Dateiaufbau bricht vor jedem Datenbankzugriff ab."""
    pflichtfelder = {"station_id", "name", "lat", "lon", "betreiber", "typ", "inbetriebnahme", "pm10_ugm3"}
    with open(pfad, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";", strict=True)
        felder = reader.fieldnames or []
        if not pflichtfelder.issubset(felder) or len(felder) != len(set(felder)):
            raise ValueError("CSV-Kopf: Pflichtfelder fehlen oder Spalten sind doppelt")
        zeilen = []
        for nr, zeile in enumerate(reader, start=2):
            if None in zeile or None in zeile.values():
                raise ValueError(f"CSV-Datensatz {nr}: falsche Anzahl Felder")
            zeilen.append(zeile)
    return zeilen


def lese_gebiete(pfad):
    """Gebiete mit GeoPandas lesen. Das Koordinatensystem kommt aus der Datei ('crs'-Eintrag);
    fehlt es, gilt der GeoJSON-Standard WGS84 (EPSG:4326). Ergebnis in ZIEL_SRID."""
    gebiete = gpd.read_file(pfad)
    if gebiete.crs is None:
        gebiete = gebiete.set_crs(4326)
    gebiete = gebiete.to_crs(ZIEL_SRID)
    if gebiete.empty or not {"gebiet_id", "name"}.issubset(gebiete.columns):
        raise ValueError("Gebiete oder Pflichtfelder fehlen")
    if gebiete["gebiet_id"].isna().any() or gebiete["gebiet_id"].duplicated().any():
        raise ValueError("Gebiets-IDs fehlen oder sind doppelt")
    if not gebiete.geometry.is_valid.all() or gebiete.geometry.is_empty.any():
        raise ValueError("Gebietsgeometrie ist ungueltig oder leer")
    if not gebiete.geom_type.eq("Polygon").all():
        raise ValueError("Gebiete muessen Polygone sein")
    return gebiete


def punkte(lon, lat):
    """WGS84-Koordinaten (Listen) -> Punkte in ZIEL_SRID als GeoSeries."""
    return gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4326).to_crs(ZIEL_SRID)


def lage_pruefen(kandidaten, gebiete):
    """Fuer jeden Kandidaten: liegt der Punkt (lon, lat) in einem Gebiet, und liegt er vertauscht (lat, lon) darin?
    Rueckgabe: {zeilennr: (liegt_im_gebiet, liegt_vertauscht_im_gebiet)}"""
    if not kandidaten:
        return {}
    flaeche = gebiete.geometry.union_all()                 # alle Gebiete als eine Flaeche
    lat = [d["lat"] for _, _, d in kandidaten]
    lon = [d["lon"] for _, _, d in kandidaten]
    im_gebiet = punkte(lon, lat).intersects(flaeche)      # so wie geliefert
    vertauscht = punkte(lat, lon).intersects(flaeche)     # lat und lon getauscht
    pruefung = {}
    for i, kandidat in enumerate(kandidaten):
        nr = kandidat[0]
        pruefung[nr] = (bool(im_gebiet.iloc[i]), bool(vertauscht.iloc[i]))
    return pruefung


# ------------------------------------------------------------------ Ausgabe: GeoPackage, dann ogr2ogr nach PostGIS



def programm_finden(name):
    """Programm im PATH suchen, alternativ in Postgres.app auf diesem Mac."""
    pfad = shutil.which(name)
    if pfad:
        return pfad
    mac_pfad = Path("/Applications/Postgres.app/Contents/Versions/latest/bin") / name
    if mac_pfad.is_file():
        return str(mac_pfad)
    raise FileNotFoundError(f"{name} fehlt. Bitte installieren und zum PATH hinzufuegen.")


def befehl_ausfuehren(befehl):
    """Ein externes Programm starten. Bei einem Fehler stoppt die Pipeline."""
    umgebung = os.environ.copy()
    umgebung.setdefault("PGHOST", "localhost")
    umgebung.setdefault("PGDATABASE", "zebris_task")
    ergebnis = subprocess.run(befehl, env=umgebung, capture_output=True, text=True)
    if ergebnis.returncode != 0:
        raise RuntimeError(f"{Path(befehl[0]).name} fehlgeschlagen:\n{ergebnis.stderr}")
    if ergebnis.stderr.strip():
        print(ergebnis.stderr.strip(), file=sys.stderr)


def tabellen_vorbereiten(psql):
    """psql fuehrt die separate SQL-Datei aus. Keine Bereinigungslogik in SQL."""
    sql_datei = Path(__file__).with_name("tabellen_vorbereiten.sql")
    befehl_ausfuehren([psql, "-X", "-v", "ON_ERROR_STOP=1", "-f", str(sql_datei)])


def als_geopackage(pfad, angenommen, abgelehnt, gebiete):
    """Zwei GeoPackage-Layer und eine CSV mit verworfenen Datensaetzen schreiben."""
    felder = ["station_id", "name", "betreiber", "typ", "inbetriebnahme", "pm10_ugm3", "lat", "lon", "korrektur"]
    daten = []
    for station in angenommen:
        zeile = station.copy()
        if station["inbetriebnahme"] is not None:
            zeile["inbetriebnahme"] = station["inbetriebnahme"].isoformat()
        zeile["korrektur"] = ", ".join(station["korrektur"]) or None
        daten.append(zeile)

    # Spalten auch bei null uebernommenen Zeilen explizit anlegen.
    stationen = gpd.GeoDataFrame(daten, columns=felder)
    stationen = stationen.set_geometry(punkte(stationen["lon"], stationen["lat"]))
    stationen.to_file(pfad, layer="stationen", driver="GPKG", engine="pyogrio")
    gebiete[["gebiet_id", "name", "geometry"]].to_file(pfad, layer="gebiete", driver="GPKG", engine="pyogrio")

    # DictWriter schreibt auch bei null Ablehnungen einen gueltigen CSV-Kopf.
    with open(str(pfad) + ".abgelehnt.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["zeile", "station_id", "grund", "hinweis", "rohdaten"])
        writer.writeheader()
        for nr, roh, grund, hinweis in abgelehnt:
            writer.writerow({"zeile": nr, "station_id": (roh.get("station_id") or "").strip(),
                             "grund": grund, "hinweis": hinweis,
                             "rohdaten": json.dumps(roh, ensure_ascii=False)})


def nach_postgis(ogr2ogr, pfad):
    """ogr2ogr laedt in die zuvor geleerten Tabellen. Verbindung kommt aus PG*-Variablen."""
    for layer in ("gebiete", "stationen"):
        befehl_ausfuehren([
            ogr2ogr, "-f", "PostgreSQL", "PG:", str(pfad), layer,
            "-nln", "public." + layer, "-append"
        ])
    befehl_ausfuehren([
        ogr2ogr, "-f", "PostgreSQL", "PG:", str(pfad) + ".abgelehnt.csv",
        "-nln", "public.stationen_abgelehnt", "-append", "-nlt", "NONE",
        "-oo", "EMPTY_STRING_AS_NULL=YES"
    ])


def ausfuehren(zeilen, gebiete_pfad):
    """Bereinigen, Dateien schreiben, Tabellen vorbereiten, mit GDAL laden."""
    ogr2ogr = programm_finden("ogr2ogr")
    psql = programm_finden("psql")
    gebiete = lese_gebiete(gebiete_pfad)
    kandidaten, abgelehnt = bereinigen_alle(zeilen)
    pruefung = lage_pruefen(kandidaten, gebiete)
    kandidaten, lage_ab = lage_anwenden(kandidaten, pruefung)
    angenommen, dup_ab = duplikate(kandidaten)
    abgelehnt += lage_ab + dup_ab
    if len(angenommen) + len(abgelehnt) != len(zeilen):
        raise RuntimeError("Zeilenbilanz stimmt nicht")

    with tempfile.TemporaryDirectory() as ordner:
        pfad = Path(ordner) / "ergebnis.gpkg"
        # Erst alle Dateien schreiben. Ein Exportfehler leert damit keine Tabellen.
        als_geopackage(pfad, angenommen, abgelehnt, gebiete)
        tabellen_vorbereiten(psql)
        nach_postgis(ogr2ogr, pfad)
    return angenommen, abgelehnt, len(gebiete)


def bericht(gelesen, angenommen, abgelehnt, n_gebiete):
    print(f"Gelesen:      {gelesen}")
    print(f"Uebernommen:  {len(angenommen)}")
    print(f"Verworfen:    {len(abgelehnt)}")
    for grund, n in Counter(grund for _, _, grund, _ in abgelehnt).most_common():
        print(f"  - {grund}: {n}")
    korrekturen = Counter(k for d in angenommen for k in d["korrektur"])
    if korrekturen:
        print("Repariert (uebernommen):")
        for art, n in korrekturen.most_common():
            print(f"  - {art}: {n}")
    print(f"Gebiete geladen: {n_gebiete} (Lagepruefung der Stationen gegen diese Polygone, GeoPandas)")


def main(argv):
    if len(argv) != 3:
        sys.exit("Aufruf: python3 pipeline.py stationen.csv gebiete.geojson")
    zeilen = lese_csv(argv[1])
    angenommen, abgelehnt, n_gebiete = ausfuehren(zeilen, argv[2])
    bericht(len(zeilen), angenommen, abgelehnt, n_gebiete)


if __name__ == "__main__":
    main(sys.argv)
