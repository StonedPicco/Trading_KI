# ADR-0001: Modularer Monolith – API und Worker aus einer Codebasis

**Status:** akzeptiert · **Datum:** 2026-10-24

## Kontext
Zwei Entwickler, Fokus auf fachliche Qualität. Microservices würden Deployments, Netzwerkfehler
und Versionierung zwischen Diensten erzwingen, ohne dass Last oder Teamgröße das rechtfertigen.

## Entscheidung
Eine Python-Codebasis (`backend/app`) mit klaren Modulgrenzen. Sie läuft als zwei Prozesse:
FastAPI (REST/WebSocket) und Worker (APScheduler). `analysis/` und `signals/` sind reine
Funktionen ohne I/O; `services/` orchestrieren. In der Entwicklung kann der Worker im
API-Prozess laufen (`RUN_WORKER_IN_API`), in Produktion nicht (Guard in `Settings`).

## Konsequenzen
+ Einfaches Deployment (Docker Compose), gemeinsame Typen, einfache Tests.
+ Dieselben Analysefunktionen laufen live und im Backtest.
− Skalierung nur vertikal bzw. über weitere Worker. Für das MVP ausreichend; eine Trennung
  wäre später entlang der Modulgrenzen möglich.
