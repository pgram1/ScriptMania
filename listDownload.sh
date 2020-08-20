wget -i "$1"
for file in *; do mv "$file" "$(basename "$file")$2"; done;
mv "$1$2" "$1"