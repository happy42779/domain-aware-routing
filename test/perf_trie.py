import time
import random
import sys
import string
import os


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


def generate_random_domain(
    tlds=None, min_length=2, max_length=5, min_parts=2, max_parts=4
):
    """Generate a random domain name for testing"""
    if tlds is None:
        tlds = ["com", "org", "net", "io", "co", "dev"]

    num_parts = random.randint(min_parts, max_parts)
    parts = []

    # Generate random subdomain parts
    for _ in range(num_parts - 1):
        length = random.randint(min_length, max_length)
        part = "".join(random.choices(string.ascii_lowercase, k=length))
        parts.append(part)

    # Add a TLD
    parts.append(random.choice(tlds))

    return ".".join(parts)


def test_lookup_performance(trie_instance, num_domains=10000, lookup_repeats=10000):
    """
    Test the lookup performance of a DNS trie implementation.

    Args:
        trie_instance: An instance of the DNSTrie class to test
        num_domains: Number of domains to insert into the trie
        lookup_repeats: Number of lookups to perform for timing

    Returns:
        Dict with performance metrics
    """
    print(f"Preparing test with {num_domains} domains and {lookup_repeats} lookups...")

    # Generate test domains
    domains = []
    for _ in range(num_domains):
        domains.append(generate_random_domain())

    # Add some wildcards (5%)
    wildcard_count = num_domains // 20  # 5%
    for _ in range(wildcard_count):
        domain = generate_random_domain()
        if "." in domain:
            wildcard_domain = "*." + ".".join(domain.split(".")[1:])
            domains.append(wildcard_domain)

    # Insert domains into trie
    print("Populating trie...")
    for domain in domains:
        rule = (
            {"action": "block"}
            if random.random() < 0.5
            else {"action": "route", "port": 8080}
        )
        trie_instance.insert(domain, rule)

    # Prepare lookup domains
    lookup_domains = []
    for _ in range(lookup_repeats):
        # 80% existing domains, 20% non-existent
        if random.random() < 0.8:
            lookup_domains.append(random.choice(domains))
        else:
            lookup_domains.append(generate_random_domain())

    # Warm-up (to avoid JIT compilation effects)
    print("Warming up...")
    for _ in range(min(100, lookup_repeats)):
        trie_instance.lookup(random.choice(lookup_domains))

    # Measure lookup performance
    print("Measuring lookup performance...")
    start_time = time.time()
    for domain in lookup_domains:
        trie_instance.lookup(domain)
    end_time = time.time()

    total_time = end_time - start_time
    avg_time_ms = (total_time / lookup_repeats) * 1000
    lookups_per_second = lookup_repeats / total_time

    # Result
    result = {
        "total_domains": num_domains,
        "total_lookups": lookup_repeats,
        "total_time_seconds": total_time,
        "avg_lookup_time_ms": avg_time_ms,
        "lookups_per_second": lookups_per_second,
    }

    # Print summary
    print("\n" + "=" * 50)
    print(" DNS TRIE LOOKUP PERFORMANCE ")
    print("=" * 50)
    print(f"Total domains in trie: {num_domains:,}")
    print(f"Total lookups performed: {lookup_repeats:,}")
    print(f"Total lookup time: {total_time:.4f} seconds")
    print(f"Average lookup time: {avg_time_ms:.6f} ms per domain")
    print(f"Lookups per second: {lookups_per_second:,.2f}")
    print("=" * 50)

    return result


if __name__ == "__main__":
    from trie import DomainTrie

    trie = DomainTrie(["1.1.1.1"])

    # Run the performance test
    # You can adjust these parameters as needed
    test_lookup_performance(trie, num_domains=100000, lookup_repeats=50000)
