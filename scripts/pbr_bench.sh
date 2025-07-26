#!/bin/bash

RULE_SIZES=(10 100 500 1000 2000 5000)
# RULE_SIZES=(10)
H4_PID=$(pgrep -f "mininet:h4")
DNS_PID=$(pgrep -f "mininet:router")

for size in "${RULE_SIZES[@]}"; do
  echo "Running experiment with $size rules..."

  # start dnsmasq
  # sudo -E mnexec -a "$DNS_PID" dnsmasq --conf-file=confs/conf_${size}.conf --log-facility=- &

  # Run experiment with N rules
  sudo -E mnexec -a "$H4_PID" env/bin/python3 pbr_delay.py --rules $size --pid "$DNS_PID"

  sleep 0.2 # Cool-down

  # get pid and terminate dnsmasq
  sudo pkill -f "dnsmasq --conf-file=confs/conf_${size}.conf"

  echo "Done with $size rules."
done
