#!/usr/bin/env bash
# Three-layer verification (static, runtime, system). See harness/verify.py --help.
exec python3 "$(dirname "$0")/verify.py" "$@"
