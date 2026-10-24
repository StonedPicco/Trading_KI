# Phase 1 – Recherche: Datenanbieter, Datenquellen, Bibliotheken, LLMs

Stand: 2026-10-24

## Methodik und Einschränkungen (bitte zuerst lesen)

In der Entwicklungsumgebung, in der diese Recherche entstand, war **direkter HTTP-Zugriff auf die
Anbieter-Websites durch eine Netzwerk-Policy blockiert** (HTTP 403 am Proxy für massive.com,
alpaca.markets, finnhub.io, databento.com, sec.gov, stlouisfed.org). Die Recherche lief daher über
eine Websuche, die Ausschnitte aus offiziellen Seiten *und* Drittquellen liefert.

Kennzeichnung in diesem Dokument:

| Marker | Bedeutung |
|---|---|
| **[offiziell]** | Aussage stammt aus einem Ausschnitt der offiziellen Doku/Preisseite des Anbieters |
| **[Dritt]** | Aussage stammt nur aus Drittquellen (Vergleichsportale, Foren) – **nicht verifiziert** |
| **[unverifiziert]** | aus Vorwissen, nicht durch eine aktuelle Quelle bestätigt |

**Vor jeder kostenpflichtigen Entscheidung müsst ihr Preise, Limits und Lizenzbedingungen direkt
auf der Anbieterseite prüfen.** Preise ändern sich häufig; nichts in diesem Dokument ist eine
verbindliche Zusage.

---

## 1. Marktdatenanbieter (US-Aktien)

### 1.1 Vergleichstabelle

| Kriterium | Alpaca Market Data | Massive (ehem. Polygon.io) | Databento | Finnhub | Twelve Data | Interactive Brokers |
|---|---|---|---|---|---|---|
| **Kostenloser Plan** | Ja: „Basic/Free“ [offiziell] | Basic $0, nur EOD, 5 Calls/min [Dritt] | Startguthaben, kein Live-Gratis [unverifiziert] | Ja, ~60 Calls/min [Dritt] | Basic: 8 Credits/min, 800/Tag [offiziell] | Nur mit Brokerkonto |
| **Echtzeit im Gratisplan** | Ja, aber **nur IEX** (eine Börse, ~2–3 % des Volumens) [offiziell] | Nein | Nein | Real-time US-Quotes laut Drittquellen [Dritt] | Real-time US-Aktien laut Preisseite [offiziell], aber kaum Credits | Gratis-Streaming nur nicht-konsolidiert (Cboe One + IEX) [offiziell] |
| **Konsolidierte Echtzeit (SIP)** | Algo Trader Plus: **$99/Monat**, alle US-Börsen [offiziell] | Stocks Advanced: **$199/Monat**, Echtzeit [offiziell]; Developer $79 = 15 min verzögert [offiziell] | Standard-Plan ab **$199/Monat** inkl. Live-Daten, ohne Börsenlizenzgebühren [offiziell] | Bezahlpläne ~$50–500+/Monat [Dritt] | Pro **$229/Monat** (u. a. Pre/Post-Market, volles WebSocket) [offiziell] | Bundle ~USD 10/Monat (bei Aktivität erlassen) [offiziell, Spaltenzuordnung unklar] |
| **Historische Intraday-Daten** | Ja, Minutenbars; Gratisplan: **keine Abfrage der letzten 15 Min.** auf SIP [offiziell] | Developer: 10 Jahre Trades [offiziell]; Advanced 20+ Jahre [Dritt] | Sehr tief, Tick-Level, nutzungsbasiert [offiziell] | Je nach Plan eingeschränkt [Dritt] | Ja, credit-basiert | Ja, mit Pacing-Limits [unverifiziert] |
| **Historische Tiefe** | Bars seit ca. 2016 [unverifiziert] | 10–20+ Jahre je Plan [offiziell/Dritt] | Jahrzehnte, je Datensatz | Plan-abhängig | Plan-abhängig | Plan-abhängig |
| **WebSocket** | Ja; Gratis: **30 Symbole**, Bezahlt: unbegrenzt [offiziell] | Ja (Stocks WebSocket) [offiziell] | Ja (Live-API, Binärprotokoll) [offiziell] | Ja, Gratis ~50 Symbole [Dritt] | Gratis/Grow nur Trial-Credits; Pro voll [offiziell] | Ja (TWS/Gateway-API) |
| **REST-Limits** | Gratis **200/min**, Bezahlt **10 000/min** [offiziell] | Bezahlt „unbegrenzt“ [Dritt] | nutzungsbasiert | ~60/min gratis [Dritt] | 8/min gratis, 377/min Grow [offiziell] | Pacing-Regeln |
| **Pre/After-Market** | Ja (Extended Hours in Bars) [unverifiziert] | Ja [unverifiziert] | Ja | Plan-abhängig | Erst ab Pro [offiziell] | Ja |
| **Nachrichten** | **Ja, Benzinga-News** über REST (seit 2015) + WebSocket, 130+ Artikel/Tag [offiziell] | News-Endpunkt vorhanden [offiziell] | Nein (nur Marktdaten) | Company News, Earnings-Kalender gratis [Dritt] | eingeschränkt | Ja (kostenpflichtige Feeds) |
| **Splits/Dividenden** | `adjustment`-Parameter (raw/split/dividend/all); Foren melden vereinzelt Fehler [Dritt] | Adjusted-Flag [unverifiziert] | Corporate-Actions-Daten separat | – | – | – |
| **Lizenz private Nutzung** | Datenplan braucht mind. ein (kostenloses) Paper-Konto [Dritt/Forum]; Alpaca ist in 29 EWR-Ländern inkl. **Österreich** passported [offiziell], ob Privatkonten aus AT möglich sind: **unbestätigt** | Individual-Pläne für nicht-professionelle Nutzung [Dritt] | Non-Pro-Status wird pro Datensatz abgefragt [offiziell] | „Personal use“ im Gratisplan [Dritt] | Individual-Pläne: persönlich, nicht kommerziell [offiziell] | Non-Pro-Definition klar [offiziell], aber Brokerkonto + Mindestaktivität nötig |
| **API-Komplexität** | Gering (REST + JSON-WS) | Gering | Mittel–hoch (DBN-Format, Schema-Wissen) | Gering | Gering | **Hoch** (lokales TWS/Gateway, Session-Handling) |

