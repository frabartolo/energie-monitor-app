# energie-monitor-app

Monitoring der Energie in unserem Haus.

## Zielbild (2 Container)

- **Grafana-Container (bestehend):** Visualisierung, Zeitraumauswahl, Dashboards
- **App-Container (neu):** Rohdaten lesen, fachlich normalisieren, Kennzahlen und Aggregationen liefern

Details zur agentischen Prompt-Chain und zum fachlichen Output-Vertrag für Grafana:

- [`docs/agentic-prompt-chain.md`](docs/agentic-prompt-chain.md)
