#!/bin/bash
for a in *.zip
do
  b=${a%%.zip}
  7z x "$a" -o"$b"
done
rm *.zip
