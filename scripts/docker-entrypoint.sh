#!/bin/sh
set -e

python -m src.health --startup
exec "$@"
