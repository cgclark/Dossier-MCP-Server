#!/bin/bash
# build.sh — compile the macOS Swift engines/helpers from source.
# Run this after a fresh clone (or after editing any .swift file) on a Mac with
# Xcode command line tools installed. Binaries land next to their source and are
# gitignored — only the .swift files are tracked.
set -euo pipefail
cd "$(dirname "$0")"

for src in engines/*.swift helpers/*.swift; do
    out="${src%.swift}"
    echo "swiftc -O $src -> $out"
    swiftc -O "$src" -o "$out"
    chmod +x "$out"
done

echo "done."
