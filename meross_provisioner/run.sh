#!/command/with-contenv bash
set -euo pipefail

export PYTHONPATH="/app/src${PYTHONPATH:+:$PYTHONPATH}"

exec python -m meross_provisioner
