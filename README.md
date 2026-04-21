# energie-monitor-app

Monitoring der Energie in unserem Haus

## Installation

### Voraussetzungen

- Linux/macOS oder WSL mit `bash`
- `rsync`
- SSH-Zugriff auf das Zielsystem

### Schritte

1. Repository klonen:
   ```bash
   git clone https://github.com/frabartolo/energie-monitor-app.git
   cd energie-monitor-app
   ```
2. Deploy-Skript ausführbar machen:
   ```bash
   chmod +x /home/runner/work/energie-monitor-app/energie-monitor-app/scripts/deploy.sh
   ```

## Verwendung

### 1) Testlauf (empfohlen)

```bash
DEPLOY_TARGET="user@server:/opt/energie-monitor-app" \
/home/runner/work/energie-monitor-app/energie-monitor-app/scripts/deploy.sh --dry-run
```

### 2) Deployment ausführen

```bash
DEPLOY_TARGET="user@server:/opt/energie-monitor-app" \
/home/runner/work/energie-monitor-app/energie-monitor-app/scripts/deploy.sh
```

### Optionale Umgebungsvariable

- `BUILD_DIR`: Quellverzeichnis für das Deployment (Standard: Projektverzeichnis)

Beispiel:

```bash
DEPLOY_TARGET="user@server:/opt/energie-monitor-app" \
BUILD_DIR="/home/runner/work/energie-monitor-app/energie-monitor-app" \
/home/runner/work/energie-monitor-app/energie-monitor-app/scripts/deploy.sh
```
