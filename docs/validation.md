# Phase 4 – Validierung

Stand: 2026-10-24 · Branch `feature/mvp`

## 1. Was geprüft wurde und Ergebnis

| Bereich | Prüfung | Ergebnis |
|---|---|---|
| Berechnungslogik | 77 Backend-Tests (pytest) | ✅ alle grün auf SQLite **und** PostgreSQL 16 |
| Indikatoren | Referenzwerte (EMA rekursiv, Wilder-RSI 0/50/100, ATR konstant, BB, MACD), VWAP-Reset je Session ohne Extended Hours, RVOL = 1 bei identischen Sessions und 5× bei Spike | ✅ |
| Zeitstempel/Kalender | EDT/EST-Wechsel, Feiertag (Thanksgiving), verkürzter Handelstag, Wochenende, naive Datetimes abgelehnt | ✅ |
| Look-Ahead | Merkmalstabelle kausal (identisch mit/ohne Zukunftsdaten); `compute_facts` identisch mit/ohne Zukunft; der Tagesbar der laufenden Session wird nie vom Provider übernommen; Analogien nur aus früheren Sessions, max. 1 pro Session; vorberechnete Merkmalstabelle liefert dieselben Ergebnisse | ✅ |
| Statistische Ehrlichkeit | Random Walk erzeugt keine „statistisch verwendbaren“ Analogien (≤ 2 von 8 Abfragen); Trade-Simulator ohne systematischen Bias auf driftfreiem Random Walk (600 Läufe, \|Ø R\| < 3 SE) | ✅ |
| Signal-Engine | Datenmangel → `insufficient_data`; Gleichlauf → Long mit Stop < Entry < Ziel, CRV ≥ 1,5; keine Evidenz → `no_trade`; MTF-Konflikt → Abstufung; schlechtes CRV → `watch`; After-Hours → nie sofortiger Entry; Invalidierung; Short-Spiegelung | ✅ |
| LLM | Striktes JSON-Schema (überall `additionalProperties: false`); Validator lehnt erfundene Kurse und Gewissheitsformulierungen ab, entfernt nicht wörtliche Zitate, lehnt unbekannte News-IDs ab; Client verarbeitet strukturierte Ausgabe, Refusal und ungültiges JSON; Kostenberechnung | ✅ (mit Fake-Client) |
| Provider | Alpaca: Paging, Header, `adjustment=all`, Feed, SIP-Verzögerung im Gratisplan, Daily-Labels, 429-Retry, 403-Abbruch, News-Parsing inkl. defekter Items, Stream-Nachrichten; SEC-Parsing; Demo deterministisch, OHLC-konsistent, gekennzeichnet | ✅ (gemockt, `respx`) |
| Persistenz/Cache | Kaltstart → DB → nur Tail-Abruf in neuem Prozess; Upsert-Idempotenz | ✅ SQLite + PostgreSQL |
| Unveränderbarkeit | ORM blockiert UPDATE/DELETE; PostgreSQL-Trigger blockiert rohes `UPDATE`/`DELETE` (manuell per `psql` verifiziert) | ✅ |
| Migrationen | `alembic upgrade head`, `alembic check` (Modelle = Migration), `downgrade base` | ✅ |
| API | Health (Demo-Modus sichtbar), Watchlist-CRUD + Validierung, Bars/Indikatoren, vollständige Analyse inkl. Speicherung, Reproduzierbarkeit (gleicher `input_hash`), Benachrichtigungs-Dedupe, Token-Schutz, Production-Guards | ✅ |
| Frontend | `tsc --noEmit`, 7 Unit-Tests (Zeitzonen, Formatierung, URL-Sanitizing), Produktions-Build; Playwright-Screenshots aller Bereiche ohne Konsolenfehler | ✅ |
| Docker | Compose-Stack (PostgreSQL, Migration, API, Worker, Web) gebaut und gestartet, Analyse über PostgreSQL erfolgreich | ✅* |
| Qualität | Ruff (Lint + Format), Mypy ohne Fehler | ✅ |

\* Im Build-Environment fängt ein Proxy TLS mit einer eigenen CA ab. Die Images wurden deshalb
mit einer temporären Dockerfile-Variante gebaut, die diese CA vertraut. Die Repository-Dockerfiles
selbst brauchen das nicht; bitte einmal lokal `docker compose up --build` ausführen.

## 2. Während der Validierung gefundene und behobene Fehler

