# Anforderungen

Legende Status: ✅ im MVP umgesetzt · 🟡 teilweise / vereinfacht · ⏳ Roadmap

## 1. Funktionale Anforderungen

### F1 Marktdaten
| ID | Anforderung | Status | Umsetzung / Anmerkung |
|---|---|---|---|
| F1.1 | Frei wählbare US-Aktie | ✅ | Watchlist, Symbolvalidierung |
| F1.2 | Echte historische OHLCV-Daten | ✅ | Alpaca Bars (`adjustment=all`), DB-Cache |
| F1.3 | Neue Marktdaten über dokumentierte API | ✅ | REST-Refresh pro Minute; WebSocket-Client vorhanden (`ALPACA_USE_STREAM`), Einbindung in Worker ⏳ |
| F1.4 | Pre-/After-Market | ✅ | Extended-Hours-Bars, Marktphasen, PMH/PML |
| F1.5 | Echtzeit vs. verzögert unterscheidbar | ✅ | `Provenance` in jeder Antwort |
| F1.6 | Demo-/Testdaten technisch unterscheidbar | ✅ | `data_kind=demo`, eigener `feed`, Banner |
| F1.7 | Mehrere Datenanbieter | 🟡 | Interface vorhanden, ein Live-Adapter (Alpaca) |

### F2 Analyse
| ID | Anforderung | Status | Anmerkung |
|---|---|---|---|
| F2.1 | Multi-Timeframe 1m–1W | ✅ | Resampling aus 1m/1D, Trend je TF |
| F2.2 | MTF-Konflikte erkennen | ✅ | Tages- vs. Intraday-Trend, Nähe zu HTF-Widerstand |
| F2.3 | S/R-Zonen, Swing-Struktur, HH/HL | ✅ | Clusterung ohne Verkettung |
| F2.4 | Trendlinien / Trendkanäle | ⏳ | Zonen + Struktur statt Linien im MVP |
| F2.5 | VWAP, EMA/SMA, RSI, MACD, ATR, BB | ✅ | Eigene, getestete Implementierung |
| F2.6 | RVOL, Volumenspitzen | ✅ | Tageszeitbereinigt |
| F2.7 | Gaps, Breakouts, False Breakouts | ✅ | Volumenbestätigung |
| F2.8 | Momentum(-verlust), Überdehnung | ✅ | RSI-Divergenz, VWAP-Abstand in ATR |
| F2.9 | Volatilitätsregime | ✅ | ATR%-Perzentil 1 Jahr |
| F2.10 | Relative Stärke Markt/Sektor | ✅ | SPY + Sektor-ETF |
| F2.11 | Liquidität | ✅ | Ø Dollar-Volumen (IEX-skaliert) |
| F2.12 | Fakten vs. Interpretation trennen | ✅ | Jeder Faktor: `observation` + `interpretation` |

### F3 Historische Mustererkennung
| ID | Anforderung | Status | Anmerkung |
|---|---|---|---|
| F3.1 | Ähnliche Situationen finden | ✅ | Merkmals-kNN + DTW-Nachsortierung |
| F3.2 | Regime, Tageszeit, Liquidität, Trend berücksichtigen | ✅/🟡 | Regime + Tageszeit als Filter, Trend/RVOL als Merkmale; Nachrichtenlage ⏳ |
| F3.3 | Renditeverteilung 5/15/30/60, MFE/MAE, Trefferquote | ✅ | inkl. Wilson-KI und Basisrate |
| F3.4 | Wahrscheinlichkeit nur bei statistischer Validität | ✅ | n ≥ 30, KI ≠ Basis, Match-Qualität |
| F3.5 | Look-Ahead/Leakage/Survivorship/Overfitting vermeiden | ✅/🟡 | Tests für Kausalität; Survivorship erst bei Universen relevant ⏳ |
| F3.6 | Corporate Actions | 🟡 | `adjustment=all`; automatischer Neuabruf nach Splits ⏳ |

### F4 News Intelligence
| ID | Anforderung | Status | Anmerkung |
|---|---|---|---|
| F4.1 | Neue Meldungen automatisch erkennen | ✅ | Worker alle 2 Min. |
| F4.2 | Betroffene Ticker, Zeitstempel, Quelle | ✅ | |
| F4.3 | Neuheit/Duplikate | ✅ | Hash + Jaccard |
| F4.4 | Kursreaktion + Volumenbestätigung | ✅ | gemessen, nicht vom LLM |
| F4.5 | LLM-Einordnung, wörtliche Fakten | ✅ | Validator entfernt nicht belegte Zitate |
| F4.6 | Makro, Zentralbanken, Earnings-Kalender | ⏳ | FRED / Finnhub geplant |

