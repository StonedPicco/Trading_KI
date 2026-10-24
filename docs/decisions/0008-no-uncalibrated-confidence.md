# ADR-0008: Keine unkalibrierte Konfidenz

**Status:** akzeptiert · **Datum:** 2026-10-24

## Entscheidung
- Die Engine zeigt eine **Evidenzbilanz** (Summe gewichteter Pro/Contra-Faktoren), ausdrücklich
  als „nicht kalibriert, keine Wahrscheinlichkeit“ gekennzeichnet.
- Eine Trefferquote je Evidenz-Bucket wird erst angezeigt, wenn mindestens
  `CALIBRATION_MIN_SAMPLES` live gespeicherte und nachträglich ausgewertete Analysen vorliegen.
  Diese sind out-of-sample, weil sie vor dem Ergebnis gespeichert wurden.
- Backtest-Ergebnisse auf Demo-Daten sind als bedeutungslos markiert.
