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

# =====  SETUP =====
# CONFS
POLICY_ENGINE_URL = "http://10.0.0.253:8054/api/rules"
TARGET_TEMPLATE = "http://{}"
TOTAL_DOMAINS = 10239
REPS_PER_SCALE = 10
RULE_SIZES = [10, 100, 500, 1000, 5000]
# RULE_SIZES = [10, 100, 500]
PROBE_INTERVAL = 0.02
CURL_TIMEOUT = 1
# DELAY_LOG = "delay.txt"
RESPONSE_LOG = "response.txt"
HTTP_HEADER = "Content-Type=application/json"
MAX_PROBE_RETRY = 200

EXPERIMENT_SEED = 2178133


random.seed(EXPERIMENT_SEED)

all_domains = [
    f"test{int(i / 256) + 1}-{i % 256}.com" for i in range(1, TOTAL_DOMAINS + 1)
]


# def write_delay_data(rule_count: int, result: List):
#     # check log path
#     fname = DELAY_LOG
#     with open(fname, mode="a", newline="") as f:
#         writer = csv.writer(f)
#         writer.writerow(
#             [
#                 f"[{rule_count}]",
#                 "run_index",
#                 "domain",
#                 "responsiveness_s",
#             ]
#         )
#         writer.writerows(result)


