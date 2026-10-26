# Zusammenarbeit & Entwicklungsprozess

## Branching-Strategie: GitHub Flow mit geschütztem `main`

Für zwei Entwickler ohne Release-Zyklen ist GitHub Flow die einfachste belastbare Variante.

- `main` ist immer lauffähig und grün in CI. Direkte Pushes sind gesperrt (Branch Protection:
  PR erforderlich, CI muss bestehen, 1 Review).
- Arbeit läuft in kurzlebigen Branches: `feature/<thema>`, `fix/<thema>`, `docs/<thema>`,
  `chore/<thema>`, `exp/<thema>` (Experimente, z. B. neue Modelle).
- Ein PR pro abgeschlossenem, reviewbarem Schritt (Faustregel < 500 Zeilen Diff).
- Merge per **Squash**, Commit-Titel nach Conventional Commits (`feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, `chore:`).
- Releases bei Bedarf als Tag `vX.Y.Z` auf `main`.

### Empfohlene GitHub-Einstellungen
1. Settings → Branches → Rule für `main`: *Require a pull request*, *Require status checks*
   (`backend`, `frontend`, `secrets-scan`), *Require conversation resolution*.
2. Settings → Secrets: keine Laufzeit-Secrets für CI nötig; Keys nur lokal in `.env`.
3. Dependabot für `pip`/`npm`/`github-actions` aktivieren (optional).

## Arbeiten mit Claude Code
- `CLAUDE.md` enthält die Invarianten. Claude Code liest sie automatisch.
- Jede Session auf einem eigenen Branch; vor dem PR die Checks aus `CLAUDE.md` laufen lassen.
- Für fachliche Änderungen an Engine oder Ähnlichkeitssuche: ADR schreiben und Backtest-Report
  im PR anhängen (vorher/nachher, gleiche Periode, gleiche Kosten).

## Lokale Umgebung (Windows & macOS)
| Werkzeug | Version | Installation |
|---|---|---|
| Python | ≥ 3.12 | python.org bzw. `brew install python@3.12` |
| uv | aktuell | `pip install uv` oder offizielle Installer |
| Node.js | 22 LTS | nodejs.org bzw. `brew install node@22` |
| Docker Desktop | optional | für PostgreSQL / Compose |

Ohne Docker läuft alles mit SQLite und dem Demo-Provider. PostgreSQL-spezifische Features
(Unveränderbarkeits-Trigger, Advisory Lock) greifen nur mit PostgreSQL.

## Definition of Done
- Tests für neue Logik (insbesondere Berechnungen und Kausalität)
- `ruff`, `mypy`, `pytest`, `npm run typecheck`, `npm test`, `npm run build` grün
- Doku/ADR aktualisiert, falls Verhalten oder Architektur sich ändern
- Keine Secrets, keine Order-Funktionalität, Demo-Kennzeichnung intakt