Quellen: siehe Abschnitt 6.

### 1.2 Bewertung

* **Alpaca** ist für den MVP die stärkste Option: kostenloser Einstieg mit **echter Echtzeit (IEX)**,
  dokumentierte REST- und WebSocket-API, historische Minutendaten, **Nachrichten im selben Konto**
  und ein klarer Upgrade-Pfad auf konsolidierte SIP-Daten für $99/Monat. Wichtigster Haken: IEX ist
  eine einzelne Börse. Absolute Volumina sind deshalb nicht repräsentativ; relative Kennzahlen wie
  RVOL bleiben aussagekräftig, solange **konsequent ein Feed** verwendet wird (→ ADR-0003).
* **Massive (Polygon)** hat sehr gute historische Tiefe und eine saubere API. Echtzeit gibt es aber
  erst ab $199/Monat, darunter nur verzögerte Daten. Massive ist der beste Kandidat als **zweiter
  Anbieter** für Backtests mit langer Historie (Developer, $79, 10 Jahre, 15 Min. verzögert).
* **Databento** liefert die höchste Datenqualität (Tick-Level, institutionell). Für zwei Entwickler
  mit privatem Budget ist das im MVP Overkill; interessant wird es später für präzise Backtests mit
  echten Spreads.
* **Finnhub**: brauchbarer kostenloser **Earnings-Kalender und Company News** als zweite
  Nachrichtenquelle. Die Marktdaten-Bedingungen sind nur über Drittquellen belegt, deshalb setzen
  wir Finnhub dafür nicht ein.
* **Twelve Data**: Der Gratisplan (8 Credits/min) reicht für Live-Monitoring nicht; Pre/Post-Market
  gibt es erst ab $229. Für uns schlechteres Preis-Leistungs-Verhältnis als Alpaca.
