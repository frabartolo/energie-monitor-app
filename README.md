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
| `pv`            | Volkszähler (`VOLKSZAEHLER_UUID_PV`) |
| `waermepumpe`   | HA `ENTITY_ID_WAERMEPUMPE_ENERGY` (gesamt) oder `HEAT_PUMP_API_BASE_URL` |
| `waermepumpe_heizung` | HA `ENTITY_ID_WAERMEPUMPE_HEIZUNG` |
| `waermepumpe_warmwasser` | HA `ENTITY_ID_WAERMEPUMPE_WARMWASSER` |
| `waermepumpe_kuehlen` | HA `ENTITY_ID_WAERMEPUMPE_KUEHLEN` |
| `eauto`         | Wallbox – HA `ENTITY_ID_EAUTO_ENERGY`; mit `EAUTO_MEASUREMENT=apparent_power_va` Integration der Shelly-Scheinleistung (VA) |
| `haus_ohne_eauto` | berechnet: Haus-Verbrauch minus Wallbox im Zeitraum |

### REST-Endpunkte (Auszug)

- `GET /api/v1/metrics` — Katalog
- `GET /api/v1/energy/balance?start=...&end=...` — Bilanz: Gesamtverbrauch, Netzbezug (Rechnung), Einspeisung, PV-Eigenverbrauch
- `GET /api/v1/energy/wallbox-split?start=...&end=...` — Haus / Wallbox / Haus ohne Wallbox (kWh im Zeitraum)
- `GET /api/v1/metrics/{metric_id}/current` — aktueller Wert (kWh oder bei Wallbox/VA: kVA Momentanleistung)
- `GET /api/v1/metrics/{metric_id}/timeseries?start=...&end=...` — Zählerstand-Zeitreihe
- `GET /api/v1/metrics/{metric_id}/aggregate/daily|monthly|yearly?start=...&end=...` — Verbrauch in kWh pro Periode (`start`/`end` wie in OpenAPI beschrieben; Tagesaggregate nach **UTC**-Kalendertagen)
- `GET /api/v1/metrics/{metric_id}/aggregate/night-daily?start=...&end=...&time_from=22:00&time_to=06:00&timezone=Europe/Berlin` — Verbrauch **pro Kalendernacht** im Uhrzeitfenster (Ortszeit)
- `GET /api/v1/metrics/{metric_id}/profile/hourly?start=...&end=...` — mittlerer kWh-Verbrauch je Stunde (0–23); optional `time_from`/`time_to` wie oben
- `GET /api/v1/metrics/{metric_id}/window-total?start=...&end=...` — eine Summe für beliebiges Intervall
- `GET /api/v1/metrics/{metric_id}/load-profile?start=...&end=...&interval=auto` — **Lastgang** (mittlere Leistung kW pro Intervall; `interval`: auto, 15m, 1h, 6h, 1d)

Hinweis: Für kumulative Sensoren werden Zählerresets heuristisch erkannt; Lücken ohne Messpunkte führen zu `null` in Aggregaten.

### Konfiguration

Siehe [`.env.example`](.env.example). `VOLKSZAEHLER_BASE_URL` ist die Basis-URL der Middleware (ohne Pfad zu einzelnen UUIDs).

## YAML-Artefakte (KIara)

Im Verzeichnis `yaml/` liegen von KIara generierte **fachliche Modelle** (Application/Mapping/Risks/Delivery/Dashboard-Konzept) als YAML.

- Die Dateien sind **Dokumentation/Entwurfsartefakte**, keine aktive Runtime-Konfiguration.
- Identifikatoren (UUIDs, Entity-IDs, Tokens) sind bewusst als **Platzhalter** (`<...>`) gehalten.

## Deployment (optional)

Wenn du das Repository auf ein Zielsystem synchronisieren willst (z. B. VM/NAS), kannst du das optionale `rsync`-Deploy-Skript nutzen:

```bash
chmod +x ./scripts/deploy.sh
DEPLOY_TARGET="user@server:/opt/energie-monitor-app" ./scripts/deploy.sh --dry-run
DEPLOY_TARGET="user@server:/opt/energie-monitor-app" ./scripts/deploy.sh
```

Voraussetzungen: `bash`, `rsync`, SSH-Zugriff und Host-Key ist lokal als vertrauenswürdig hinterlegt.
