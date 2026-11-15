#!/usr/bin/env bash
# Sustituido por «bin/pos instalar» (primera vez) y «bin/pos actualizar» (después). Se deja como atajo.
exec "$(cd "$(dirname "$0")/../.." && pwd)/bin/pos" actualizar "$@"