### F5 Signal-Engine
| ID | Anforderung | Status |
|---|---|---|
| F5.1 | 8 Ergebnisklassen inkl. „kein Trade“ und „Daten unzureichend“ | ✅ |
| F5.2 | Entry-Zone, Bestätigung, Stop, Ziele, CRV, Invalidierung | ✅ |
| F5.3 | Pro-/Contra-Argumente, Kontext, Zusammenfassung | ✅ |
| F5.4 | Historische Einordnung inkl. Einschränkungen | ✅ |
| F5.5 | Konfidenz nur kalibriert | ✅ (bewusst noch nicht angezeigt) |

### F6 Dashboard
| ID | Anforderung | Status |
|---|---|---|
| F6.1 | Watchlist mit Kurs, %, Volumen, RVOL, Signal, News | ✅ |
| F6.2 | Interaktiver Chart, Timeframes, Indikatoren, Zonen, Entry/Stop/Ziel, Signalmarker | ✅ |
| F6.3 | AI-Analyst-Panel inkl. Quellen und Zeitstempel | ✅ |
| F6.4 | News-Panel | ✅ |
| F6.5 | Historische Analyse mit Statistik und Visualisierung | ✅ |
| F6.6 | Signal History mit Ergebnisauswertung | ✅ |
| F6.7 | Automatische Aktualisierung | ✅ (WebSocket + 60-s-Fallback) |

### F7 Automatisierung
| ID | Anforderung | Status |
|---|---|---|
| F7.1 | Trigger: Level-Bruch, Volumen, Relativbewegung, News, Invalidierung, Setup | ✅ |
| F7.2 | Keine Doppelanalysen / kein Spam | ✅ Cooldown + UNIQUE `dedupe_key` |
| F7.3 | In-App-Benachrichtigungen | ✅ |
| F7.4 | Telegram/Discord/E-Mail/Push erweiterbar | ✅ Interface, Kanäle ⏳ |

### F8 Backtesting & Qualität
| ID | Anforderung | Status |
|---|---|---|
| F8.1 | Reproduzierbare historische Simulation | ✅ |
| F8.2 | Walk-Forward / Out-of-Sample | ✅ (parameterfreie Engine; Embargo) |
| F8.3 | Spreads, Slippage, Kosten | ✅ (bps-Annahmen) |
| F8.4 | Liquiditätsbedingungen | 🟡 (Warnung; keine Füllmodellierung nach Volumen) |
| F8.5 | Marktphasen-Vergleich | ✅ (Hälften, Volatilitätsregime) |
| F8.6 | Baselines | ✅ (Random, Momentum, immer Long) |
| F8.7 | Unveränderbare Live-Analysen + nachträgliche Auswertung | ✅ |

## 2. Nicht-funktionale Anforderungen

| Bereich | Anforderung | Umsetzung |
|---|---|---|
| Sicherheit | Secrets nur per Env, keine Klartext-Abfragen | `SecretStr`, Redaction, gitleaks in CI |
| Sicherheit | API nicht offen | Ports nur `127.0.0.1`, optionales `API_TOKEN`, CORS-Whitelist |
| Robustheit | Rate-Limits, Lücken, Abbrüche | Token-Bucket, Retry/Backoff, Lückenprüfung, WS-Reconnect |
| Zeit | Zeitzonen, Börsenkalender | UTC-Speicherung, XNYS-Kalender, DST-Tests |
| Betrieb | Strukturierte Logs | JSON-Logs |
| Betrieb | Idempotente Jobs | Upserts, UNIQUE-Constraints, `max_instances=1`, Advisory Lock |
| Kosten | LLM-/Datenkosten kontrollieren | Tagesbudget, Cache, Cooldown; Gratis-Datenplan als Default |
| Umgebungen | dev/test/prod getrennt | `APP_ENV`, Production-Guards (kein Demo, separater Worker, PostgreSQL) |
| Plattformen | Windows + macOS | Reines Python/Node, kein nativer Build (kein TA-Lib), Docker optional |
