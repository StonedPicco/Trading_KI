# ADR-0006: Eigener Walk-Forward-Replayer statt Backtesting-Framework

**Status:** akzeptiert · **Datum:** 2026-10-24

## Kontext
Geprüft wurden vectorbt (vektorisiert, schnell, ideal für Parameter-Sweeps), backtesting.py
(einfach, Einzelwert) und NautilusTrader (ereignisgetrieben, live-fähig, steile Lernkurve).
Getestet werden sollen *Analyse-Szenarien* (Entry-Zone, Stop, Ziel, „kein Trade“) mit exakt
derselben Funktion wie im Live-Betrieb.

## Entscheidung
`backtest/runner.py` spielt `compute_facts` + `build_scenario` zu festen Entscheidungszeitpunkten
ab (`as_of` kürzt alle Eingaben). Die Trades werden konservativ simuliert (Stop vor Ziel im
selben Bar), Spread/Slippage/Kommission sind konfigurierbar. Baselines (Random, Momentum, immer
Long) handeln zu denselben Zeitpunkten mit gleicher Geometrie. Berichte gibt es gesamt, je
Periodenhälfte und je Volatilitätsregime.

## Konsequenzen
+ Keine Abweichung zwischen Live- und Backtest-Logik; Look-Ahead per Test abgesichert.
− Langsamer als vektorisierte Frameworks (~1 s je Entscheidung). vectorbt bleibt Option für
  Schwellen-Sweeps mit strikter Out-of-Sample-Trennung.
