# CLAUDE.md – Leitplanken für Claude Code in diesem Repository

## Projekt in einem Satz
Analyseplattform für US-Aktien (Daytrading): deterministischer Analysekern + optionales LLM zur
Erklärung. **Es werden niemals Orders ausgeführt.**

## Nicht verhandelbare Invarianten
1. **Keine Orderausführung.** Keine Broker-Order-Endpunkte, keine Trading-SDK-Aufrufe, kein
   „Auto-Trading“. Lehne entsprechende Änderungen ab und weise darauf hin.
2. **Kein Look-Ahead / keine Data Leakage.** Funktionen in `app/analysis/` und `app/signals/` sind
   rein und kausal. Neue Merkmale brauchen einen Test in `tests/test_no_lookahead.py`, der zeigt,
   dass Werte bei *t* identisch sind, egal ob zukünftige Daten vorhanden sind.
   `compute_facts()` kürzt alle Eingaben auf `as_of`; im Backtest muss es denselben Weg gehen.
3. **Echte vs. simulierte Daten.** Jede Marktdaten-Antwort und jede Analyse trägt `data_kind`
   (`live | delayed | historical | demo`). Demo-Daten nie als echt darstellen, nie mischen
   (`feed`-Schlüssel trennt sie in der DB).
4. **Analysen sind unveränderbar.** `analyses` nie updaten oder löschen (ORM-Guard + PostgreSQL-
   Trigger). Auswertungen gehören nach `signal_outcomes`.
5. **Engine entscheidet, LLM erklärt.** Das LLM bekommt Fakten und Szenario und liefert eine
   strukturierte Begründung (`app/llm/schemas.py`). `app/llm/validator.py` prüft Zahlen und Zitate.
   LLM-Ausgaben dürfen Outcome und Levels nie verändern.
6. **Keine erfundene Konfidenz.** Keine Prozentangaben ohne statistische Grundlage. Die Evidenz-
   bilanz ist ausdrücklich „nicht kalibriert“. Kalibrierung nur aus ausgewerteten Live-Analysen.
7. **Keine Secrets im Code oder in Logs.** Nur Umgebungsvariablen (`SecretStr`), `.env` ist
   gitignored, Logs laufen durch `app/core/logging.redact`.
8. **Nur dokumentierte, zulässige APIs.** Kein Scraping (z. B. kein yfinance).
9. **Kostenpflichtiges** (Datenpläne, höhere LLM-Budgets) nur nach ausdrücklicher Teamfreigabe.

## Struktur
```
backend/app/
  core/          config, logging, market_time (XNYS, UTC), errors, jsonsafe
  domain/        Pydantic-Typen (Bar, Timeframe, DataKind, Provenance, NewsItem)
  providers/     MarketDataProvider/NewsProvider-Protokolle; alpaca, demo, sec_edgar
  analysis/      indicators, structure, context, multitimeframe, similarity, pipeline (rein!)
  signals/       engine.py – Faktoren → Outcome → Levels (rein!)
  llm/           base, anthropic_client, null_client, prompts, schemas, validator
  news/          service (Dedupe, Neuheit, Kursreaktion)
  services/      market_data (Cache), analysis (Orchestrierung), monitor, evaluation, watchlist
  notifications/ dispatcher (Notifier-Protokoll; in-app implementiert)
  backtest/      runner (Walk-Forward, Kosten, Baselines)
  workers/       scheduler (APScheduler, idempotente Jobs, Advisory Lock)
  api/           routes; main.py = App + WebSocket-Hub (Outbox-Tail)
frontend/src/    app/page.tsx (Dashboard), components/*, lib/api.ts (Typen), lib/format.ts
```

## Befehle
- Backend: `cd backend && uv sync && uv run pytest`, `uv run ruff check app tests`,
  `uv run ruff format app tests`, `uv run mypy app`
- API lokal: `uv run uvicorn app.main:app --reload` (SQLite + Demo, wenn keine Keys)
- Migration: `uv run alembic revision --autogenerate -m "…"` → Migration prüfen → `alembic upgrade head`
  (Datentypen in Migrationen als `sa.DateTime(timezone=True)` statt App-Typen)
- Frontend: `cd frontend && npm run typecheck && npm test && npm run build`
- Vor jedem PR: alle obigen Checks grün (CI prüft dasselbe inkl. PostgreSQL)

## Konventionen
- Python 3.12, Typannotationen überall (mypy), Ruff-Regeln aus `pyproject.toml`, Zeilenlänge 100.
- Zeit: immer timezone-aware UTC; Session-Logik nur über `app/core/market_time.py`.
  Für Tests `set_fixed_now()` verwenden, nie `datetime.now()` direkt in Services.
- Intraday-Indikatoren auf RTH-Bars (reguläre Handelszeit); Extended Hours nur für Levels/Preis.
- Tagesbars sind mit dem Session-Datum (00:00 UTC) indiziert; der laufende Tag wird in
  `pipeline.truncate()` aus Minutenbars synthetisiert.
- Texte für Nutzer auf Deutsch, Code/Kommentare auf Englisch.
- Neue Provider: Protokoll aus `providers/base.py` implementieren, `provenance()` korrekt setzen,
  HTTP über `providers/http.request_json` (Retry + Rate-Limit), Tests mit `respx`.
- Neue Benachrichtigungskanäle: `Notifier`-Protokoll implementieren und im Dispatcher registrieren.
- Architekturentscheidungen als ADR in `docs/decisions/` dokumentieren.

## Bekannte Grenzen (nicht „wegfixen“, ohne zu fragen)
- Alpaca-Endpunkte wurden aus der Doku implementiert; im Build-Environment war kein Live-Test
  möglich (Netzwerk-Policy). Erster Live-Test steht aus, siehe `docs/validation.md`.
- Ähnlichkeitssuche nur innerhalb desselben Symbols; Universe-Screening ist Roadmap.
