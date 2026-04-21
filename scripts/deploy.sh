#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT_DIR}"
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage:
  DEPLOY_TARGET="user@host:/ziel/pfad" ./scripts/deploy.sh [--dry-run]

Environment variables:
  DEPLOY_TARGET  Required. SSH target in rsync format user@host:/path
  BUILD_DIR      Optional. Local source directory (default: repository root)
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
elif [[ -n "${1:-}" ]]; then
  echo "Unknown option: $1" >&2
  usage
  exit 1
fi

: "${DEPLOY_TARGET:?DEPLOY_TARGET is required (example: user@host:/opt/energie-monitor-app)}"

if [[ ! -d "$BUILD_DIR" ]]; then
  echo "BUILD_DIR does not exist: $BUILD_DIR" >&2
  exit 1
fi

RSYNC_ARGS=(
  -az
  --delete
  --exclude ".git"
  --exclude ".github"
  --exclude ".DS_Store"
)

if [[ "$DRY_RUN" == "true" ]]; then
  RSYNC_ARGS+=(--dry-run)
  echo "Dry-run active."
fi

echo "Deploying from '$BUILD_DIR' to '$DEPLOY_TARGET'..."
rsync "${RSYNC_ARGS[@]}" "$BUILD_DIR"/ "$DEPLOY_TARGET"/
echo "Deployment finished."
