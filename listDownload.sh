wget -U 'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.8.1.6) Gecko/20070802 SeaMonkey/1.1.4' -e robots=off -i "$1"
for file in *; do mv "$file" "$(basename "$file")$2"; done;
mv "$1$2" "$1"