* **Interactive Brokers**: Daten sind günstig, wenn man ohnehin bei IBKR handelt. Die API
  (TWS/Gateway lokal, Pacing) ist für eine Server-Plattform aufwendig. Das kann später als optionaler
  Adapter kommen.

### 1.3 Entscheidung

→ **ADR-0002**: Alpaca Market Data als primärer Anbieter. Start im Gratisplan mit IEX-Feed, Upgrade
auf Algo Trader Plus (SIP) **nur nach eurer ausdrücklichen Freigabe**. Die Anbieter-Schnittstelle
ist abstrahiert (`MarketDataProvider`), Massive/Databento können später als Adapter dazukommen.

Ohne API-Keys läuft das System mit einem **deterministischen Demo-Provider** (synthetische Daten).
Diese Daten sind technisch markiert (`data_kind = "demo"`); das Dashboard zeigt dann einen
dauerhaften Warnbanner.

---

## 2. Weitere Datenquellen

| Bereich | Quelle | Kosten | Status im MVP | Hinweise |
|---|---|---|---|---|
| Unternehmensnachrichten | Alpaca News API (Benzinga) | im Alpaca-Konto enthalten [offiziell] | **implementiert** | REST + WebSocket, Historie ab 2015 |
| SEC-Filings (8-K, 10-Q, 10-K) | SEC EDGAR `data.sec.gov` | kostenlos | **implementiert** (8-K/10-Q/10-K-Liste) | Fair Access: max. **10 Requests/s**, **User-Agent mit Kontakt-E-Mail Pflicht** [offiziell] |
| Earnings-Kalender | Finnhub `/calendar/earnings` | Gratisplan [Dritt] | Schnittstelle vorbereitet (Roadmap) | Konditionen vor Nutzung prüfen |
| Makrodaten (CPI, Zinsen, Arbeitsmarkt) | FRED API (St. Louis Fed) | kostenlos, API-Key | Roadmap P1 | ~120 Requests/min laut Drittquellen [Dritt] |
| Zentralbankentscheidungen | FRED (Leitzins-Serien), Fed-Pressemitteilungen (RSS) | kostenlos | Roadmap P1 | nur dokumentierte Feeds, kein Scraping |
| Wirtschaftskalender | Finnhub Economic Calendar (vermutlich Premium) [Dritt] | ? | Roadmap P2 | Verfügbarkeit ungeklärt |
| Unternehmenskennzahlen | SEC `companyfacts` (XBRL) | kostenlos | Roadmap P1 | offizielle, geprüfte Zahlen |
| Analystenerwartungen | Finnhub/Massive (meist Premium) | kostenpflichtig | Roadmap P2 | nur bei klarer Lizenz |
| Vergleichsindizes | SPY, QQQ, Sektor-ETFs (XLK, XLF, …) über denselben Marktdatenanbieter | wie Marktdaten | **implementiert** (Relative Stärke vs. SPY + Sektor-ETF) | ETFs als Proxy für die Indizes |
| Börsenkalender | `exchange_calendars` (XNYS) | Open Source | **implementiert** | Feiertage, verkürzte Handelstage |

**Ausgeschlossen:** Yahoo Finance (`yfinance`) und ähnliche inoffizielle Endpunkte. Sie sind nicht
dokumentiert und für automatisierten Zugriff nicht lizenziert. Das widerspricht unserer Regel
„nur zulässige, dokumentierte Schnittstellen“.

---

## 3. LLM-Auswahl

Anforderungen: zuverlässige strukturierte Ausgabe (JSON-Schema), gutes Leseverständnis für
Finanztexte, nachvollziehbare Begründungen, Kostenkontrolle, austauschbar.

