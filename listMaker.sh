#!/bin/bash
# Search for "aria-label="Search Results"".
# Replace $2 with the correct class from the html document (one that is after all the divs of profiles in the result list)
sed -n "/<div aria-label\=\"Search Results\" role\=\"main\"/,/<div class=\"$2\">/p" $1 > out;
tr -d "\n\r" < out > outTrimmed;
grep -Po '(?<=\" href\=\"https\:\/\/www.facebook.com\/)[^\"\#\&]+' outTrimmed | uniq > outProfileLinks;
sed -e "s/?[^id].*//g" -i outProfileLinks;
sed -e 's/^/https\:\/\/www.facebook.com\//' outProfileLinks | uniq > outProfileLinks;
grep -Po "(?<=\<image style\=\"height\: 60px\; width\: 60px\;\" x\=\"0\" y\=\"0\" height\=\"100\%\" preserveAspectRatio\=\"xMidYMid slice\" width\=\"100\%\" xlink:href\=\")[^\"]+" outTrimmed > outProfileImages;
mkdir images;
cd images;
i=0;
while read p; do
((i++));
(curl -s "$p" -o "${i}.jpg" > /dev/null) &
done < ../outProfileImages;
cd ..;
