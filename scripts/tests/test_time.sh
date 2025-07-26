#!/bin/bash

start_time=$(date +%s.%N)
sleep 1
end_time=$(date +%s.%N)
echo "delay: $( echo "$end_time - $start_time" | bc) s"