| Modell (Anthropic, Stand Okt. 2026) | Input $/MTok | Output $/MTok | Einsatz |
|---|---|---|---|
| Claude Opus 5.5 (`claude-opus-5-5`) | 4,00 | 20,00 | **Standard** für Analyse-Synthese und News-Bewertung |
| Claude Sonnet 5.5 (`claude-sonnet-5-5`) | 2,00 | 10,00 | Option bei hohem Volumen |
| Claude Haiku 5.5 (`claude-haiku-5-5`) | 0,10 | 0,50 | Option für News-Vorklassifikation (sehr günstig) |

Preise laut Anthropic-SDK-Referenz (Cache-Stand 2026-10-06), vor Produktivbetrieb auf der
offiziellen Preisseite prüfen.

Entscheidung → **ADR-0004**:

* Das LLM steckt hinter einem Interface (`LLMClient`). Implementiert sind ein Anthropic-Client und
  ein `NullLLMClient`, der ohne Key deterministische Texte aus den berechneten Fakten erzeugt.
  Weitere Anbieter (OpenAI, lokale Modelle über Ollama) brauchen nur einen neuen Adapter.
* Das Modell ist per Umgebungsvariable wählbar. Standard ist `claude-opus-5-5`. Ob für die
  News-Klassifikation aus Kostengründen auf Haiku gewechselt wird, entscheidet ihr.
* **Das LLM entscheidet nie über das Setup.** Es bekommt die vom deterministischen Engine
  berechneten Fakten und schreibt Begründung und Szenarien. Jede Ausgabe wird per JSON-Schema
  und Pydantic validiert. Zusätzlich prüft das System, ob jede genannte Zahl in den Eingabefakten
  vorkommt und jedes zitierte „Faktum“ wörtlich im Nachrichtentext steht.

---

## 4. Bibliotheken & Frameworks

| Bereich | Gewählt | Alternativen geprüft | Begründung |
|---|---|---|---|
| API | FastAPI + Pydantic v2 | – | Vorgabe, async, WebSockets, OpenAPI |
| DB | PostgreSQL 16 + SQLAlchemy 2 (async) + Alembic | TimescaleDB | Timescale erst bei >100 Mio. Bars nötig, Migration später möglich |
| Hintergrundjobs | APScheduler 3 im Worker-Prozess + Postgres-Outbox | Celery/RQ (bräuchten Redis), Dramatiq | Keine zusätzliche Infrastruktur; Idempotenz über DB-Constraints |
| Börsenkalender | `exchange_calendars` (XNYS) | `pandas_market_calendars` (spiegelt dieselben Kalender) | Direkte Quelle, gut gepflegt |
| Indikatoren | **Eigene, getestete NumPy/pandas-Implementierung** | TA-Lib (C-Abhängigkeit, unter Windows mühsam), `pandas-ta` | Volle Kontrolle über Definition (z. B. Wilder-RSI, sitzungsbasierter VWAP), keine nativen Builds |
| Ähnlichkeitssuche | scikit-learn (`NearestNeighbors`, Robust-Scaling) + eigene DTW-Nachsortierung | `tslearn`, `stumpy` | Merkmalsbasiert + Regime-Filter wichtiger als reine Formähnlichkeit; DTW nur für Top-k |
| Backtesting | **Eigenes, schlankes Walk-Forward-Modul** | vectorbt (schnell, vektorisiert), backtesting.py (einfach, Einzelwert), NautilusTrader (ereignisgetrieben, steile Lernkurve) | Wir testen *Analyse-Szenarien* (Entry-Zone, Stop, Ziele, „kein Trade“), keine Parameter-Strategien. Dieselbe Engine-Funktion muss live und im Backtest laufen, dafür ist ein eigener Replayer am sichersten. vectorbt bleibt Option für Parameter-Sweeps (→ ADR-0006) |
| Frontend | Next.js (App Router) + TypeScript | Vite + React | Vorgabe; Routing und Build sind enthalten |
| Charts | TradingView Lightweight Charts **5.2.1** (npm) | ECharts, Highcharts Stock | Apache-2.0, **Attribution an TradingView ist Pflicht** (Logo-Option `attributionLogo` aktiv lassen) [offiziell] |
| Qualität | pytest, Ruff, Mypy, GitHub Actions | – | Vorgabe |

