#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

version="${1:-snapshot}"
dist_dir="dist/sudobrain-${version}"

rm -rf "$dist_dir"
mkdir -p "$dist_dir"

cp -R README.md LICENSE CHANGELOG.md SECURITY.md CONTRIBUTING.md docs scripts backend browser-extension web-companion docker-compose.yml docker-compose.full.yml Makefile "$dist_dir/"

tar -czf "dist/sudobrain-${version}.tar.gz" -C dist "sudobrain-${version}"

echo "Created dist/sudobrain-${version}.tar.gz"
echo "This is an unsigned source/backend package. Signed macOS app release still requires Apple signing credentials."
