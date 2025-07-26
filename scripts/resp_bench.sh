#!/bin/bash

RULE_SIZES=(10 100 500 1000 2000 5000)
# RULE_SIZES=(10 100)
H1_PID=$(pgrep -f "mininet:h1")

for size in "${RULE_SIZES[@]}"; do
  echo "Running experiment with $size rules..."

  OVS_PID=$(pgrep -f ovs-vswitchd | head -n1)
  CONTROLLER_PID=$(pgrep -f ryu-manager | head -n1)
  POLICY_PID=$(pgrep -f policy_engine.py | head -n1)
  AGENT_PID=$(pgrep -f rest_agent.py | head -n1)

  # Start psrecord for each component
  env/bin/psrecord $OVS_PID --interval 0.005 --duration 1 --include-children \
    --log logs/ovs_${size}.txt & # --plot plots/ovs_${size}.png &
  LOG_PID_OVS=$!

  env/bin/psrecord $CONTROLLER_PID --interval 0.005 --duration 1 --include-children \
    --log logs/controller_${size}.txt & # --plot plots/controller_${size}.png &
  LOG_PID_CTRL=$!

  env/bin/psrecord $POLICY_PID --interval 0.005 --duration 1 --include-children \
    --log logs/policy_${size}.txt & # --plot plots/policy_${size}.png &
  LOG_PID_POLICY=$!

  env/bin/psrecord $AGENT_PID --interval 0.005 --duration 1 --include-children \
    --log logs/agent_${size}.txt & # --plot plots/agent_${size}.png &
  LOG_PID_AGENT=$!

  sleep 0.2 # Baseline

  # Run experiment with N rules
  sudo -E mnexec -a $H1_PID env/bin/python3 sdn_resp.py --rules $size >debug.log

  sleep 0.2 # Cool-down

  # Kill loggers
  # kill $LOG_PID_OVS
  wait $LOG_PID_OVS
  # kill $LOG_PID_CTRL
  wait $LOG_PID_CTRL
  # kill $LOG_PID_POLICY
  wait $LOG_PID_POLICY
  # kill $LOG_PID_AGENT
  wait $LOG_PID_AGENT

  echo "Done with $size rules."
done