---

## 5. Kostenabschätzung (monatlich, privat, Österreich)

| Posten | MVP (Gratis) | Empfohlen „ernsthaftes Daytrading“ |
|---|---|---|
| Marktdaten | Alpaca Basic (IEX): **$0** | Alpaca Algo Trader Plus (SIP): **$99** |
| Historische Tiefe für Backtests | Alpaca (ab ca. 2016 [unverifiziert]) | optional Massive Developer **$79** |
| News | Alpaca/Benzinga: $0 | $0 |
| SEC/FRED | $0 | $0 |
| LLM | $0 (Null-Client) | siehe unten |
| Hosting | lokal $0 | kleiner VPS ca. €10–30 [Schätzung] |

**LLM-Budget (Schätzung):** Eine Analyse-Synthese hat etwa 6 000 Input- und 1 500 Output-Token.
Mit Opus 5.5 kostet das ca. 6 000 × $4/1M + 1 500 × $20/1M ≈ **$0,054 pro Analyse**.
Bei 10 Aktien und 15 getriggerten Analysen pro Aktie und Handelstag sind das ≈ $8/Tag ≈
**$170/Monat** (21 Handelstage). Deshalb gibt es ein hartes Tagesbudget (`LLM_DAILY_BUDGET_USD`),
Caching per Input-Hash und Trigger-Deduplizierung. Mit Haiku 5.5 als News-Vorfilter sinken die
Kosten deutlich.

Österreich: Die Preise sind in USD; es können Umsatzsteuer und Währungsgebühren hinzukommen.
Für die steuerliche Behandlung ist ein Steuerberater zuständig.

---

## 6. Quellen

Marktdaten:
- Alpaca – About Market Data API: https://docs.alpaca.markets/docs/about-market-data-api
- Alpaca – Historical News Data: https://docs.alpaca.markets/us/docs/historical-news-data
- Alpaca – EEA-Passporting (29 Länder): https://alpaca.markets/blog/alpaca-completes-eea-passporting-to-29-countries-expanding-access-to-regulated-investment-services-across-europe/
- Alpaca Forum – Market Data API ohne Trading-Konto: https://forum.alpaca.markets/t/market-data-api-without-trading-account/6069
- Alpaca Forum – Split-Adjustierung: https://forum.alpaca.markets/t/v2-api-bars-request-adjustment-not-working/12893
- Massive – Full Market Snapshot (Planstufen/Latenz): https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot
- Massive – Trades: https://massive.com/docs/rest/stocks/trades-quotes/trades
- Massive – WebSocket Overview: https://massive.com/docs/websocket/stocks/overview
- Massive Preise (Drittquelle): https://costkite.com/tools/massive-formerly-polygon-io
- Databento – US Equities: https://databento.com/catalog/us-equities
- Databento – Introducing US Equities: https://databento.com/blog/introducing-databento-us-equities
- Databento – Live data: https://databento.com/docs/portal/live-data
- Twelve Data – Pricing: https://twelvedata.com/pricing.md
- Twelve Data – Credits: https://support.twelvedata.com/en/articles/5615854-credits
- Interactive Brokers – Market Data Pricing: https://www.interactivebrokers.com/en/pricing/market-data-pricing.php
- Finnhub (Drittquellen): https://nexusfi.com/d/data-providers/finnhub/ , https://apicostcalc.com/finnhub.html

Weitere Datenquellen:
- SEC – Accessing EDGAR Data: https://www.sec.gov/os/accessing-edgar-data
- FRED (Drittquelle zu Limits): https://cran.r-project.org/web/packages/fredr/news/news.html

Bibliotheken:
- Lightweight Charts v5: https://www.tradingview.com/blog/en/tradingview-lightweight-charts-version-5-50837
- pandas_market_calendars: https://pandas-market-calendars.readthedocs.io/en/latest/index.html
- exchange_calendars: https://pypi.org/project/exchange-calendars/
- Backtesting-Vergleich (Sekundärquelle): https://algolab.co.kr/blog/python-backtesting-library-comparison-2026
