# ADR-0002: Alpaca Market Data als primärer Anbieter

**Status:** akzeptiert · **Datum:** 2026-10-24

## Kontext
Siehe Vergleich in `docs/research.md`. Gesucht war ein Anbieter mit kostenloser, echter
Echtzeitfähigkeit, dokumentierter REST- und WebSocket-API, Intraday-Historie und Nachrichten,
nutzbar aus Österreich.

## Entscheidung
- Primär: **Alpaca Market Data**. Gratisplan mit IEX-Echtzeit; Upgrade auf Algo Trader Plus
  (SIP, $99/Monat laut Doku) nur nach Teamfreigabe.
- Nachrichten: Alpaca News (Benzinga), Filings: SEC EDGAR.
- Ohne Keys: deterministischer **Demo-Provider** (simuliert, gekennzeichnet).
- Abstraktion `MarketDataProvider`/`NewsProvider`; Massive oder Databento können später als
  Adapter folgen.

## Konsequenzen
+ Sofort nutzbar ohne Kosten; klarer Upgrade-Pfad.
− IEX ist eine einzelne Börse: absolute Volumina sind nicht konsolidiert (siehe ADR-0003).
− Endpunkte wurden aus der Doku implementiert; ein Live-Test steht aus (Netzwerk-Policy im
  Build-Environment).
