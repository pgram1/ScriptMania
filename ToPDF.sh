#!/bin/bash
for a in *.doc
do
  b=${a%%.doc}
  lloconv "$a" "$b.pdf"
done


for c in *.ppt
do
  d=${c%%.ppt}
  lloconv "$c" "$d.pdf"
done

for e in *.docx
do
  f=${e%%.docx}
  lloconv "$e" "$f.pdf"
done

for g in *.pptx
do
  h=${g%%.pptx}
  lloconv "$g" "$h.pdf"
done

rm *.doc
rm *.ppt
rm *.docx
rm *.pptx
