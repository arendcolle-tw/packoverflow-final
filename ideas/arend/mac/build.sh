#!/bin/bash
# Compiles the Swift helper once into local/bin/fow (needs Xcode command line tools).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p local/bin
swiftc -O mac/fow.swift -o local/bin/fow
echo "built local/bin/fow"
