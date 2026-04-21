# Agentische Prompt-Chain für die Energie-Auswertungsanwendung

Diese Spezifikation setzt das gewünschte **2-Container-Zielbild** um:

1. **Grafana-Container (bestehend)** für Visualisierung
2. **App-Container (neu)** für fachliche Datenaufbereitung und Bereitstellung

## Zielbild der Anwendung

Der App-Container vereinheitlicht Rohdaten aus:

- Volkszähler
- Home Assistant
- Wärmepumpen-API (optional/bevorzugt für Wärmepumpenverbrauch)

und liefert für Grafana fachlich nutzbare Kennzahlen.

### Kernkennzahlen

- Haus-Gesamtverbrauch
- Wärmepumpenverbrauch
- E-Auto-Verbrauch (Shelly Pro 3EM via Home Assistant)

### Verbindliche Output-Kategorien pro Kennzahl

Der App-Container liefert pro Kennzahl:

- **Current Value**
- **Historical Time Series**
- **Daily Aggregate**
- **Monthly Aggregate**
- **Yearly Aggregate**

Damit kann Grafana mindestens umsetzen:

- historische Grafiken
- frei einschränkbare Zeiträume (heute, 24h, 7d, Monat, Jahr, frei)
- aktuelle Werte (Stat/KPI)
- Tages-/Monats-/Jahresauswertungen

## Rollenverteilung

### Grafana-Container

- Dashboards, Panels, Visualisierung
- interaktive Zeitraumsteuerung
- Stat-/KPI-Anzeigen

### App-Container

- Rohdaten lesen und mappen
- Einheiten/Zeitstempel normalisieren
- Fachlogik für Kennzahlen und Aggregationen
- Bereitstellung grafana-tauglicher Datenformen

## Verantwortungsmatrix

| Bereich | App-Container | Grafana-Container |
|---|---|---|
| Rohdaten lesen | Ja | Nein |
| Messpunkte zuordnen | Ja | Nein |
| Einheiten normalisieren | Ja | Nein |
| Kennzahlen fachlich berechnen | Ja | Nein |
| Current Values liefern | Ja | Nein |
| Historische Zeitreihen liefern | Ja | Nein |
| Tages-/Monats-/Jahresaggregate liefern oder definieren | Ja | Nein |
| Zeiträume interaktiv auswählen | Nein | Ja |
| Grafiken/Panels darstellen | Nein | Ja |
| Dashboard-Struktur wählen | Nein | Ja |

## Prompt-Chain (5 Agenten)

Die Prompt-Chain erzeugt schrittweise ein prüfbares fachliches Modell.

### Agent 1 — Anwendungs- und Quellenanalyst

Input: Zielkennzahlen, Quellen, Messpunkte, gewünschte Sichten/Aggregate  
Output: `application_model` (YAML) mit Metriken, Rohmessungen, Verantwortungen, offenen Fragen

Qualitätsfokus:
- Zielkennzahlen vs. Rohquellen sauber trennen
- Messart (`instantaneous_power` / `cumulative_energy`) sichtbar machen
- Historik und Aggregate explizit aufnehmen

### Agent 2 — Datenqualitäts- und Mapping-Analyst

Input: `application_model`  
Output: `quality_and_mapping_risks` (YAML) mit priorisierten Risiken und Lücken

Qualitätsfokus:
- Resets, Lücken, Einheitenfehler, Zeitbezug
- Auswirkungen getrennt nach `current_value`, `timeseries`, `daily`, `monthly`, `yearly`
- Logik identifizieren, die nicht in Grafana liegen darf

### Agent 3 — Metrik- und Output-Architekt

Input: Agent 1 + Agent 2  
Output: `metric_and_output_model` (YAML) mit derivation/normalization/validation je KPI

Qualitätsfokus:
- Leistung und Energie strikt trennen
- klarer Output Contract je KPI
- Aggregatbildung fachlich beschreiben
- Visual-Stilregeln für KPI/Charts definieren (iPhone/iOS-inspiriert)

### Agent 4 — Bereitstellungsdesigner für Grafana

Input: Agent 1–3  
Output: `grafana_delivery_model` (YAML) mit lieferbaren Datenformen je KPI

Qualitätsfokus:
- pro KPI alle fünf Output-Kategorien
- Zeitraumfähigkeit explizit
- konsumierbar ohne komplexe Grafana-Transformationen

### Agent 5 — Dashboard- und Umsetzungsplaner

Input: Agent 1–4  
Output: Dashboard-Konzept + priorisierte Umsetzung

Qualitätsfokus:
- Dashboard 1: Live/Überblick
- Dashboard 2: Historische Verläufe
- Dashboard 3: Aggregate (Tag/Monat/Jahr)
- klare Reihenfolge von Messpunkt-Validierung bis Dashboard-Bau

## Orchestrator-Workflow

1. **Kontext sammeln** (Metriken, Quellen, Messart, Historik, Aggregate, Timestamp/Reset-Besonderheiten)
2. Agent 1 ausführen
3. Agent 2 ausführen
4. Agent 3 ausführen
5. Agent 4 ausführen
6. Agent 5 ausführen
7. Abschluss mit:
   1. Anwendungsmodell
   2. Quellen/Mappings
   3. Risiken/Unsicherheiten
   4. Metrik- und Output-Modell
   5. Bereitstellungsmodell für Grafana
   6. Dashboard-Konzept
   7. Offene Fragen

## Leitplanken

- Historik ist Pflicht
- Aggregate (Tag/Monat/Jahr) sind Pflichtbestandteil des Output-Vertrags
- Grafana steuert Zeiträume, App liefert Fachsemantik
- Keine zusätzliche Datenbank als Pflicht in der Startarchitektur
- Fragen statt raten; unklare Punkte als offene Fragen markieren
