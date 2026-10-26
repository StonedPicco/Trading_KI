# ATI – AI Stock Trading Intelligence Platform

KI-gestützte Analyseplattform für US-Aktien im Daytrading. Sie sammelt Marktdaten, Nachrichten und
SEC-Filings und kombiniert Multi-Timeframe-Technik, Marktstruktur, Markt- und Sektorkontext mit
historischen Vergleichssituationen. Daraus erstellt sie **nachvollziehbare Szenarien**: Long,
Short, Beobachten oder ausdrücklich *kein Trade*.

> **Keine Orderausführung.** Die Plattform liefert ausschließlich Analysen, Szenarien und
> Entscheidungshilfen. Es gibt keinen Code-Pfad zu einer Broker-Order-API. Keine Anlageberatung.

![Status](https://img.shields.io/badge/status-MVP-blue)

## Was das MVP kann

| Bereich | Umfang |
|---|---|
| Marktdaten | Alpaca Market Data (IEX gratis/Echtzeit oder SIP), REST mit Paging, Rate-Limit, Retries; WebSocket-Stream-Client; DB-Cache |
| Demo-Modus | Ohne Keys: deterministische, **klar als SIMULIERT gekennzeichnete** Daten (Banner, `data_kind=demo` in jeder Antwort) |
| Charts | Kerzen 1m/5m/15m/1h/1D/1W, EMA 20/50, VWAP, Bollinger, RSI, MACD, Volumen, S/R-Zonen, Entry/Stop/Ziele, Signalmarker |
| Analyse | Trend und Struktur (HH/HL/LH/LL) je Timeframe, MTF-Konflikte, Zonen, PDH/PDL/PMH/PML, Gaps, Breakouts/False Breakouts, RVOL (tageszeitbereinigt), Divergenzen, Überdehnung, Volatilitätsregime, relative Stärke vs. SPY/Sektor-ETF, Liquidität, Datenqualität |
| Historie | Analogsuche (merkmalsbasiertes kNN + DTW, Regime- und Tageszeitfilter, Embargo, 1 Analog/Session) mit Renditeverteilung 5/15/30/60 Min., MFE/MAE, Wilson-KI vs. Basisrate |
| Signale | Deterministische Engine: 8 Ergebnisklassen, Pro/Contra-Faktoren, Entry-Zone, Stop, Ziele, CRV, Bestätigungs- und Invalidierungsbedingungen |
| KI | Austauschbares LLM-Interface (Anthropic Claude implementiert), strukturierte Ausgabe, Validator (Zahlen müssen belegt sein, Zitate wörtlich), Tagesbudget, Cache; ohne Key deterministische Begründung |
| News | Alpaca/Benzinga-News + SEC-EDGAR-Filings, Dedupe, Neuheitsprüfung, gemessene Kursreaktion (Rendite/RVOL vs. SPY) |
| Nachvollziehbarkeit | Jede Analyse wird **unveränderbar** gespeichert (DB-Trigger) mit Datenstand, Quellen, Input-Hash, Engine- und Modellversion |
| Qualität | Automatische Auswertung gespeicherter Analysen (15/60/240 Min.) gegen Baselines; Walk-Forward-Backtest mit Spread/Slippage |
| Automatisierung | Worker mit Triggern (Level-Bruch, Volumenspitze, Relativbewegung, News, Invalidierung, Setup), Cooldown, Dedupe; In-App-Benachrichtigungen per WebSocket |

## Schnellstart

### Variante 0 – Doppelklick (ohne Vorkenntnisse)

1. Auf GitHub **Code → Download ZIP** klicken und die ZIP-Datei entpacken.
2. Im entpackten Ordner doppelklicken auf:
   - **Windows:** `Start.bat`
   - **macOS:** `Start.command` (beim ersten Mal: Rechtsklick → „Öffnen“ → „Öffnen“ bestätigen)
   - **Linux:** `./start.sh`
3. Beim **ersten Start** fragt das Fenster einmalig nach den Alpaca-Keys (API Key ID und Secret).
   Sie werden nur lokal in `config/alpaca.env` gespeichert. Leer lassen = Demo-Modus.
4. Der erste Start dauert einige Minuten (Python und Pakete werden automatisch installiert),
   danach öffnet sich das Dashboard im Browser: http://127.0.0.1:8000

Das Fenster muss offen bleiben, solange ihr die Plattform nutzt; Schließen beendet sie.
Voraussetzung ist nur eine Internetverbindung, Node.js oder Docker werden nicht benötigt.

### Variante A – Docker Compose

```bash
cp .env.example .env          # optional: Alpaca-Keys eintragen, sonst Demo-Modus
docker compose up --build
```

Dashboard: http://localhost:3000 · API-Doku: http://localhost:8000/docs

### Variante B – lokal ohne Docker (Windows & macOS)

Voraussetzungen: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
# Backend (SQLite, Worker läuft im API-Prozess)
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000

# Frontend (zweites Terminal)
cd frontend
npm ci
npm run dev
```

Windows (PowerShell): dieselben Befehle; `cp` → `Copy-Item .env.example .env`.

### Echte Marktdaten aktivieren (kostenlos)

1. Bei Alpaca ein **kostenloses Paper-Konto** anlegen (keine Einzahlung nötig) und API-Keys erzeugen.
2. In `.env` eintragen: `ALPACA_API_KEY_ID=…`, `ALPACA_API_SECRET_KEY=…`
3. Optional für SEC-Filings: `SEC_USER_AGENT="Name kontakt@email"`.
4. Optional KI-Begründungen: `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=…`, Budget über
   `LLM_DAILY_BUDGET_USD` begrenzen.

Der Gratisplan liefert Echtzeitdaten **nur von IEX** (Teil des Gesamtvolumens); das Dashboard
zeigt diesen Hinweis an. Für konsolidierte Echtzeitdaten gibt es Alpaca Algo Trader Plus
(kostenpflichtig, **nur nach Teamfreigabe**), siehe [docs/research.md](docs/research.md).

## Wichtige Befehle

| Zweck | Befehl |
|---|---|
| Backend-Tests | `cd backend && uv run pytest` |
| Tests auch gegen PostgreSQL | `TEST_DATABASE_URL=postgresql+asyncpg://… uv run pytest` |
| Lint / Format / Typen | `uv run ruff check app tests && uv run ruff format app tests && uv run mypy app` |
| Migration anwenden | `DATABASE_URL=postgresql+asyncpg://… uv run alembic upgrade head` |
| Neue Migration | `uv run alembic revision --autogenerate -m "…"` |
| Worker separat | `uv run python -m app.workers.scheduler` |
| Backtest | `uv run python -m app.backtest --symbol AAPL --start 2026-09-01 --end 2026-10-15 --provider auto` |
| Frontend prüfen | `cd frontend && npm run typecheck && npm test && npm run build` |
| Dashboard für den Doppelklick-Start neu bauen | `cd frontend && npm run build:web` (Ergebnis `web/` committen) |

## Dokumentation

- [docs/research.md](docs/research.md) – Phase 1: Anbieter- und Technologievergleich, Kosten
- [docs/architecture.md](docs/architecture.md) – Phase 2: Architektur, Datenfluss, DB-Modell, API, Pipelines
- [docs/requirements.md](docs/requirements.md) – Anforderungen und MVP-Status
- [docs/roadmap.md](docs/roadmap.md) – Phase 5: priorisierter Ausbau
- [docs/validation.md](docs/validation.md) – Phase 4: Validierung, gefundene Fehler, Sicherheitsreview
- [docs/development.md](docs/development.md) – Zusammenarbeit, Branching, Konventionen
- [docs/decisions/](docs/decisions/) – Architecture Decision Records
- [CLAUDE.md](CLAUDE.md) – Leitplanken für die Arbeit mit Claude Code

## Grundsätze

1. **Keine erfundenen Daten.** Fehlt eine Quelle, sagt das System das. Demo-Daten sind immer markiert.
2. **Engine entscheidet, LLM erklärt.** LLM-Ausgaben werden validiert und können Setups nicht ändern.
3. **Kein Look-Ahead.** Jede Berechnung zum Zeitpunkt *t* nutzt nur Daten ≤ *t*; dafür gibt es Tests.
4. **Keine Pseudo-Konfidenz.** Wahrscheinlichkeiten erscheinen nur bei ausreichender, out-of-sample
   validierter Stichprobe; sonst sind sie als deskriptiv markiert.
5. **„Kein Trade“ ist ein gültiges Ergebnis.**

## Lizenzhinweise

Charts: [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/)
(Apache-2.0). Die TradingView-Attribution im Chart ist laut Lizenz erforderlich und bleibt aktiv.
