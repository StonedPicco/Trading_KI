# ADR-0004: Deterministische Engine entscheidet, das LLM erklärt

**Status:** akzeptiert · **Datum:** 2026-10-24

## Kontext
LLMs können plausibel klingende, aber falsche Zahlen oder Fakten erzeugen. Handelsentscheidungen
müssen reproduzierbar und prüfbar sein.

## Entscheidung
- Outcome-Klasse, Entry, Stop, Ziele und Evidenzbilanz berechnet ausschließlich
  `signals/engine.py` (reine Funktion, versioniert).
- Das LLM (Interface `LLMClient`, Standard `claude-opus-5-5`, per Env austauschbar) erhält Fakten,
  Szenario und Nachrichten. Es liefert eine strukturierte Begründung (JSON-Schema, strukturierte
  Ausgabe, Pydantic).
- `llm/validator.py`: Preisähnliche Zahlen müssen in den Eingaben vorkommen, Nachrichtenfakten
  müssen wörtliche Zitate sein, Gewissheitsformulierungen sind verboten. Fällt die Prüfung durch,
  wird die Ausgabe verworfen und eine deterministische Begründung verwendet.
- Widerspricht das LLM, wird das als `engine_agreement` angezeigt, ändert aber nichts.
- Kosten: Tagesbudget, Cache per Prompt-Hash, Analysen nur bei Triggern mit Cooldown.

## Konsequenzen
+ Keine halluzinierten Levels, reproduzierbare Entscheidungen.
− Die Erklärungsqualität hängt von den Fakten ab; das LLM kann keine eigenen Recherchen einbringen.
