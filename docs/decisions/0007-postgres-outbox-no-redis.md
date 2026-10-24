# ADR-0007: PostgreSQL + Outbox statt Redis/Celery

**Status:** akzeptiert · **Datum:** 2026-10-24

## Entscheidung
- PostgreSQL ist Datenspeicher, Cache für Bars (mit Coverage-Tabelle) und Nachrichtenkanal:
  Der Worker schreibt Events in `events`, die API liest die Tabelle alle 2 s und pusht per WebSocket.
- Jobs: APScheduler im Worker, `max_instances=1`; ein PostgreSQL-Advisory-Lock verhindert
  doppelte Worker.
- Idempotenz über Upserts und UNIQUE-Constraints (Bars, Benachrichtigungen, Outcomes).

## Konsequenzen
+ Eine Infrastrukturkomponente weniger, transaktionale Konsistenz.
− Push-Latenz bis ca. 2 s; bei hoher Last ggf. `LISTEN/NOTIFY` oder Redis nachrüsten.
