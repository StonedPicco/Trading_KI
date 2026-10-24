# Architecture Decision Records

Format: Kontext → Entscheidung → Konsequenzen. Neue ADRs fortlaufend nummerieren; bestehende
nicht umschreiben, sondern durch ein neues ADR ersetzen (Status „ersetzt durch …“).

| Nr. | Titel | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modularer Monolith: API + Worker, eine Codebasis | akzeptiert |
| [0002](0002-market-data-alpaca.md) | Alpaca als primärer Marktdatenanbieter, Demo-Provider ohne Keys | akzeptiert |
| [0003](0003-single-feed-consistency.md) | Ein Feed pro Analyse (IEX *oder* SIP), RTH-basierte Intraday-Indikatoren | akzeptiert |
| [0004](0004-llm-explains-engine-decides.md) | Deterministische Engine entscheidet, LLM erklärt (validiert) | akzeptiert |
| [0005](0005-historical-similarity.md) | Analogsuche: Merkmals-kNN + DTW, Embargo, Wilson-KI vs. Basisrate | akzeptiert |
| [0006](0006-backtesting.md) | Eigener Walk-Forward-Replayer statt Framework | akzeptiert |
| [0007](0007-postgres-outbox-no-redis.md) | PostgreSQL + Outbox statt Redis/Celery | akzeptiert |
| [0008](0008-no-uncalibrated-confidence.md) | Keine unkalibrierte Konfidenz; Kalibrierung nur aus Live-Outcomes | akzeptiert |
| [0009](0009-immutable-analyses.md) | Analysen unveränderbar (ORM-Guard + DB-Trigger) | akzeptiert |
