#!/bin/bash

# Search for "clearfix pbm".
# Replace $2 with the correct classes from the html document

sed -n "/<div aria-label\=\"Search Results\" role\=\"main\"/,/<div class=\"$2\">/p" $1 > out;

tr -d "\n\r" < out > outTrimmed;

grep -Po '(?<=\" href\=\"https\:\/\/www.facebook.com\/)[^\"\#\&]+' outTrimmed | uniq > outProfileLinks;

sed -e "s/?[^id].*//g" -i outProfileLinks;

sed -e 's/^/https\:\/\/www.facebook.com\//' outProfileLinks | uniq > outProfileLinks;

grep -Po "(?<=\<image style\=\"height\: 60px\; width\: 60px\;\" x\=\"0\" y\=\"0\" height\=\"100\%\" preserveAspectRatio\=\"xMidYMid slice\" width\=\"100\%\" xlink:href\=\")[^\"]+" outTrimmed > outProfileImages;

mkdir images;

cd images;
iterator=1;
while read p; do
	curl "$p" -o $((iterator++)).jpg;
done < ../outProfileImages;
cd ..;
