#!/bin/sh
set -eu

export PYTHONPATH="/app/src${PYTHONPATH:+:$PYTHONPATH}"

exec python -m meross_provisioner
