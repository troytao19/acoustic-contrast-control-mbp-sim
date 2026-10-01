#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p ../bin
xcrun clang -O2 -Wall -Wextra -std=c11 audio.c -o ../bin/macbook-audio -framework AudioUnit -framework CoreAudio -framework CoreFoundation
