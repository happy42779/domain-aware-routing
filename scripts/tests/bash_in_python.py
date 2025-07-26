"""
This file contains some tests of running bash in python.
"""

import subprocess
import tempfile
import os
import ipaddress


def in_same_subnet(ip1, ip2, prefix_length=24):
    """
    Deciding if ip1 is in ip2/prefix_length
    """
    # print(f"Deciding if {ip1} and {ip2} are in the same subnet")
    network = ipaddress.IPv4Network(f"{ip2}/{prefix_length}", strict=False)
    # print(f"Network is: {network}")
    return ipaddress.IPv4Address(ip1.strip()) in network


def run_policy_change_and_probe(domain, rule, gw):
    # Simulate dynamic rule (you could replace this with iptables/OVS logic)

    # Bash script content
    bash_script = f"""#!/bin/bash
    curl -s --max-time 1 --write-out "%{{time_total}}\n%{{http_code}}\n" http://{domain}
    echo $?
    """

    # Write to temporary file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".sh") as f:
        f.write(bash_script)
        temp_script_path = f.name

    # Make it executable
    os.chmod(temp_script_path, 0o755)

    # Run it using subprocess
    result = subprocess.run([temp_script_path], capture_output=True, text=True)

    output = result.stdout.strip()

    # Output results
    print(output)

    success = False
    delay = -1
    if "route" in rule:
        (ip, delay, http_code, exit_code) = output.rsplit("\n", 3)
        print(
            f"ip: {ip}, delay: {delay}, http_code:{http_code}, exit_code: {exit_code}"
        )
        if in_same_subnet(ip, gw, 24) and int(http_code) == 200:
            success, delay = True, delay
        else:
            success, delay = False, -1

    elif "block" in rule:
        exit_code = output.rsplit("\n", 1)[-1]
        print(f"exit_code: {exit_code}")
        if int(exit_code) == 6:
            success, delay = True, 0
        else:
            success, delay = False, -1

    # Clean up
    os.remove(temp_script_path)

    return success, delay


def test_probing():
    rule = {"domain": "test11_90.com", "block": "", "dbr": True}
    rule = {"domain": "test30_253.com", "route": "192.168.1.1", "dbr": True}
    success, delay = run_policy_change_and_probe(
        rule["domain"], rule, rule.get("route")
    )
    if success:
        print(f"Delay is: {delay}")
    else:
        print("Probe Failed")
