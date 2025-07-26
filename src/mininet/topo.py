#!/usr/bin/python3

from mininet.net import Mininet
from mininet.node import Controller, RemoteController, OVSSwitch, Node
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import os
import time


def setupRoutingTopology():
    """Create a topology with 2 hosts and 2 uplinks, all connected to an OVS switch."""

    # Create network without remote controller
    # controller is running one of the hosts
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink)

    # Add controller
    info("*** Adding controller\n")
    c0 = net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6633)

    # Add switch
    info("*** Adding switch\n")
    s1 = net.addSwitch("s1", protocols="OpenFlow13")

    # Add hosts
    info("*** Adding hosts\n")
    h1 = net.addHost(
        "h1",
        ip="10.0.0.1/24",
        defaultRoute="via 10.0.0.254",
    )
    h2 = net.addHost(
        "h2",
        ip="10.0.0.2/24",
        defaultRoute="via 10.0.0.254",
    )
    h3 = net.addHost(
        "h3",
        ip="10.0.0.3/24",
        defaultRoute="via 10.0.0.254",
    )
    h4 = net.addHost(
        "h4",
        ip="10.0.0.4/24",
        defaultRoute="via 10.0.0.254",
    )

    # connect router to the switch
    # add router
    router = net.addHost("router", ip="10.0.0.254/24")

    # confiure network in root namespace
    # root = Node("root", inNamespace=False)
    root = net.addHost("root", ip="10.0.0.253/24", inNamespace=False)

    # Connect hosts to switch
    info("*** Creating links\n")
    # try to have router as port 1
    net.addLink(router, s1)
    net.addLink(h1, s1)
    net.addLink(h2, s1)
    net.addLink(h3, s1)
    net.addLink(h4, s1)
    net.addLink(root, s1)

    # connect controller to switch
    # dns = net.addHost("dns", ip="10.0.0.253/24", defaultRoute="via 10.0.254")
    # net.addLink(dns, s1)

    # Start network
    info("*** Starting network\n")
    net.start()

    # setting dns for hosts
    # h1.cmd(
    #     'bash -c "echo nameserver 10.0.0.253 > /tmp/resolv.conf; mount --bind /tmp/resolv.conf /etc/resolv.conf || true"'
    # )
    # h2.cmd(
    #     'bash -c "echo nameserver 10.0.0.253 > /tmp/resolv.conf; mount --bind /tmp/resolv.conf /etc/resolv.conf || true"'
    # )
    # h3.cmd(
    #     'bash -c "echo nameserver 10.0.0.253 > /tmp/resolv.conf; mount --bind /tmp/resolv.conf /etc/resolv.conf || true"'
    # )
    # h4.cmd(
    #     'bash -c "echo nameserver 10.0.0.254 > /tmp/resolv.conf; mount --bind /tmp/resolv.conf /etc/resolv.conf || true"'
    # )
    # Add router namespace
    info("*** Configuring router\n")
    # Create ISP uplink interfaces
    info("*** Setting up ISP uplinks\n")
    router.cmd("ip link add router-isp1 type veth peer name isp1-router")
    router.cmd("ip link set router-isp1 up")
    router.cmd("ip addr add 192.168.1.2/24 dev router-isp1")

    router.cmd("ip link add router-isp2 type veth peer name isp2-router")
    router.cmd("ip link set router-isp2 up")
    router.cmd("ip addr add 192.168.2.2/24 dev router-isp2")

    # Move ISP ends of links to root namespace
    router.cmd("ip link set isp1-router netns 1")
    router.cmd("ip link set isp2-router netns 1")

    # Configure ISP interfaces in root namespace
    info("*** Configuring ISP interfaces in root namespace\n")
    # These run in the root namespace
    root.cmd("ip addr add 192.168.1.1/24 dev isp1-router")
    root.cmd("ip link set isp1-router up")
    root.cmd("ip addr add 192.168.2.1/24 dev isp2-router")
    root.cmd("ip link set isp2-router up")

    # Set up default routes on router
    # router.cmd("ip route add default via 192.168.1.1 metric 100")
    # router.cmd("ip route add default via 192.168.2.1 metric 200")

    # Set up NAT in root namespace
    info("*** Setting up NAT for internet connectivity\n")
    # Enable IP forwarding in root namespace, and router space
    router.cmd("sysctl -w net.ipv4.ip_forward=1")
    root.cmd("sysctl -w net.ipv4.ip_forward=1")
    # Set up NAT (replace ens33 with your actual interface)
    root.cmd("iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE")

    router.cmd("iptables -t nat -A POSTROUTING -o router-isp1 -j MASQUERADE")
    router.cmd("iptables -t nat -A POSTROUTING -o router-isp2 -j MASQUERADE")

    # Start custom DNS forwarder in root namespace
    # root.cmd("ip link add dns-ovs type veth peer name ovs-dns")
    # root.cmd("ip link set dns-ovs up")
    # root.cmd("ip link set ovs-dns up")
    # net.addLink(root, s1)

    # Configure DNS on hosts
    for host in net.hosts:
        if host.name != "dns":
            host.cmd("rm -f /etc/resolv.conf")
            host.cmd('echo "nameserver 10.0.0.253" > /etc/resolv.conf')
            # host.cmd("sysctl -w net.ipv4.conf.all.rp_filter=0")
            # host.cmd("sysctl -w net.ipv4.conf.default.rp_filter=0")
            # host.cmd("sysctl -w net.core.rmem_max=16777216")
            # host.cmd("sysctl -w net.core.wmem_max=16777216")
            # host.cmd("sysctl -w net.core.netdev_max_backlog=5000")
            # host.cmd('echo "soft nofile 100000"|sudo tee -a /etc/security/limits.conf')
            # host.cmd('echo "hard nofile 100000"|sudo tee -a /etc/security/limits.conf')

    h4.cmd('echo "nameserver 10.0.0.254" > /etc/resolv.conf')

    info("*** Running apps at different hosts\n")
    # starting up controller and the dns policy engine
    # root.cmd( "sudo /Users/dian/Code/dbr/src/dns_policy/env/bin/python /Users/dian/Code/dbr/src/dns_policy/policy_engine.py --listen 10.0.0.253 --port 53 &")

    # root.cmd( "/Users/dian/Code/dbr/src/controller/env/bin/python /Users/dian/Code/dbr/src/controller/ryu_app.py &")
    # get the router running
    output = router.cmd(
        "/Users/dian/Code/dbr/src/agent/env/bin/python /Users/dian/Code/dbr/src/agent/rest_agent.py > /dev/null 2>&1 & echo $!"
    )
    info(f"*** [debug] output: {output}\n")
    agent_pid = int(output.strip().split("\n")[-1])
    info(f"*** Started sdn agent with pid: {agent_pid}\n")

    # Show network information
    # info("*** Network configuration:\n")
    # info("*** Router interfaces:\n")
    # info(router.cmd("ifconfig -a"))
    # info("\n*** Root namespace interfaces:\n")
    # info(root.cmd("ifconfig -a"))

    # Run CLI
    CLI(net)

    # Clean up
    info("*** Stopping network\n")
    # Clean up namespaces and interfaces
    router.cmd(f"kill {agent_pid}")
    root.cmd("iptables -t nat -F POSTROUTING")
    root.cmd("ip link del isp1-router")
    root.cmd("ip link del isp2-router")
    net.stop()


if __name__ == "__main__":
    # Check if running as root
    if os.geteuid() != 0:
        exit("You need to run this script as root!")

    # Clean up from previous runs
    os.system("mn -c")

    # Configure logging
    setLogLevel("info")

    # Create and run the network
    setupRoutingTopology()
