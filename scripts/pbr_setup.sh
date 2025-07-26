#!/bin/bash

# create ipset
sudo ipset create isp1 hash:ip
sudo ipset create isp2 hash:ip
# setup iptables matches
sudo iptables -t mangle -A PREROUTING -m set --match-set isp1 dst -j MARK --set-mark 1234
sudo iptables -t mangle -A PREROUTING -m set --match-set isp2 dst -j MARK --set-mark 2345

# setup routing rules
sudo ip rule add fwmark 1234 table 100 #isp 1
sudo ip route add default via 192.168.1.1 table 100

sudo ip rule add fwmark 2345 table 200 #isp 2
sudo ip route add default via 192.168.2.1 table 200
