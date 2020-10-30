sed -n "/<div class=\"$2\">/,/<div class=\"$3\">/p" $1 > out
