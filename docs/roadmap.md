# Roadmap (Phase 5)

Priorisierung nach Nutzen für das eigentliche Ziel: belastbar bessere Einschätzungen als einfache
Referenzmethoden. Vor neuen Features steht der Nachweis mit echten Daten.

## P0 – Sofort (vor ernsthafter Nutzung)

1. **Erster Live-Test mit Alpaca-Keys** (kostenlos): Endpunkte, Paging, Daily-Bar-Zeitstempel,
   News-Format und WebSocket gegen die echte API prüfen. Im Build-Environment war das nicht möglich.
   Danach `docs/validation.md` ergänzen.
2. **Datenqualitäts-Monitoring mit echten Daten**: Lücken je Symbol, IEX-Abdeckung, Abgleich
   IEX vs. SIP (verzögert) für RVOL-Plausibilität.
3. **WebSocket-Stream im Worker aktivieren** (`ALPACA_USE_STREAM`), REST nur noch als Backfill.
4. **Live-Signal-Journal sammeln**: 4–8 Wochen Analysen speichern und auswerten lassen. Erst dann
   ist eine Aussage „besser als Baseline“ möglich.

## P1 – Kurzfristig

5. **Multi-Stock-Screening**: Universum (z. B. Top-500 nach Dollar-Volumen) mit leichtem
   Vorfilter (Gap, RVOL, Relativstärke), Vollanalyse nur für Kandidaten. Survivorship-freie
   Universumsliste mit historischen Mitgliedschaften.
6. **Makro & Kalender**: FRED (CPI, Zinsen, Arbeitsmarkt), Fed-Termine; Earnings-Kalender
   (Finnhub, Lizenz prüfen). Ereignis-Risiken als Faktor und Warnung in der Engine.
7. **Erweiterte News-Analyse**: eigener LLM-Klassifikationsschritt bei News-Triggern vor der
   Analyse (ggf. günstigeres Modell nach Teamentscheidung), Sektor-Spillover (betrifft Peers).
8. **Benachrichtigungskanäle**: Telegram und Discord als `Notifier`; E-Mail; Web-Push.
9. **Corporate Actions**: tägliche Prüfung auf Splits und automatischer Neuabruf der Historie.

## P2 – Mittelfristig

10. **Verbesserte Modelle**: Gradient-Boosting/Logistic-Modelle auf den Analogie-Merkmalen mit
    Purged-K-Fold-CV und Walk-Forward. Einsatz nur, wenn out-of-sample besser als die Engine.
11. **Kalibrierte Konfidenz**: Reliability-Diagramme und isotone Kalibrierung, sobald genug
    Live-Outcomes je Evidenz-Bucket vorliegen.
12. **Fortgeschrittene Backtests**: Quote-basierte Spreads (SIP-Quotes oder Databento),
    volumenabhängige Fills, Portfolio-Ebene; vectorbt für Parameter-Sweeps der Schwellen
    (mit strikter Out-of-Sample-Trennung).
13. **Zweiter Datenanbieter**: Massive (Polygon) für lange Historie oder Databento für
    Tick-Qualität. Abgleich der Anbieter als Datenqualitätscheck.
14. **Branchenübergreifende Vergleiche**: Peer-Gruppen, Sektor-Rotation, Breadth (Advance/Decline).

## P3 – Später

15. **Paper-Trading-Auswertung** mit simuliertem Konto (weiterhin ohne echte Orders).
16. Trendlinien/Trendkanäle als eigene Level-Quelle.
17. Mehrbenutzerfähigkeit (Login), Rollen, persönliche Watchlists.
18. Mobile Ansicht und Push.

## Bewusst nicht geplant
- Automatische Orderausführung (außerhalb des Projektumfangs).
- Inoffizielle Datenquellen / Scraping.
