import subprocess
import ipaddress
import tempfile
import random
import os
import csv
import json
from typing import Dict, List, Tuple, Any
import requests
import argparse
import time

# =====  SETUP =====
# CONFS
TARGET_TEMPLATE = "http://{}"
TOTAL_DOMAINS = 10239
REPS_PER_SCALE = 10
RULE_SIZES = [10, 100, 500, 1000, 2000, 5000]
# RULE_SIZES = [10, 100, 500]
CURL_TIMEOUT = 1
DELAY_LOG = "delay_pbr.txt"
HTTP_HEADER = "Content-Type=application/json"
MAX_PROBE_RETRY = 200
UPSTREAM = "10.0.253.1"
PORT = 5333

EXPERIMENT_SEED = 2178133


random.seed(EXPERIMENT_SEED)

all_domains = [
    f"test{int(i / 256) + 1}-{i % 256}.com" for i in range(1, TOTAL_DOMAINS + 1)
]
rule_map = {}


def write_delay_data(rule_count: int, result: List):
    # check log path
    fname = DELAY_LOG
    with open(fname, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                f"[{rule_count}]",
                "run_index",
                "domain",
                "responsiveness_s",
            ]
        )
        writer.writerows(result)


# ============== FUNCTIONS  =================
def in_same_subnet(ip1: str, ip2: str, prefix_length=24) -> bool:
    """
    Deciding if ip1 is in ip2/prefix_length
    """
    # print(f"Deciding if {ip1} and {ip2} are in the same subnet")
    network = ipaddress.IPv4Network(f"{ip2}/{prefix_length}", strict=False)
    # print(f"Network is: {network}")
    return ipaddress.IPv4Address(ip1.strip()) in network


def run_curl_probe(domain: str, gw: str, debug: bool = False) -> Tuple[bool, str]:
    # Simulate dynamic rule (you could replace this with iptables/OVS logic)

    # Bash script content
    bash_script = f"""#!/bin/bash
    curl -s --max-time 1 --write-out "%{{time_total}}\n%{{http_code}}\n" http://{domain}
    echo $?
    """

    if debug:
        print(f"Testing domain: {domain}, with gw: {gw}")

    # Write to temporary file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".sh") as f:
        f.write(bash_script)
        temp_script_path = f.name

    # Make it executable
    os.chmod(temp_script_path, 0o755)

    # Run it using subprocess
    result = subprocess.run(
        [temp_script_path], capture_output=True, text=True, timeout=2
    )

    output = result.stdout.strip()

    # Output results
    if debug:
        print(output)

    success = False
    delay = ""
    try:
        (ip, delay, http_code, exit_code) = output.rsplit("\n", 3)
        if debug:
            print(
                f"target: {domain}, ip: {ip}, delay: {delay}, http_code:{http_code}, exit_code: {exit_code}"
            )
        if in_same_subnet(ip, gw, 24) and int(http_code) == 200:
            success, delay = True, delay
        else:
            success, delay = False, ""

    except ValueError as e:
        print(f"having problem parsing output: {e}\n{domain}:{output}")
    # Clean up
    os.remove(temp_script_path)

    return success, delay


def generate_dnsmasq_ipset_conf(domains: List, ipset_name: str):
    """
    Generate ipset = /domain/[ipset] rules.
    Directly output it to a conf file
    """
    rule_size = len(domains)
    lines = [
        "no-resolv",
        f"server={UPSTREAM}#{PORT}",
        "listen-address=10.0.0.254",
        "port=53",
    ]
    for d in domains:
        lines.append(f"ipset=/{d}/{ipset_name}")
    content = "\n".join(lines)

    with open(f"./confs/conf_{rule_size}.conf", "w") as f:
        f.write(content)


def get_unique_test_domains(samples: List, num: int) -> List:
    """
    Returns [num] number of domains from samples
    """
    used_domains = set()
    domains = []
    for i in range(1, num + 1):
        while True:
            domain = random.choice(samples)
            if domain in used_domains:
                continue
            else:
                used_domains.add(domain)
                domains.append(domain)
                break
    return domains


def start_dnsmasq(rule_count: int, pid: str):
    cmd = [
        "sudo",
        "-E",
        "mnexec",
        "-a",
        pid,
        "dnsmasq",
        "--conf-file=confs/conf_{}.conf".format(rule_count),
    ]

    result = subprocess.run(cmd)


# ===  EXPERIMENT LOOP ===
def run(rule_count: int, pid: str):
    samples = random.sample(all_domains, rule_count)

    # get the domains sets chosen for this rule count
    test_domains = get_unique_test_domains(samples, rule_count)

    # rule_map = {}

    # generate the file
    generate_dnsmasq_ipset_conf(test_domains, "isp1")
    start_dnsmasq(rule_count, pid)
    # print result
    result = []
    gw = "192.168.1.1"
    # print("============= Overall Delay Results ==============")
    for run_index in range(1, REPS_PER_SCALE + 1):
        # === 1. probing
        target = random.choice(test_domains)

        success, delay = run_curl_probe(target, gw, False)

        result.append([run_index, target, delay.strip()])

    # write to file
    write_delay_data(rule_count, result)

    result = []


def gen_conf():
    for n in RULE_SIZES:
        samples = random.sample(all_domains, n)
        test_domains = get_unique_test_domains(samples, n)
        generate_dnsmasq_ipset_conf(test_domains, "isp1")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Specify rule size.")
    parser.add_argument("--rules", type=int, help="Number of rules")
    parser.add_argument("--gen", action="store_true", help="Generate the conf files")
    parser.add_argument(
        "--pid", type=str, help="Pid to the namespace to run dnsmasq in"
    )
    args = parser.parse_args()
    if args.gen:
        gen_conf()
    elif args.rules and args.pid:
        run(args.rules, args.pid)
    else:
        print("Missing argument...")
