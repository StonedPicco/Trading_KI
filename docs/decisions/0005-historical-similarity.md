# ADR-0005: Historische Analogsuche

**Status:** akzeptiert · **Datum:** 2026-10-24

## Kontext
Rein optische Chartähnlichkeit (z. B. nur DTW auf Kursen) ignoriert Volatilität, Tageszeit,
Volumen und Regime. Überlappende oder zu kleine Stichproben erzeugen Scheinsignifikanz.

## Entscheidung
- Merkmalsvektor je abgeschlossenem 5-Min-RTH-Bar: Renditen 5/15/30/60 Min. in ATR, VWAP-Abstand,
  Position in der Tagesrange, log-RVOL, Gap in Tages-ATR, EMA-Steigung, RSI. Alle kausal berechnet.
- Kandidaten nur aus **früheren Sessions** (Embargo), Tageszeit ±30 Min., gleiches
  Volatilitätsregime, sofern genug Sessions vorhanden sind.
- Robust-Skalierung auf den Kandidaten, gewichtete euklidische Distanz, Top-k mit
  DTW-Nachsortierung (70/30), **max. ein Analog pro Session**.
- Statistik: Wilson-95%-KI der Trefferquote gegen die Basisrate des Kandidatenfensters.
  „Statistisch verwendbar“ erst bei n ≥ 30, KI schließt die Basisrate aus und Match-Qualität < 0,6.
  Die Mehrfachtest-Problematik wird angezeigt.

## Konsequenzen
+ Verhindert Leakage (getestet), ehrliche Darstellung, in der Regel „deskriptiv“.
− Nur Historie desselben Symbols; symbolübergreifende Analogien sind Roadmap.
