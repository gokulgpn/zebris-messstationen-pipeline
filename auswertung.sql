-- Randpunkte gehoeren dazu. Gemeinsame Grenzen koennen in beiden Gebieten zaehlen.
-- Teil B: Auswertungen als Views. Aufruf: psql -d zebris_task -f auswertung.sql
-- Die Views bleiben erhalten, wenn pipeline.py erneut laeuft (die Pipeline leert die Tabellen nur, sie loescht sie nicht).

-- 1. Anzahl Stationen je Gebiet (LEFT JOIN: auch Gebiete ohne Station erscheinen mit 0)
CREATE OR REPLACE VIEW v_stationen_je_gebiet AS
SELECT g.gebiet_id, g.name, count(s.station_id) AS anzahl_stationen
FROM gebiete g
LEFT JOIN stationen s ON ST_Covers(g.geom, s.geom)
GROUP BY g.gebiet_id, g.name
ORDER BY g.gebiet_id;

-- 2. Je Station: naechste andere Station (ID, Distanz in Metern) und Anzahl anderer Stationen im Umkreis von 500 m.
--    Naechste: KNN-Operator <-> mit LIMIT 1 nutzt den GiST-Index. Umkreis: ST_DWithin nutzt ebenfalls den Index.
--    SRID 25832 ist metrisch, die Distanzen sind also Meter.
CREATE OR REPLACE VIEW v_naechste_station AS
SELECT s.station_id,
       n.station_id                        AS naechste_station_id,
       round(n.distanz_m::numeric, 1)      AS distanz_m,
       u.anzahl_500m
FROM stationen s
LEFT JOIN LATERAL (
    SELECT o.station_id, ST_Distance(o.geom, s.geom) AS distanz_m
    FROM stationen o
    WHERE o.station_id <> s.station_id
    ORDER BY o.geom <-> s.geom, o.station_id
    LIMIT 1
) n ON true
CROSS JOIN LATERAL (
    SELECT count(*) AS anzahl_500m
    FROM stationen o
    WHERE o.station_id <> s.station_id
      AND ST_DWithin(o.geom, s.geom, 500)
) u;

-- 3. Mittlerer PM10-Wert je Gebiet und Stationstyp (Stationen ohne Messwert sind NULL und zaehlen nicht mit)
CREATE OR REPLACE VIEW v_pm10_je_gebiet_typ AS
SELECT g.gebiet_id, g.name, s.typ,
       round(avg(s.pm10_ugm3), 1)   AS pm10_mittel,
       count(s.pm10_ugm3)           AS stationen_mit_wert,
       count(*)                     AS stationen_gesamt
FROM stationen s
JOIN gebiete g ON ST_Covers(g.geom, s.geom)
GROUP BY g.gebiet_id, g.name, s.typ
ORDER BY g.gebiet_id, s.typ;
