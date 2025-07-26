#!/bin/bash

RULE_SIZES=(10 100 500 1000 2000 5000)
# RULE_SIZES=(10 100)
H1_PID=$(pgrep -f "mininet:h1")

for size in "${RULE_SIZES[@]}"; do
  echo "Running latency tests with $size rules..."

  # Run experiment with N rules
  sudo -E mnexec -a $H1_PID env/bin/python3 sdn_delay.py --rules $size

  echo "Done with $size rules."
done
