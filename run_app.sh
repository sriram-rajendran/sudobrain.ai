#!/bin/bash
# Build and run the SudoBrain Swift app as a macOS app bundle.
cd "$(dirname "$0")"
exec ./script/build_and_run.sh "$@"
