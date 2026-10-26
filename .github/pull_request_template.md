## Was ändert sich?

## Warum?

## Wie getestet?
- [ ] `uv run pytest` / `npm test`
- [ ] Ruff, Mypy, `npm run typecheck`
- [ ] Manuell im Dashboard geprüft (Demo- oder Live-Daten?)

## Checkliste
- [ ] Keine Secrets, keine API-Keys im Diff
- [ ] Kein Look-Ahead: neue Analysefunktionen nutzen nur Daten ≤ `as_of` (Test vorhanden)
- [ ] Demo-/Testdaten bleiben als solche gekennzeichnet
- [ ] Architekturentscheidung? → ADR in `docs/decisions/`
- [ ] Keine Code-Pfade zu echter Orderausführung
