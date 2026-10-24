# ADR-0009: Unveränderbare Analysen

**Status:** akzeptiert · **Datum:** 2026-10-24

## Entscheidung
Jede Analyse wird mit Zeitstempel, Datenstand (`data_as_of`), Fakten, Szenario, Begründung,
Quellen, `input_hash` (SHA-256 der Fakten + Engine-Version), Engine- und Modellversion
gespeichert. `UPDATE`/`DELETE` sind doppelt gesperrt: per SQLAlchemy-Event und per PostgreSQL-
Trigger (Migration 0001). Auswertungen landen in `signal_outcomes`.

## Konsequenzen
+ Nachträgliche Schönfärberei ist technisch ausgeschlossen; objektive Langzeitbewertung möglich.
− Fehlerhafte Analysen bleiben sichtbar (gewollt). Korrekturen erfolgen über neue Analysen.
