#!/bin/bash
set -euo pipefail

ROOT="${1:-"$PWD"}"
OUT="$ROOT/_reencoded"

mkdir -p "$OUT"

find "$ROOT" -type f \
  \( -iname "*.mp4" -o -iname "*.m4v" -o -iname "*.mov" -o -iname "*.mkv" -o -iname "*.avi" -o -iname "*.webm" \) \
  -not -path "$OUT/*" \
  -print0 |
while IFS= read -r -d '' IN; do
  REL="${IN#$ROOT/}"
  RELDIR="$(dirname "$REL")"
  BASENAME="$(basename "${REL%.*}")"
  mkdir -p "$OUT/$RELDIR"

  OUTFILE="$OUT/$RELDIR/$BASENAME.mp4"

  ffmpeg -hide_banner -loglevel error -stats -y \
    -i "$IN" \
    -map 0:v:0 -map 0:a? -sn -dn \
    -c:v hevc_videotoolbox \
    -b:v 10M -maxrate 12M -bufsize 4M \
    -g 48 \
    -tag:v hvc1 \
    -c:a aac -b:a 128k -ac 2 \
    -movflags +faststart \
    "$OUTFILE" < /dev/null
done
