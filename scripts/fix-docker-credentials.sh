#!/usr/bin/env bash
set -euo pipefail

docker_config_dir="${DOCKER_CONFIG:-${HOME}/.docker}"
config_file="${docker_config_dir}/config.json"

if [[ ! -f "$config_file" ]]; then
  echo "Docker config not found: $config_file"
  exit 0
fi

helper_action=remove
if command -v docker-credential-desktop >/dev/null 2>&1; then
  helper_action=keep
elif command -v docker-credential-osxkeychain >/dev/null 2>&1; then
  helper_action=use-osxkeychain
fi

python3 - "$config_file" "$helper_action" <<'PY'
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

config_path = Path(sys.argv[1])
action = sys.argv[2]
config = json.loads(config_path.read_text())

if action == "keep":
    print("docker-credential-desktop is available; no change needed.")
    raise SystemExit(0)

changed = False
if config.get("credsStore") == "desktop":
    if action == "use-osxkeychain":
        config["credsStore"] = "osxkeychain"
    else:
        del config["credsStore"]
    changed = True

credential_helpers = config.get("credHelpers")
if isinstance(credential_helpers, dict):
    stale_registries = [
        registry
        for registry, helper in credential_helpers.items()
        if helper == "desktop"
    ]
    for registry in stale_registries:
        if action == "use-osxkeychain":
            credential_helpers[registry] = "osxkeychain"
        else:
            del credential_helpers[registry]
        changed = True
    if not credential_helpers:
        config.pop("credHelpers", None)

if not changed:
    print("No stale Docker Desktop credential helper setting found.")
    raise SystemExit(0)

timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
backup_path = config_path.with_name(f"{config_path.name}.bak.{timestamp}")
shutil.copy2(config_path, backup_path)
config_path.write_text(json.dumps(config, indent=2) + "\n")

if action == "use-osxkeychain":
    print(f"Switched Docker credentials to osxkeychain: {config_path}")
else:
    print(f"Removed stale Docker Desktop credential helper: {config_path}")
print(f"Backup created: {backup_path}")
PY
