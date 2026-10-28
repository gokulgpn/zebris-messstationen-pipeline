"""Tests der Bereinigungsregeln (ohne Datenbank). Aufruf: python3 -m unittest -v test_pipeline"""
import json
import os
import tempfile
import unittest
from datetime import date

import geopandas as gpd
from shapely.geometry import box

from pipeline import (Abgelehnt, bereinigen, datum, koordinaten, lage_anwenden, lage_entscheiden,
                      lage_pruefen, lese_gebiete, lese_csv, als_geopackage, pm10, verarbeiten, zahl)

ZEILE = {"station_id": "S1", "name": "A", "lat": "54.5", "lon": "9.8", "betreiber": "B",
         "typ": "Verkehr", "inbetriebnahme": "2024-01-01", "pm10_ugm3": "10"}


def gruende(abgelehnt):
    return [grund for _, _, grund, _ in abgelehnt]


class TestKoordinaten(unittest.TestCase):
    def test_dezimalkomma_wird_gelesen(self):
        self.assertEqual(zahl("54,3"), 54.3)
        lat, lon, korr = koordinaten("54,5", "9,8")
        self.assertEqual((lat, lon), (54.5, 9.8))
        self.assertIn("Dezimalkomma", korr)

    def test_fehlender_dezimalpunkt_wird_repariert(self):
        lat, _, korr = koordinaten("541073", "9.90609")
        self.assertAlmostEqual(lat, 54.1073)
        self.assertIn("Dezimalpunkt fehlte", korr)

    def test_fehlende_und_null_koordinaten_werden_abgelehnt(self):
        with self.assertRaisesRegex(Abgelehnt, "fehlt"):
            koordinaten("", "9.5")
        with self.assertRaisesRegex(Abgelehnt, "ist 0"):
            koordinaten("0", "9.5")


class TestLage(unittest.TestCase):
    def test_vertauschte_koordinaten_werden_getauscht(self):
        # GeoPandas meldet: so nicht im Gebiet, vertauscht schon -> tauschen
        self.assertEqual(lage_entscheiden(False, True), "tauschen")
        d = {"lat": 9.09938, "lon": 54.18876, "korrektur": []}
        gut, _ = lage_anwenden([(2, {}, d)], {2: (False, True)})
        self.assertEqual((gut[0][2]["lat"], gut[0][2]["lon"]), (54.18876, 9.09938))
        self.assertIn("lat/lon vertauscht", gut[0][2]["korrektur"])

    def test_punkt_ausserhalb_der_gebiete_wird_abgelehnt(self):
        self.assertEqual(lage_entscheiden(True, False), "ok")
        with self.assertRaisesRegex(Abgelehnt, "ausserhalb der Gebiete"):
            lage_entscheiden(False, False)

    def test_koordinatensystem_kommt_aus_dem_geojson(self):
        """Mit crs-Eintrag (25832) bleiben die Meter-Koordinaten; ohne crs gilt WGS84 und es wird umgerechnet."""
        def lesen(inhalt):
            with tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False) as f:
                json.dump(inhalt, f)
            try:
                return lese_gebiete(f.name)
            finally:
                os.remove(f.name)
        def feature(ring):
            return {"type": "Feature", "properties": {"gebiet_id": "T", "name": "Test"},
                    "geometry": {"type": "Polygon", "coordinates": [ring]}}
        utm = [[500000, 6000000], [510000, 6000000], [510000, 6010000], [500000, 6000000]]
        mit_crs = {"type": "FeatureCollection", "features": [feature(utm)],
                   "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::25832"}}}
        self.assertAlmostEqual(lesen(mit_crs).total_bounds[0], 500000, places=0)
        grad = [[9.0, 54.0], [9.1, 54.0], [9.1, 54.1], [9.0, 54.0]]
        ohne_crs = {"type": "FeatureCollection", "features": [feature(grad)]}
        self.assertGreater(lesen(ohne_crs).total_bounds[0], 400000)       # in Meter umgerechnet

    def test_lagepruefung_mit_geometrie(self):
        """Echte Geometriepruefung: ein Testgebiet um Rendsburg, ein richtiger und ein vertauschter Punkt."""
        gebiet = gpd.GeoDataFrame({"gebiet_id": ["T"]}, geometry=[box(9.5, 54.2, 9.8, 54.4)], crs=4326).to_crs(25832)
        richtig = {"lat": 54.3, "lon": 9.65, "korrektur": []}
        vertauscht = {"lat": 9.65, "lon": 54.3, "korrektur": []}
        weit_weg = {"lat": 48.1, "lon": 11.6, "korrektur": []}
        ergebnis = lage_pruefen([(2, {}, richtig), (3, {}, vertauscht), (4, {}, weit_weg)], gebiet)
        self.assertEqual(ergebnis, {2: (True, False), 3: (False, True), 4: (False, False)})


