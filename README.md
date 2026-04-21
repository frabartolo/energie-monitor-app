# energie-monitor-app

Monitoring der Energie in unserem Haus.

## Zielbild (2 Container)

- **Grafana-Container (bestehend):** Visualisierung, Zeitraumauswahl, Dashboards
- **App-Container (neu):** Rohdaten lesen, fachlich normalisieren, Kennzahlen und Aggregationen liefern

Details zur agentischen Prompt-Chain und zum fachlichen Output-Vertrag für Grafana:

- [`docs/agentic-prompt-chain.md`](docs/agentic-prompt-chain.md)

## App-Container (Umsetzung)

Python-**FastAPI**-Dienst unter `src/energie_monitor/`. Er liest **Volkszähler** (Haus-Gesamt), **Home Assistant** (E-Auto / optional Wärmepumpe) und optional eine **Wärmepumpen-REST-API**, normalisiert kumulative kWh-Zählerstände und liefert pro Kennzahl die fünf Output-Kategorien als JSON (für Grafana z. B. mit dem *Infinity*- oder *JSON API*-Datasource).

### Schnellstart (lokal)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # Werte eintragen
uvicorn energie_monitor.main:app --reload --host 0.0.0.0 --port 8080
```

OpenAPI: `http://localhost:8080/docs`

### Docker

```bash
cp .env.example .env
docker compose up --build
```

Healthcheck: `GET http://localhost:8080/health`

### Kennzahlen (`metric_id`)

| `metric_id`     | Quelle |
|-----------------|--------|
| `haus_gesamt`   | Volkszähler (`VOLKSZAEHLER_UUID_HAUS`) |
| `waermepumpe`   | HA-Entity `ENTITY_ID_WAERMEPUMPE_ENERGY` oder `HEAT_PUMP_API_BASE_URL` |
| `eauto`         | HA-Entity `ENTITY_ID_EAUTO_ENERGY` |

### REST-Endpunkte (Auszug)

- `GET /api/v1/metrics` — Katalog
- `GET /api/v1/metrics/{metric_id}/current` — aktueller Zählerstand (kWh)
- `GET /api/v1/metrics/{metric_id}/timeseries?start=...&end=...` — Zählerstand-Zeitreihe
- `GET /api/v1/metrics/{metric_id}/aggregate/daily|monthly|yearly?start=...&end=...` — Verbrauch in kWh pro Periode (`start`/`end` wie in OpenAPI beschrieben; Tagesaggregate nach **UTC**-Kalendertagen)

Hinweis: Für kumulative Sensoren werden Zählerresets heuristisch erkannt; Lücken ohne Messpunkte führen zu `null` in Aggregaten.

### Konfiguration

Siehe [`.env.example`](.env.example). `VOLKSZAEHLER_BASE_URL` ist die Basis-URL der Middleware (ohne Pfad zu einzelnen UUIDs).
