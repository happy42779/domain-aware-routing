#!/bin/bash

function setup() {
  # hosts namespace
  ip netns add hosta
  ip netns add hostb
  # router namespace
  ip netns add router
  # isp namespaces
  ip netns add ispa
  ip netns add ispb

  # Host A ↔ OVS
  ip link add ha-veth0 type veth peer name s1-ha
  ip link set ha-veth0 netns hosta

  # Host B ↔ OVS
  ip link add hb-veth0 type veth peer name s1-hb
  ip link set hb-veth0 netns hostb

  # Router ↔ OVS
  ip link add r-veth0 type veth peer name s1-router
  ip link set r-veth0 netns router

  # Router ↔ ISP A
  ip link add r-veth1 type veth peer name ispa-veth0
  ip link set r-veth1 netns router
  ip link set ispa-veth0 netns ispa

  # Router ↔ ISP B
  ip link add r-veth2 type veth peer name ispb-veth0
  ip link set r-veth2 netns router
  ip link set ispb-veth0 netns ispb

  # Router ↔ dns_engine
  ip link add r-dns0 type veth peer name router-dns0
  ip link set r-dns0 netns router

  # create bridge and connect interfaces
  ovs-vsctl add-br s1
  ovs-vsctl add-port s1 s1-ha
  ovs-vsctl add-port s1 s1-hb
  ovs-vsctl add-port s1 s1-router

  ip link set s1 up
  ip link set s1-ha up
  ip link set s1-hb up
  ip link set s1-router up
  # dns link in root namespace
  ip link set router-dns0 up

  # configure interfaces
  # host namespace
  # host a
  ip netns exec hosta ip addr add 10.0.0.1/24 dev ha-veth0
  ip netns exec hosta ip link set ha-veth0 up
  ip netns exec hosta ip link set lo up
  ip netns exec hosta ip route add default via 10.0.0.254

  # host b
  ip netns exec hostb ip addr add 10.0.0.2/24 dev hb-veth0
  ip netns exec hostb ip link set hb-veth0 up
  ip netns exec hostb ip link set lo up
  ip netns exec hostb ip route add default via 10.0.0.254

  # router namespace
  ip netns exec router ip addr add 10.0.0.254/24 dev r-veth0
  ip netns exec router ip addr add 192.168.1.2/24 dev r-veth1
  ip netns exec router ip addr add 192.168.2.2/24 dev r-veth2
  ip netns exec router ip addr add 198.19.249.54/24 dev r-dns0
  ip netns exec router ip link set r-veth0 up
  ip netns exec router ip link set r-veth1 up
  ip netns exec router ip link set r-veth2 up
  ip netns exec router ip link set r-dns0 up
  ip netns exec router ip link set lo up
  ip netns exec router sysctl -w net.ipv4.ip_forward=1

  # root namespace setup
  ip addr add 198.19.249.53/24 dev router-dns0
  ip link set router-dns0 up

  # no need for doing nat
  #ip netns exec router iptables -t nat -A POSTROUTING -o h-veth1 -j MASQUERADE
  #ip netns exec router iptables -t nat -A POSTROUTING -o h-veth2 -j MASQUERADE

  # isp A namespace
  ip netns exec ispa ip addr add 192.168.1.1/24 dev ispa-veth0
  ip netns exec ispa ip link set ispa-veth0 up
  ip netns exec ispa ip link set lo up
  ip netns exec ispa ip route add default via 192.168.1.2

  # isp B namespace
  ip netns exec ispb ip addr add 192.168.2.1/24 dev ispb-veth0
  ip netns exec ispb ip link set ispb-veth0 up
  ip netns exec ispb ip link set lo up
  ip netns exec ispb ip route add default via 192.168.2.2

  # setup ovs controller
  ovs-vsctl set-controller s1 tcp:127.0.0.1:6633
  ovs-vsctl set-fail-mode s1 secure
}

# cleanup
function cleanup() {
  ip netns del hosta
  ip netns del hostb
  ip netns del router
  ip netns del ispa
  ip netns del ispb
  ovs-vsctl del-br s1
  ip link delete s1-ha
  ip link delete s1-hb
  ip link delete s1-router
  ip link delete ispa-veth0
  ip link delete ispb-veth0
  ip link delete router-dns0
}

$1
