#!/bin/bash

# 1. Basic Check
[[ -z "$1" ]] && { echo "Usage: ./preparer.sh <file>"; exit 1; }

# Wrap everything in quotes to handle spaces
INPUT="$1"
INPUT_DIR=$(dirname "$(realpath "$INPUT")")
FILENAME=$(basename "${INPUT%.*}")
OUTPUT="${INPUT_DIR}/${FILENAME}_web.mp4"
TEMP_SUB="/tmp/temp_sub_${RANDOM}.srt"

# Clean up temp file on exit
trap "rm -f \"$TEMP_SUB\"" EXIT

echo "--- Scanning for Subtitles ---"

# 2. Get Internal Subs (Index | Lang | Title)
internal_subs=$(ffprobe -v error -select_streams s -show_entries stream=index:stream_tags=language,title -of csv=p=0 "$INPUT" | \
    awk -F, '{print $1 " | " $2 " | " $3 " (internal)"}')

# 3. Get External Subs
external_subs=$(find "$INPUT_DIR" -maxdepth 1 \( -iname "*.srt" -o -iname "*.ass" \) -printf "external:%f\n")

# 4. User Selection
choice=$(echo -e "none\n$internal_subs\n$external_subs" | fzf --header="Select Subtitle" --reverse)

FILTER_ARGS=()

if [[ "$choice" == *"(internal)"* ]]; then
    INDEX=$(echo "$choice" | cut -d' ' -f1)
    echo "Extracting stream #$INDEX..."
    ffmpeg -y -i "$INPUT" -map 0:"$INDEX" "$TEMP_SUB" -v quiet
    FILTER_ARGS=("-vf" "subtitles=$TEMP_SUB")

elif [[ "$choice" == "external:"* ]]; then
    SUB_NAME=$(echo "$choice" | cut -d':' -f2-)
    FULL_PATH="$INPUT_DIR/$SUB_NAME"
    ESCAPED_PATH=$(echo "$FULL_PATH" | sed 's/:/\\:/g')
    FILTER_ARGS=("-vf" "subtitles='$ESCAPED_PATH'")
fi

# 5. Run Encode
echo "--- Encoding: $OUTPUT ---"

# Optimized for Web Playback (Stable Bitrate & yuv420p)
ffmpeg -i "$INPUT" \
    -c:v h264_nvenc \
    -preset slow \
    -profile:v high \
    -level 4.1 \
    -pix_fmt yuv420p \
    -b:v 3M -maxrate 4M -bufsize 8M \
    "${FILTER_ARGS[@]}" \
    -c:a aac \
    -b:a 128k \
    -movflags +faststart \
    -y "$OUTPUT"
