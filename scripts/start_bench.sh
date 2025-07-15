#!/bin/bash

# start logging ryu application
# TODO: need to add measurements of ovs
psrecord $(pgrep ryu_app) --interval 0.3 --duration 30 --log controller.csv &
LOG_PID=$!

# run rule updates
python3 measure.py --rules 100

wait $LOG_PID