| Fehler | Auswirkung | Behebung |
|---|---|---|
| Demo-Tagespfad wurde pro Tag neu erzeugt | inkonsistente Kurse, unrealistische Gaps (+29 % in 5 Tagen) | ein Pfad pro Symbol, getrennte Gap- und Intraday-Renditen |
| Brownian Bridge mit künstlicher Drift | Analogsuche „fand“ eine Kante in Zufallsdaten (70 % Treffer) | Bridge-Endpunkt aus derselben Verteilung wie ein freier Walk → keine Vorhersagbarkeit; Test ergänzt |
| Zonen-Clusterung verkettete Swings | eine Zone von 447 bis 1130 | Breitenlimit (2 × Toleranz) |
| `gap_atr` hing vom Vorhandensein des laufenden Tagesbars ab | Look-Ahead-Test schlug an | Lookup des letzten abgeschlossenen Vortags |
| Gleich hohe Hochs/Tiefs (Tick-Rundung) wurden nie als Swing erkannt | fehlende Struktur in echten Daten | erster Bar bei Gleichstand ist Pivot |
| `_narrative` gab teils Dict statt Tupel zurück | Absturz beim LLM-Fallback | per Mypy gefunden, korrigiert |
| ATR/RSI aus Extended Hours | „6,4 ATR über VWAP“ nach Börsenschluss | Intraday-Indikatoren nur auf RTH (ADR-0003) |
| Demo-Volumen nach 16:00 explodierte | falsche Volumenbalken | Begrenzung der Session-Minute |
| Watchlist am Wochenende: Veränderung/Volumen 0 | irreführende Übersicht | Bezug auf die letzte Session |
| VWAP über Nacht verbunden | optisch falsche Linie | Lücken + transparente Segmente (per Minimaltest verifiziert) |
| „R brutto“ enthielt bereits Kosten | falscher Kostenvergleich | Rohpreise in der Simulation, Kosten nur netto |
| Advisory Lock wurde sofort wieder freigegeben | mehrere Worker möglich | Verbindung bleibt für die Prozesslaufzeit offen |

## 3. Sicherheitsreview

| Thema | Befund | Maßnahme |
|---|---|---|
| Secrets | nur Env/`SecretStr`, `.env` gitignored, Redaction-Filter im Logger, leere Werte → `None` | gitleaks-Job in CI |
| API-Zugriff | ohne Auth, wenn `API_TOKEN` fehlt | Compose bindet nur `127.0.0.1`; `API_TOKEN` für jeden anderen Betrieb dokumentiert. `NEXT_PUBLIC_API_TOKEN` ist im Browser sichtbar → nur lokal |
| XSS über Provider-URLs | `javascript:`-URL im `href` wäre ausführbar gewesen | `safeUrl()` im Frontend + Filter bei der Speicherung |
| SQL-Injection | nur parametrisierte SQLAlchemy-Statements | – |
| Eingaben | Ticker-Regex, Enum-Timeframes, UUIDs, Grenzen für `days`/`limit` | – |
| DoS | Analyse kostet Sekunden CPU | Lock pro Symbol, 10-s-Schutz für manuelle Analysen, Cooldown im Monitor |
| Prompt-Injection | Nachrichtentexte gehen in den Prompt | LLM ohne Werkzeuge, Ausgabe validiert, keine Entscheidungsbefugnis |
| Container | – | Nicht-Root-User, keine Secrets in Images |
| Orderausführung | kein Code-Pfad vorhanden | Invariante in `CLAUDE.md` und PR-Template |

## 4. Nicht verifiziert (offen)

1. **Alpaca-Live-API** (Bars, News, WebSocket) – Implementierung nach Doku, getestet nur gemockt.
   Erster Test mit echten (kostenlosen) Keys ist P0 in der Roadmap.
2. **Anthropic-Live-Aufruf** – kein API-Key im Build-Environment; Client mit Fake getestet.
   Strukturierte Ausgabe und `fallbacks="default"` sind in der installierten SDK-Version (2.3.0)
   als Parameter vorhanden.
3. **SEC-EDGAR-Live-Abruf** – Parsing getestet, Live-Zugriff durch Netzwerk-Policy blockiert.
4. **Aussagekraft der Engine** – auf Demo-Daten **keine** (Zufallsprozess). Ein Vergleich mit den
   Baselines ist erst mit echten Daten und ausreichend vielen Live-Outcomes sinnvoll.

## 5. Beispiel: Backtest auf Demo-Daten

`python -m app.backtest --symbol AAPL --start 2026-10-12 --end 2026-10-16 --step 60 --provider demo`
läuft durch (30 Entscheidungen; davon 5 Trades der Engine, die übrigen `watch`/`no_trade`) und
liefert Baselines, Hälften- und Regime-Aufteilung. Auf simulierten Daten sind alle Strategien wie
erwartet negativ (Kosten, Zufallsprozess). Der Report trägt den Hinweis „DEMO-DATEN … keine
Aussagekraft“.
