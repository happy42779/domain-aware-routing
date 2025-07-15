import unittest
from typing import Dict, List
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from trie import DomainTrie


class TestDNSTrie(unittest.TestCase):
    def setUp(self):
        # Create a fresh DNS trie for each test
        self.trie = DomainTrie(["1.1.1.1"])

        # Set up some common rules
        self.trie.insert("example.com", {"action": "block"})
        self.trie.insert("*.example.com", {"action": "route", "gw": "192.168.1.1"})
        self.trie.insert("api.example.com", {"action": "route", "port": 8080})
        self.trie.insert(
            "google.com", {"action": "route", "upstreams": ["8.8.8.8", "8.8.4.4"]}
        )
        self.trie.insert("test.org", {"action": "block"})

    def test_exact_matches(self):
        """Test exact domain matches"""
        # Check exact match for example.com
        rule = self.trie.lookup("example.com")
        self.assertEqual(rule.get("action"), "block")

        # Check exact match for api.example.com
        rule = self.trie.lookup("api.example.com")
        self.assertEqual(rule.get("action"), "route")
        self.assertEqual(rule.get("port"), 8080)

        # Check exact match for google.com
        rule = self.trie.lookup("google.com")
        self.assertEqual(rule.get("action"), "route")
        self.assertEqual(rule.get("upstreams"), ["8.8.8.8", "8.8.4.4"])

        # Check exact match for test.org
        rule = self.trie.lookup("test.org")
        self.assertEqual(rule.get("action"), "block")

    def test_wildcard_matches(self):
        """Test wildcard domain matches"""
        # www.example.com should match *.example.com
        rule = self.trie.lookup("www.example.com")
        self.assertEqual(rule.get("action"), "route")
        self.assertEqual(rule.get("gw"), "192.168.1.1")

        # sub.example.com should match *.example.com
        rule = self.trie.lookup("sub.example.com")
        self.assertEqual(rule.get("action"), "route")
        self.assertEqual(rule.get("gw"), "192.168.1.1")

        # deep.sub.example.com should match *.example.com
        rule = self.trie.lookup("deep.sub.example.com")
        self.assertEqual(rule.get("action"), "route")
        self.assertEqual(rule.get("gw"), "192.168.1.1")

    def test_wildcard_precedence(self):
        """Test that exact matches take precedence over wildcards"""
        # api.example.com has an exact rule that should take precedence
        # over the *.example.com wildcard rule
        rule = self.trie.lookup("api.example.com")
        self.assertEqual(rule.get("port"), 8080)  # From the exact match
        self.assertNotEqual(rule.get("gw"), "192.168.1.1")  # Not from the wildcard

    def test_non_existent_domains(self):
        """Test lookup behavior for domains that don't match any rules"""
        # No rule for unknown.com
        rule = self.trie.lookup("unknown.com")
        self.assertEqual(rule, {})

        # No rule for sub.unknown.com
        rule = self.trie.lookup("sub.unknown.com")
        self.assertEqual(rule, {})

    def test_empty_domain(self):
        """Test that empty domains raise ValueError"""
        with self.assertRaises(ValueError):
            self.trie.insert("", {"action": "block"})

        with self.assertRaises(ValueError):
            self.trie.lookup("")

    def test_partial_matches(self):
        """Test behavior with partial domain matches"""
        # Insert a domain with subdomain
        self.trie.insert("sub.partial.com", {"action": "block"})

        # Lookup the parent domain - should not match
        rule = self.trie.lookup("partial.com")
        self.assertEqual(rule, {})

        # Lookup a different subdomain - should not match
        rule = self.trie.lookup("other.partial.com")
        self.assertEqual(rule, {})

    def test_subdomain_wildcards(self):
        """Test wildcards at different subdomain levels"""
        # Add wildcard rules at different levels
        self.trie.insert("*.multi.level.com", {"action": "block", "level": "third"})
        self.trie.insert("*.level.com", {"action": "block", "level": "second"})

        # Test third-level wildcard match
        rule = self.trie.lookup("test.multi.level.com")
        self.assertEqual(rule.get("level"), "third")

        # Test second-level wildcard match
        rule = self.trie.lookup("direct.level.com")
        self.assertEqual(rule.get("level"), "second")

        # Second-level should apply to deeper level
        rule = self.trie.lookup("test.other.level.com")
        self.assertEqual(rule.get("level"), "second")

    def test_complex_trie_structure(self):
        """Test the structure of a more complex trie"""
        # Build a more complex trie
        domains = [
            ("com", {"action": "default"}),
            ("example.com", {"action": "block"}),
            ("api.example.com", {"action": "route", "port": 8080}),
            ("v1.api.example.com", {"action": "route", "port": 8081}),
            ("org", {"action": "default"}),
            ("test.org", {"action": "block"}),
            ("*.test.org", {"action": "route", "gw": "10.0.0.1"}),
        ]

        # Create fresh trie and insert all domains
        trie = DomainTrie(["1.1.1.1"])
        for domain, rule in domains:
            trie.insert(domain, rule)

        # Check structure by lookups
        self.assertEqual(trie.lookup("com").get("action"), "default")
        self.assertEqual(trie.lookup("example.com").get("action"), "block")
        self.assertEqual(trie.lookup("api.example.com").get("port"), 8080)
        self.assertEqual(trie.lookup("v1.api.example.com").get("port"), 8081)
        self.assertEqual(trie.lookup("org").get("action"), "default")
        self.assertEqual(trie.lookup("test.org").get("action"), "block")
        self.assertEqual(trie.lookup("sub.test.org").get("gw"), "10.0.0.1")

    def test_tld_only_domains(self):
        """Test behavior with TLD-only domains"""
        # Insert rules for TLDs
        self.trie.insert("com", {"action": "log"})
        self.trie.insert("org", {"action": "log"})

        # Check exact matches
        self.assertEqual(self.trie.lookup("com").get("action"), "log")
        self.assertEqual(self.trie.lookup("org").get("action"), "log")

        # TLD rules should not affect subdomains
        self.assertEqual(self.trie.lookup("example.com").get("action"), "block")
        self.assertEqual(self.trie.lookup("test.org").get("action"), "block")

    def test_wildcard_handling_edge_cases(self):
        """Test edge cases with wildcard handling"""
        # Insert a literal domain with * character (not a wildcard)
        self.trie.insert("*.literal.com", {"action": "special"})

        # Insert a domain with * as a subdomain label
        special_domain = "*.special.com"
        self.trie.insert(special_domain, {"action": "wildcard"})

        # Lookup domains that should match the literal *
        self.assertEqual(self.trie.lookup("*.literal.com").get("action"), "special")

        # Lookup domains that should match the wildcard
        self.assertEqual(self.trie.lookup("sub.special.com").get("action"), "wildcard")
        self.assertEqual(
            self.trie.lookup("another.special.com").get("action"), "wildcard"
        )


if __name__ == "__main__":
    unittest.main()
