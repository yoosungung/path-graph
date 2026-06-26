#!/usr/bin/env bash
# Raise inotify limits on a k3s node (argoexec fsnotify watcher exhaustion).
#
# Usage:
#   ./scripts/tune-node-inotify.sh
#   NODE=didim-gpu MAX_USER_INSTANCES=512 ./scripts/tune-node-inotify.sh

set -euo pipefail

NODE="${NODE:-didim-gpu}"
MAX_USER_INSTANCES="${MAX_USER_INSTANCES:-512}"
MAX_USER_WATCHES="${MAX_USER_WATCHES:-524288}"

echo "Tuning inotify on node=${NODE} (max_user_instances=${MAX_USER_INSTANCES}) ..."

kubectl run "tune-inotify-$(date +%s)" \
  --image=alpine:3.19 \
  --restart=Never \
  --rm \
  -i \
  --overrides "$(cat <<EOF
{
  "spec": {
    "nodeName": "${NODE}",
    "hostPID": true,
    "hostNetwork": true,
    "containers": [{
      "name": "tune",
      "image": "alpine:3.19",
      "command": ["sh", "-c", "sysctl -w fs.inotify.max_user_instances=${MAX_USER_INSTANCES} fs.inotify.max_user_watches=${MAX_USER_WATCHES} && echo instances=\$(cat /proc/sys/fs/inotify/max_user_instances) watches=\$(cat /proc/sys/fs/inotify/max_user_watches)"],
      "securityContext": {"privileged": true}
    }]
  }
}
EOF
)"

echo "Done. Persist across reboot: on the node, add to /etc/sysctl.d/99-inotify.conf"
