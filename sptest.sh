#!/bin/bash

# Installation:
# sudo apt-get install python-pip && pip install speedtest-cli
# sudo cp ~/.local/bin/speedtest-cli /usr/local/bin
# sudo apt-get install speedtest

if [[ ! -f speedtest ]]; then
  printf "%s\n" "Required package speedtest-cli not found"
  printf "%s\n" "Install it with:"
#  printf "%s\n" "sudo apt-get install python-pip && pip install speedtest-cli"
#  printf "%s\n" "sudo cp ~/.local/bin/speedtest-cli /usr/local/bin"
  printf "%s\n" "sudo apt-get install speedtest"
  exit 1
fi

_trapCmd() {
  trap 'kill -TERM $PID; exit 130;' TERM
  eval "$1" &
  PID=$!
  wait $PID
}

declare -A servers=( [19078]="Athens" [4201]="Athens" [5188]="Athens")
declare -A providers=( [19078]="Vodafone - Panafon S.A." [4201]="OTE S.A." [5188]="Cosmote S.A." )

printf "%s\n\n" "Press CTRL+C to cancel"
id=19078
# for id in 19078 4201 5188; do
  printf "%s\n" "Location: ${servers[$id]}"
  printf "%s\n" "Provider: ${providers[$id]}"
  # _trapCmd "speedtest --server $id --simple; echo;" -> speedtest-cli
  _trapCmd "speedtest --server-id=$id echo;" # -> speedtest (.net)
# done

unset servers
unset providers
unset id