def write_response_data(rule_count: int, result: List):
    # check log path
    fname = RESPONSE_LOG.format(rule_count)
    with open(fname, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                f"[{rule_count}]",
                "run_index",
                "domain",
                "overall_delay",
                "api_delay",
                "policy_delay",
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


def run_curl_probe(domain: str, rule: Dict, debug: bool = False) -> Tuple[bool, str]:
    # Simulate dynamic rule (you could replace this with iptables/OVS logic)

    # Bash script content
    bash_script = f"""#!/bin/bash
    curl -s --max-time 1 --write-out "%{{time_total}}\n%{{http_code}}\n" http://{domain}
    echo $?
    """

    if debug:
        print(f"Testing domain: {domain}, with rule: {rule}")

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
        if "route" in rule:
            (ip, delay, http_code, exit_code) = output.rsplit("\n", 3)
            if debug:
                print(
                    f"target: {domain}, ip: {ip}, delay: {delay}, http_code:{http_code}, exit_code: {exit_code}"
                )
            if in_same_subnet(ip, rule.get("route", ""), 24) and int(http_code) == 200:
                success, delay = True, delay
            else:
                success, delay = False, ""

        elif "block" in rule:
            delay, _, exit_code = output.rsplit("\n", 2)
            if debug:
                print(f"exit_code: {exit_code}")
            if int(exit_code) == 6:
                success, delay = True, delay
            else:
                success, delay = False, ""

    except ValueError as e:
        print(f"having problem parsing output: {e}\n{output}")
    # Clean up
    os.remove(temp_script_path)

    return success, delay


### TODO: directly use a file ?
def run_policy_change_and_probe(
    domain: str, rule: Dict, debug: bool = False
) -> Tuple[bool, str, str, str]:
    # Simulate dynamic rule (you could replace this with iptables/OVS logic)
    #
    if debug:
        print(f"Running probe and change to domain: {domain}, rule: {rule}")

    bash_script = ""
    # prepare the
    if "route" in rule:
        # curl to change the rule
        # "-H",
        # "Content-Type: application/json",
        # "-d",
        # data,
        data = {"domain": domain, "directive": "block", "value": ""}
        data_json = json.dumps(data)

        bash_script = f"""#!/bin/bash

        function probe() {{
            max_count={MAX_PROBE_RETRY}
            count=0
            start_time=$(date +%s.%N)
            while ((count<max_count)); do
                if ! ping -c1 -D -W 0.5 {domain} >>result.log; then
                    end_time=$(date +%s.%N)
                    break
                fi
                sleep {PROBE_INTERVAL}
                ((count++))
            done
            echo "$(echo "($end_time - $start_time)" | bc)"
        }}

        function change() {{
            curl -s --max-time 1 --write-out "\\n%{{time_total}}\\n" -X POST -H "{HTTP_HEADER}" -d '{data_json}' {POLICY_ENGINE_URL}
        }}

        probe &
        change &
        wait
        """

    elif "block" in rule:
        # curl to change the rule
        data = {"domain": domain, "directive": "route", "value": "192.168.1.1"}
        data_json = json.dumps(data)

        bash_script = f"""#!/bin/bash

        function probe() {{
            max_count={MAX_PROBE_RETRY}
            count=0
            start_time=$(date +%s.%N)
            while ((count<max_count)); do
                if ping -c1 -D -W 0.5 {domain} >>result.log; then
                    end_time=$(date +%s.%N)
                    break
                fi
                sleep {PROBE_INTERVAL}
                ((count++))
            done
            echo "$(echo "($end_time - $start_time)" | bc)"
        }}

        function change() {{
            curl -s --max-time 1 --write-out "\\n%{{time_total}}\\n" -X POST -H "{HTTP_HEADER}" -d '{data_json}' {POLICY_ENGINE_URL}
        }}

        probe &
        change &
        wait
        """
    if not bash_script:
        return False, "", "", ""
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
    if debug:
        print(output)

    success = True
    resp_delay = ""
    api_delay = ""
    policy_delay = ""

    (api_resp, policy_delay, resp_delay) = output.rsplit("\n", 2)
    if debug:
        print(
            f"resp_delay: {resp_delay}, api_delay:{api_resp}, policy_delay: {policy_delay}"
        )

    # parse api response
    r = json.loads(api_resp)
    api_delay = r.get("elapsed")

    if not api_delay:
        print("error: failed to parse response")
        success = False

    # Clean up
    os.remove(temp_script_path)

    # return success, delay
    return success, resp_delay, api_delay, policy_delay


def get_unique_test_domains(samples, num) -> List:
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


def batch_adding_rules(test_domains: List, rule_map: Dict, debug: bool = False):
    """
    Odd numbers will be block, and even numbers will be route
    """
    upstreams = ["192.168.1.1", "192.168.2.1"]
    gw_index = 0
    rules = []
    for i, domain in enumerate(test_domains):
        if i % 2 == 0:
            rule = {"domain": domain, "route": upstreams[gw_index], "dbr": True}
            rules.append(rule)
            gw_index = ~gw_index
            rule_map[domain] = rule
        else:
            rule = {"domain": domain, "block": "", "dbr": True}
            rules.append(rule)
            rule_map[domain] = rule

    data = {"rules": rules}

    if debug:
        print("requestdata: ")
        for r in rules:
            print(r)

    # batch_adding_rules
    resp = requests.post(f"{POLICY_ENGINE_URL}/batch", json=data)

    if debug:
        print(f"Got response: {resp.json()}")


# ===  EXPERIMENT LOOP ===
def run(rule_count: int):
    samples = random.sample(all_domains, rule_count)

    # get the domains sets chosen for this rule count
    test_domains = get_unique_test_domains(samples, rule_count)

    rule_map = {}

    # re-build the policy engine with new set of rules
    batch_adding_rules(test_domains, rule_map, False)
    # print(rule_map)

    # print result
    result = []
    # print("============= Overall Delay Results ==============")
    # for run_index in range(1, REPS_PER_SCALE + 1):
    #     # === 1. probing
    #     target = random.choice(test_domains)
    #
    #     success, delay = run_curl_probe(target, rule_map.get(target, ""), False)
    #
    #     # print(
    #     #     f" Run {run_index} | {target} | Correct: {success} | time: {delay.strip()}"
    #     # )
    #     result.append([run_index, target, delay.strip()])
    #
    # # write to file
    # write_delay_data(rule_count, result)

    result = []

    for run_index in range(1, REPS_PER_SCALE + 1):
        target = random.choice(test_domains)

        # retrieve the current rule first
        url = f"{POLICY_ENGINE_URL}/{target}"
        resp = requests.get(url)
        rule = resp.json()
        # rule = rule_map.get(target, "")
        # generate a bash script and run it, in this script,
        # probing is done immediately after changing policy
        success, overall_delay, api_delay, policy_delay = run_policy_change_and_probe(
            target, rule, True
        )
        result.append([run_index, target, overall_delay, api_delay, policy_delay])

    write_response_data(rule_count, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Specify rule size.")
    parser.add_argument("--rules", type=int, required=True)
    args = parser.parse_args()
    run(args.rules)
