#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v magick >/dev/null 2>&1; then
  echo "ImageMagick 'magick' command is required to generate the demo GIF." >&2
  exit 1
fi

out="docs/assets/screenshots/demo-flow.gif"
tmp="$(mktemp -d)"
trap 'rm -f "$tmp"/*.png; rmdir "$tmp"' EXIT

make_frame() {
  local file="$1"
  local accent="$2"
  local offset="$3"
  magick -size 960x540 "xc:#f7f8fb" \
    -fill white -stroke "#d9dde7" -strokewidth 2 -draw "roundrectangle 28,28 238,512 8,8" \
    -fill white -stroke "#d9dde7" -strokewidth 2 -draw "roundrectangle 262,28 932,512 8,8" \
    -fill "$accent" -stroke none -draw "roundrectangle 292,92 882,172 8,8" \
    -fill "#f6f8fb" -stroke "#e1e5ee" -strokewidth 2 -draw "roundrectangle 292,214 572,326 8,8" \
    -fill "#f6f8fb" -stroke "#e1e5ee" -strokewidth 2 -draw "roundrectangle 602,214 882,326 8,8" \
    -fill "#f6f8fb" -stroke "#e1e5ee" -strokewidth 2 -draw "roundrectangle 292,356 882,448 8,8" \
    -fill "$accent" -stroke none -draw "circle $((380 + offset)),270 $((392 + offset)),270" \
    -fill "$accent" -stroke none -draw "circle $((520 + offset)),270 $((532 + offset)),270" \
    -fill "$accent" -stroke none -draw "circle $((660 + offset)),270 $((672 + offset)),270" \
    -stroke "$accent" -strokewidth 5 -draw "line $((392 + offset)),270 $((508 + offset)),270 line $((532 + offset)),270 $((648 + offset)),270" \
    "$file"
}

make_frame "$tmp/today.png" "#2563eb" 0
make_frame "$tmp/chat.png" "#16a34a" 18
make_frame "$tmp/graph.png" "#7c3aed" -18
make_frame "$tmp/workflows.png" "#ea580c" 36
make_frame "$tmp/admin.png" "#0891b2" -36

magick -delay 130 -loop 0 "$tmp/today.png" "$tmp/chat.png" "$tmp/graph.png" "$tmp/workflows.png" "$tmp/admin.png" "$out"
echo "Created $out"
