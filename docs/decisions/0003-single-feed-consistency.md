# ADR-0003: Ein Feed pro Analyse, RTH-basierte Intraday-Indikatoren

**Status:** akzeptiert · **Datum:** 2026-10-24

## Kontext
Im Gratisplan liefert Alpaca SIP-Historie nur mit 15 Minuten Verzögerung, IEX dagegen in Echtzeit.
Mischt man beide Feeds (SIP historisch, IEX aktuell), werden RVOL und Volumenvergleiche wertlos:
IEX hat nur einen Bruchteil des Gesamtvolumens. Extended-Hours-Bars sind sehr dünn und verzerren
ATR, RSI und Struktur.

## Entscheidung
- Pro Installation genau ein Feed (`ALPACA_FEED`); der Feed ist Teil des DB-Schlüssels.
- RVOL wird immer innerhalb desselben Feeds und tageszeitbereinigt berechnet.
- Intraday-Indikatoren, Trends und Ausbruchserkennung nutzen **nur reguläre Handelszeit (RTH)**.
  Extended Hours fließen in Levels (PMH/PML), aktuellen Preis und Gap-Analyse ein.
- Liquiditätsschwellen sind für IEX skaliert und als solche gekennzeichnet.

## Konsequenzen
+ Konsistente, vergleichbare Kennzahlen.
− IEX-Volumen ist nicht absolut interpretierbar (Hinweis in UI und Analyse).
