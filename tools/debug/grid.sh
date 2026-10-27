#!/bin/sh
# 2x2 (or 1x3) contact sheet of screenshots: tools/debug/grid.sh out.png a.png b.png [c.png] [d.png]
out="$1"; shift
FF=$(command -v ffmpeg || echo /opt/homebrew/bin/ffmpeg)
if [ $# -eq 4 ]; then
  "$FF" -loglevel error -y -i "$1" -i "$2" -i "$3" -i "$4" -filter_complex "[0]scale=628:-1[a];[1]scale=628:-1[b];[2]scale=628:-1[c];[3]scale=628:-1[d];[a][b]hstack[t];[c][d]hstack[u];[t][u]vstack" "$out"
else
  n=$#; args=""; for f in "$@"; do args="$args -i $f"; done
  "$FF" -loglevel error -y $args -filter_complex "hstack=$n,scale=1884:-1" "$out"
fi
echo "$out"
