#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x bin/macbook-audio ] || [ native/audio.c -nt bin/macbook-audio ]; then ./native/build.sh; fi
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m macbook_acc.server "$@"
elif [ -x ../.venv/bin/python ]; then
  exec ../.venv/bin/python -m macbook_acc.server "$@"
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
  exec .venv/bin/python -m macbook_acc.server "$@"
fi
