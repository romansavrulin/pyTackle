#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./clean_and_remove_fragment.sh /path/to/folder /path/to/fragment.mp3
#
# Env toggles:
#   DEBUG=1        -> bash xtrace (set -x)
#   AOF_LOG=1      -> print raw audio-offset-finder output per attempt
#   MAX_HITS=50    -> max removals per file
#   MIN_CONF=0.60  -> ignore weak matches (if confidence is present)
#   EPS=0.02       -> seconds padding around cut to reduce clicks
#
# Requirements:
#   - ffmpeg, ffprobe, jq, find
#   - perl rename supporting: rename -0ve ...
#   - audio-offset-finder (bbc/audio-offset-finder)

ROOT="${1:-.}"
FRAG="${2:-$ROOT/fragment.mp3}"

AOF_CMD="${AOF_CMD:-audio-offset-finder}"
FFMPEG="${FFMPEG:-ffmpeg}"
FFPROBE="${FFPROBE:-ffprobe}"

MAX_HITS="${MAX_HITS:-50}"
MIN_CONF="${MIN_CONF:-0.60}"
EPS="${EPS:-0.02}"

[[ "${DEBUG:-0}" == "1" ]] && set -x

log()  { printf '[%s] %s\n' "$(date +'%F %T')" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }

command -v "$FFMPEG"  >/dev/null || die "ffmpeg not found"
command -v "$FFPROBE" >/dev/null || die "ffprobe not found"
command -v "$AOF_CMD" >/dev/null || die "audio-offset-finder not found in PATH"
command -v jq         >/dev/null || die "jq not found"
command -v rename     >/dev/null || die "rename not found (need perl-rename with -0ve support)"
[[ -f "$FRAG" ]] || die "fragment not found: $FRAG"

log "ROOT=$ROOT"
log "FRAG=$FRAG"
log "AOF_CMD=$AOF_CMD"

# ---------- 1) Cleanup ----------
log "Cleanup: deleting known spam files..."
find "$ROOT" -size 34495627c -name "*Доп*.mp4" -delete
find "$ROOT" -name "*Доступ*.txt" -size 122c -delete
find "$ROOT" -name "*.url" -size 112c -delete
find "$ROOT" -name "Актуальный адрес.png" -size 48232c -delete

# ---------- Recursive rename ----------
find "$ROOT" -depth -exec rename -ve 's/.*\/\[SuperSliv\.biz\] //' {} \;

# ---------- 2) Remove all occurrences of fragment from all MP3s ----------
frag_dur="$("$FFPROBE" -v error -show_entries format=duration -of default=nk=1:nw=1 "$FRAG" || true)"
[[ -n "$frag_dur" ]] || die "Could not read fragment duration via ffprobe"
frag_dur="$(awk -v d="$frag_dur" 'BEGIN{printf "%.6f\n", d+0.0}')"
log "Fragment duration: ${frag_dur}s"

aof_find_json() {
  local target_mp3="$1"
  # As requested:
  #   audio-offset-finder --find-offset-of sample.mp3 --within file.mp3
  # Add --json if supported by your build. (If your version uses a different flag, adjust here.)
  "$AOF_CMD" --json --find-offset-of "$FRAG" --within "$target_mp3"
}

json_get_offset_conf() {
  local json="$1"
  # prints two lines: offset, confidence (confidence may be empty)
  jq -r '
    def first_nonnull(a): reduce a[] as $x (null; . // $x);
    ( first_nonnull([.offset, .timeOffset, .time_offset]) // "" ),
    ( first_nonnull([.confidence, .score, .matchConfidence]) // "" )
  ' <<<"$json"
}

cut_out_segment() {
  local in="$1" start="$2" end="$3" out="$4"

  local s e
  s="$(awk -v x="$start" -v eps="$EPS" 'BEGIN{v=x-eps; if(v<0)v=0; printf "%.6f\n", v}')"
  e="$(awk -v x="$end"   -v eps="$EPS" -v s="$s" 'BEGIN{v=x+eps; if(v<s)v=s; printf "%.6f\n", v}')"

  log "ffmpeg cut: removing [${s}, ${e}] from: $in"
  "$FFMPEG" -hide_banner -loglevel error -y -i "$in" \
    -filter_complex \
      "[0:a]atrim=0:${s},asetpts=PTS-STARTPTS[a0]; \
       [0:a]atrim=${e},asetpts=PTS-STARTPTS[a1]; \
       [a0][a1]concat=n=2:v=0:a=1[a]" \
    -map "[a]" -map_metadata 0 -id3v2_version 3 -q:a 2 \
    "$out"
}

process_one_mp3() {
  local mp3="$1"
  log "Processing: $mp3"

  local work="$tmpdir/work_$$.mp3"
  cp -f -- "$mp3" "$work"

  local hits=0
  while (( hits < MAX_HITS )); do
    local j offset conf
    if ! j="$(aof_find_json "$work" 2>&1)"; then
      log "AOF: non-zero exit while analyzing $mp3 (attempt $((hits+1))). Output:"
      printf '%s\n' "$j" >&2
      break
    fi

    [[ "${AOF_LOG:-0}" == "1" ]] && { log "AOF raw output:"; printf '%s\n' "$j" >&2; }

    mapfile -t oc < <(json_get_offset_conf "$j" || true)
    offset="${oc[0]:-}"
    conf="${oc[1]:-}"

    if [[ -z "$offset" ]]; then
      log "AOF: no offset found (done for this file)."
      break
    fi

    if [[ -n "$conf" ]]; then
      log "AOF: match offset=$offset confidence=$conf"
      awk -v c="$conf" -v min="$MIN_CONF" 'BEGIN{exit !(c>=min)}' || { log "AOF: confidence < $MIN_CONF, stopping."; break; }
    else
      log "AOF: match offset=$offset (no confidence field)"
    fi

    local start end
    start="$(awk -v o="$offset" 'BEGIN{printf "%.6f\n", o+0.0}')"
    end="$(awk -v o="$offset" -v d="$frag_dur" 'BEGIN{printf "%.6f\n", o+d}')"

    awk -v s="$start" 'BEGIN{exit !(s>=0)}' || { log "AOF: negative offset ($start), stopping."; break; }

    local out="$tmpdir/out_$$.mp3"
    cut_out_segment "$work" "$start" "$end" "$out"
    mv -f -- "$out" "$work"

    hits=$((hits+1))
    log "Removed occurrence #$hits from $mp3"
  done

  if (( hits > 0 )); then
    mv -f -- "$work" "$mp3"
    log "Cleaned: $mp3 (removed $hits occurrence(s))"
  else
    rm -f -- "$work" || true
    log "No changes: $mp3"
  fi
}

frag_real="$(readlink -f "$FRAG" 2>/dev/null || echo "$FRAG")"
log "Scanning for MP3 files..."
while IFS= read -r -d '' f; do
  f_real="$(readlink -f "$f" 2>/dev/null || echo "$f")"
  [[ "$f_real" == "$frag_real" ]] && { log "Skipping fragment itself: $f"; continue; }
  process_one_mp3 "$f"
done < <(find "$ROOT" -type f -name "*.mp3" -print0)

log "All done."