class TestWerte(unittest.TestCase):
    def test_beide_datumsformate(self):
        self.assertEqual(datum("03.03.2024"), date(2024, 3, 3))
        self.assertEqual(datum("2024-03-03"), date(2024, 3, 3))

    def test_unmoegliches_datum_wird_null_station_bleibt(self):
        self.assertIsNone(datum("2012-02-30"))
        d = bereinigen(dict(ZEILE, inbetriebnahme="2012-02-30"))
        self.assertIsNone(d["inbetriebnahme"])
        self.assertIn("Datum ungueltig -> NULL", d["korrektur"])

    def test_pm10_platzhalter_werden_null(self):
        self.assertIsNone(pm10("-999"))
        self.assertIsNone(pm10("n/a"))
        self.assertIsNone(pm10(""))
        self.assertEqual(pm10("17.7"), 17.7)

    def test_leerzeichen_in_station_id_wird_entfernt(self):
        d = bereinigen(dict(ZEILE, station_id=" S1 "))
        self.assertEqual(d["station_id"], "S1")
        self.assertIn("Leerzeichen in station_id entfernt", d["korrektur"])


class TestDuplikate(unittest.TestCase):
    def test_identische_zeilen_ergeben_eine_station(self):
        gut, schlecht = verarbeiten([ZEILE, dict(ZEILE)])
        self.assertEqual(len(gut), 1)
        self.assertEqual(gruende(schlecht), ["doppelte Zeile"])

    def test_nach_bereinigung_identische_zeilen(self):
        # '54,5' statt '54.5' und ein Leerzeichen in der ID: nach der Bereinigung dieselbe Station
        variante = dict(ZEILE, lat="54,5", station_id="S1 ")
        gut, schlecht = verarbeiten([ZEILE, variante])
        self.assertEqual(len(gut), 1)
        self.assertEqual(gruende(schlecht), ["doppelte Zeile (nach Bereinigung identisch)"])

    def test_widerspruechliche_duplikate_werden_beide_abgelehnt(self):
        gut, schlecht = verarbeiten([ZEILE, dict(ZEILE, pm10_ugm3="99")])
        self.assertEqual(gut, [])
        self.assertEqual(len(schlecht), 2)

    def test_gleiche_station_unter_anderer_id_wird_erkannt(self):
        kopie = dict(ZEILE, station_id="S9", name="Messcontainer 1")
        gut, schlecht = verarbeiten([kopie, ZEILE])
        self.assertEqual([d["station_id"] for d in gut], ["S1"])        # die kleinere ID bleibt
        self.assertEqual(gruende(schlecht), ["Dublette: gleiche Station unter anderer ID"])


class TestRandfaelle(unittest.TestCase):
    def test_nan_und_unendlich_werden_abgewiesen(self):
        for text in ("nan", "inf", "-inf", "1e999"):
            self.assertIsNone(zahl(text))
            self.assertIsNone(pm10(text))
            with self.assertRaises(Abgelehnt):
                koordinaten(text, "9.8")

    def test_beide_achsenreihenfolgen_passend_ist_mehrdeutig(self):
        with self.assertRaisesRegex(Abgelehnt, "mehrdeutig"):
            lage_entscheiden(True, True)

    def test_csv_mit_fehlenden_spalten_stoppt(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = os.path.join(ordner, "falsch.csv")
            with open(pfad, "w") as f:
                f.write("station_id;lat\nS1;54.5\n")
            with self.assertRaises(ValueError):
                lese_csv(pfad)

    def test_leere_ergebnisdateien_haben_spalten(self):
        gebiete = gpd.GeoDataFrame({"gebiet_id": ["T"], "name": ["Test"]},
                                  geometry=[box(9.5, 54.2, 9.8, 54.4)], crs=4326).to_crs(25832)
        with tempfile.TemporaryDirectory() as ordner:
            pfad = os.path.join(ordner, "leer.gpkg")
            als_geopackage(pfad, [], [], gebiete)
            stationen = gpd.read_file(pfad, layer="stationen")
            self.assertEqual(len(stationen), 0)
            self.assertIn("station_id", stationen.columns)
            with open(pfad + ".abgelehnt.csv") as f:
                self.assertEqual(f.readline().strip(), "zeile,station_id,grund,hinweis,rohdaten")


if __name__ == "__main__":
    unittest.main()
