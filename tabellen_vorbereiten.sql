-- Nur fuer die eigene Aufgabendatenbank: Tabellen anlegen und alte Inhalte leeren.
-- Die Bereinigung erfolgt vorher vollstaendig in Python.
BEGIN;
SET LOCAL search_path TO public;

CREATE TABLE IF NOT EXISTS gebiete (
    gebiet_id text PRIMARY KEY,
    name      text,
    geom      geometry(Polygon, 25832) NOT NULL
);
CREATE INDEX IF NOT EXISTS gebiete_geom_idx ON gebiete USING gist (geom);

CREATE TABLE IF NOT EXISTS stationen (
    station_id     text PRIMARY KEY,
    name           text,
    betreiber      text,
    typ            text,
    inbetriebnahme date,
    pm10_ugm3      numeric(6,1),
    lat            double precision,
    lon            double precision,
    korrektur      text,
    geom           geometry(Point, 25832) NOT NULL
);
CREATE INDEX IF NOT EXISTS stationen_geom_idx ON stationen USING gist (geom);

CREATE TABLE IF NOT EXISTS stationen_abgelehnt (
    zeile      integer,
    station_id text,
    grund      text NOT NULL,
    rohdaten   jsonb
);
ALTER TABLE stationen_abgelehnt ADD COLUMN IF NOT EXISTS hinweis text;

TRUNCATE gebiete, stationen, stationen_abgelehnt;
COMMIT;
