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

SUB_FILTER=""
if [[ "$choice" == *"(internal)"* ]]; then
    INDEX=$(echo "$choice" | cut -d' ' -f1)
    echo "Extracting stream #$INDEX..."
    ffmpeg -y -i "$INPUT" -map 0:"$INDEX" "$TEMP_SUB" -v quiet
    SUB_FILTER="subtitles=$TEMP_SUB"
elif [[ "$choice" == "external:"* ]]; then
    SUB_NAME=$(echo "$choice" | cut -d':' -f2-)
    FULL_PATH="$INPUT_DIR/$SUB_NAME"
    ESCAPED_PATH=$(echo "$FULL_PATH" | sed 's/:/\\:/g')
    SUB_FILTER="subtitles='$ESCAPED_PATH'"
fi

# Build video filter chain: subtitles (if any) + conditional scale to max 720p
VF=""
if [[ -n "$SUB_FILTER" ]]; then
    VF="$SUB_FILTER,"
fi
# Downscale only if height > 720 → width=1280 (proportional height ≤720), else keep original
# -2 forces even dimensions for yuv420p + h264 compatibility
VF="${VF}scale='if(gt(ih,720),1280,iw)':'if(gt(ih,720),-2,ih)':force_original_aspect_ratio=decrease"

echo "--- Encoding (NVIDIA NVENC) with conditional 720p downscale: $OUTPUT ---"

ffmpeg -i "$INPUT" \
    -vf "$VF" \
    -c:v h264_nvenc \
    -preset p7 \
    -tune hq \
    -rc vbr \
    -cq 19 \
    -b:v 0 \
    -pix_fmt yuv420p \
    -c:a aac \
    -ac 2 \
    -movflags +faststart \
    -y "$OUTPUT"
