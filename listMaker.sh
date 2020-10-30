#!/bin/bash

# Search for "clearfix pbm".
# Replace $2 and $3 with the correct classes from the html document (second and third or middle and right)

sed -n "/<div class=\"$2\">/,/<div class=\"$3\">/p" $1 > out;

tr -d "\n\r" < out > outTrimmed;

grep -Po '(?<=\" href\=\")[^\"\#\&]+' outTrimmed | uniq > outProfileLinks;

sed -e "s/?[^id].*//g" -i outProfileLinks;

grep -Po '(?=https\:\/\/scontent)[^\"]+' outTrimmed > outProfileImages;