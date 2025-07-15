import subprocess
import time
import random
import os
import csv
from datetime import datetime

# CONFS
POLICY_ENGINE_URL = ""
TARGET_TEMPLATE = "http://{}"
TOTAL_DOMAINS = 10239
REPS_PER_SCALE = 10
RULE_SIZES = [10, 100, 500, 1000, 5000]
PROBE_INTERVAL = 0.001
CURL_TIMEOUT = 1
LOG_FILE = "resposiveness_results.csv"

EXPERIMENT_SEED = 217813
random.seed(EXPERIMENT_SEED)


# =====  SETUP =====
all_domains = [f"test{int(i / 256) + 1}_{i}.com" for i in range(1, TOTAL_DOMAINS + 1)]


# check log path
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, mode="w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "timestamp",
                "domain",
                "rule_count",
                "run_index",
                "policy_change",
                "t0",
                "t1",
                "responsiveness_ms",
            ]
        )


def run_curl_probe(domain):
    url = TARGET_TEMPLATE.format(domain)
    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "--max-time",
                str(CURL_TIMEOUT),
                "--write-out",
                "%{http_code}",
                url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        status = result.stdout.decode().strip()
        return status
    except Exception as e:
        return "ERR"


def issue_policy_change(domain, action):
    data = f'{{"domain": "{domain}", "action": "{action}"}}'
    try:
        subprocess.run(
            [
                "curl",
                "-s",
                "-X",
                "POST",
                POLICY_ENGINE_URL,
                "-H",
                "Content-Type: application/json",
                "-d",
                data,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1,
        )
    except Exception as e:
        pass


def get_unique_test_domains(samples, num):
    """
    Returns [num] number of domains from samples
    """
    used_domains = set()
    domains = []
    for i in range(1, num):
        while True:
            domain = random.choice(samples)
            if domain in used_domains:
                continue
            else:
                domains.append(domain)
                break
    return domains


def batch_adding_rules(domains):
    pass


# ===  EXPERIMENT LOOP ===
for rule_count in RULE_SIZES:
    samples = random.sample(all_domains, rule_count)

    # get the domains sets chosen for this rule count
    test_domains = get_unique_test_domains(samples, rule_count)
    for run_index in range(1, REPS_PER_SCALE + 1):
        # === 1. probing
        pass
