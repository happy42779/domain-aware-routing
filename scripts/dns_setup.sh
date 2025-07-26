#!/bin/bash

# start=2
# end=5119
# j=1

gen_mock() {
  start=$1
  end=$2
  j=1
  tmp=$(mktemp)

  {
    for ((i = start; i < end; i++)); do
      k=$((i % 256))
      if [ $k -eq 0 ]; then
        ((j++))
      fi
      echo "address=/test${j}-${k}.com/10.1.${j}.${k}"
    done
  } >"${tmp}"

  # move this file to /etc/dnsmasq.d/mock.conf
  mv "${tmp}" /etc/dnsmasq.d/mock.conf
  # mv "${tmp}" /etc/dnsmasq.d/mock.conf
}

T0=$(date +%s.%N)
gen_mock 1 10239
T1=$(date +%s.%N)
#T=$(echo "scale=6; $T1-$T0" | bc)
T=$(echo "($T1-$T0)*1000" | bc)

echo "time elapsed: ${T1} - ${T0} =  ${T} ms"

# restart dnsmasq
systemctl restart dnsmasq
