#!/bin/bash

function probe() {

  start_time=$(date +%s.%N)
  while true; do
    if ping -c1 -D -W 0.1 test13-196.com >/dev/null 2>&1; then
      end_time=$(date +%s.%N)
      break
    fi
    sleep 0.001
  done
  echo "delay: $(echo "($end_time - $start_time) * 1000" | bc) ms"
}

function change() {
  curl -s --max-time 1 --write-out "\n%{time_total}\n" -X POST -H 'Content-Type=application/json' -d '{"domain":"test13-196.com", "directive": "route", "value": "192.168.1.1"}' http://10.0.0.253:8054/api/rules
}

probe &
change
