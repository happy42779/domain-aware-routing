import unittest
import sys
import os
import tempfile
import time
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from conf import Conf


class ConfTest(unittest.TestCase):
    def setUp(self):
        self.parser = Conf()
        self.sample_config = """
        # Sample configuration
        listen-address=192.168.1.5
        listen-port=5353
        
        # Default upstream servers
        server=8.8.8.8
        server=1.1.1.1
        
        # Domain-specific servers
        server=/google.com/1.1.1.3
        server=/*.google.com/9.9.9.9
        
        # Local DNS entries
        address=/router.my/192.168.1.1
        
        # Blocked domains
        block=/facebook.com/
        block=/*.baidu.com/
        
        # Routing
        route=/apple.com/10.0.0.1
        """

        # Create a temporary file
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        with open(self.temp_file.name, "w") as f:
            f.write(self.sample_config)

        # print for debug

    def tearDown(self):
        # Clean up temporary file
        os.unlink(self.temp_file.name)

    def pretty_print_config(self, config):
        """Pretty print the configuration for visual inspection"""
        print("\n" + "=" * 80)
        print("PARSED CONFIGURATION:")
        print("=" * 80)

        # Basic settings
        print(f"Listen Address: {config['listen_address']}")
        print(f"Listen Port:    {config['listen_port']}")

        # Default Upstreams
        print("\nDEFAULT UPSTREAM SERVERS:")
        print("-" * 50)
        for i, ups in enumerate(config["default_upstreams"]):
            print(f"{i + 1}. IP: {ups:<15}")

        # Domain Rules
        print("\nDOMAIN RULES:")
        print("-" * 80)
        print(f"{'DOMAIN':<25} {'ACTION':<10}")
        print("-" * 80)

        for rule in config["rules"]:
            domain = rule["domain"]
            action = rule.get("action", "")

            # Format details based on rule type
            if action == "block":
                details = "BLOCKED"
            elif action == "route":
                if "upstreams" in rule:
                    upstream_list = []
                    for up in rule["upstreams"]:
                        if "ip" in up:
                            upstream_list.append(f"{up['ip']}:{up['port']}")
                        else:
                            upstream_list.append(f"{up['host']}:{up['port']}")
                    details = f"Upstreams: {', '.join(upstream_list)}"
                elif "gateway" in rule:
                    details = f"Gateway: {rule['gateway']}"
                else:
                    details = "Unknown route type"
            else:
                details = json.dumps(
                    {k: v for k, v in rule.items() if k not in ["domain", "action"]}
                )

            print(f"{domain:<25} {action:<10} {details}")

        print("=" * 80 + "\n")

    def test_parse_file_with_visual(self):
        """Test parsing configuration from file with visual output"""
        print("\nRunning test_parse_file_with_visual")
        print("Loading configuration file...")

        # Measure parsing time
        start_time = time.time()
        config = self.parser.parse_file(self.temp_file.name)
        parse_time = time.time() - start_time

        print(f"Configuration parsed in {parse_time * 1000:.2f} ms")

        # Display the parsed configuration
        self.pretty_print_config(config)

        # Run assertions
        self.assertEqual(config["listen_address"], "192.168.1.5")
        self.assertEqual(config["listen_port"], 5353)
        self.assertEqual(len(config["default_upstreams"]), 2)
        self.assertEqual(len(config["rules"]), 6)

        # Find specific rules
        google_rule = next(
            (r for r in config["rules"] if r["domain"] == "google.com"), None
        )
        self.assertIsNotNone(google_rule)

        # Check wildcard rule
        wildcard_rule = next(
            (r for r in config["rules"] if r["domain"] == "*.google.com"), None
        )
        self.assertIsNotNone(wildcard_rule)

        print("All assertions passed!\n")

    def test_invalid_config_with_visual(self):
        """Test detection of syntax errors with visual output"""
        print("\nRunning test_invalid_config_with_visual")

        # First test basic syntax errors (first pass)
        basic_syntax_error = """
        # This configuration has basic syntax errors
        listen-address without-equals-sign
        unknown=directive
        server missing-equals
        """

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(basic_syntax_error.encode("utf-8"))
            syntax_file = f.name

        print("\nTesting basic syntax errors (first pass):")
        print("Expected behavior: Parser should detect syntax errors in first pass")

        try:
            self.parser.parse_file(syntax_file)
            print("ERROR: Parser did not detect basic syntax errors!")
        except ValueError as e:
            print("\nBASIC SYNTAX ERRORS DETECTED (FIRST PASS):")
            print("-" * 80)
            error_msg = str(e)
            print(error_msg)
            print("-" * 80)

            # Verify error contains line info
            self.assertIn("Line", error_msg)
            self.assertIn("Missing '='", error_msg)
            print("✓ Error message includes missing equals sign")

        # Clean up
        os.unlink(syntax_file)

    def test_invalid_ip_with_visual(self):
        """Test detection of value errors with visual output"""
        print("\nRunning test_invalid_ip_with_visual")
        # Now test format errors (second pass)
        format_error = """
        # This configuration has format errors that should be caught in second pass
        listen-address=999.999.999.999
        """

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(format_error.encode("utf-8"))
            format_file = f.name

        print("\nTesting format errors (second pass):")
        print("Expected behavior: Parser should detect format errors during processing")

        try:
            self.parser.parse_file(format_file)
            print("ERROR: Parser did not detect format errors!")
        except ValueError as e:
            print("\nFORMAT ERRORS DETECTED (SECOND PASS):")
            print("-" * 80)
            error_msg = str(e)
            print(error_msg)
            print("-" * 80)

            # Verify error contains validation failures
            self.assertIn("Invalid IP address", error_msg)
            print("✓ Error message includes IP validation failure")

        # Clean up
        os.unlink(format_file)
        print("\nTest completed successfully\n")

        # more cases for invalid IP
        # Now test format errors (second pass)
        format_error = """
        # This configuration has format errors that should be caught in second pass
        server=/domain/invalid:ip:format
        """

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(format_error.encode("utf-8"))
            format_file = f.name

        print("\nTesting format errors (second pass):")
        print("Expected behavior: Parser should detect format errors during processing")

        try:
            self.parser.parse_file(format_file)
            print("ERROR: Parser did not detect format errors!")
        except ValueError as e:
            print("\nFORMAT ERRORS DETECTED (SECOND PASS):")
            print("-" * 80)
            error_msg = str(e)
            print(error_msg)
            print("-" * 80)

            # Verify error contains validation failures
            self.assertIn("Invalid upstream in server directive", error_msg)
            print("✓ Error message includes IP validation failure")

        # Clean up
        os.unlink(format_file)

        # more cases for invalid IP
        # Now test format errors (second pass)
        format_error = """
        # This configuration has format errors that should be caught in second pass
        address=/router.local/999.999.999.999
        """

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(format_error.encode("utf-8"))
            format_file = f.name

        print("\nTesting format errors (second pass):")
        print("Expected behavior: Parser should detect format errors during processing")

        try:
            self.parser.parse_file(format_file)
            print("ERROR: Parser did not detect format errors!")
        except ValueError as e:
            print("\nFORMAT ERRORS DETECTED (SECOND PASS):")
            print("-" * 80)
            error_msg = str(e)
            print(error_msg)
            print("-" * 80)

            # Verify error contains validation failures
            self.assertIn("Invalid static ip address", error_msg)
            print("✓ Error message includes IP validation failure")

        # Clean up
        os.unlink(format_file)

        print("\nTest completed successfully\n")

    def test_invalid_port_with_visual(self):
        """Test detection of syntax errors with visual output"""
        print("\nRunning test_invalid_port_with_visual")
        # Now test format errors (second pass)
        format_error = """
        # This configuration has format errors that should be caught in second pass
        listen-port=99999
        """

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(format_error.encode("utf-8"))
            format_file = f.name

        print("\nTesting format errors (second pass):")
        print("Expected behavior: Parser should detect format errors during processing")

        try:
            self.parser.parse_file(format_file)
            print("ERROR: Parser did not detect format errors!")
        except ValueError as e:
            print("\nFORMAT ERRORS DETECTED (SECOND PASS):")
            print("-" * 80)
            error_msg = str(e)
            print(error_msg)
            print("-" * 80)

            # Verify error contains validation failures
            self.assertIn("Port must be between", error_msg)
            print("✓ Error message includes port range validation")

        # Clean up
        os.unlink(format_file)
        print("\nTest completed successfully\n")

    def test_large_config_performance(self):
        """Test performance with a large configuration file"""
        print("\nRunning test_large_config_performance")

        # Generate a large configuration file
        large_config = ["# Large configuration file with many entries"]
        large_config.append("listen-address=192.168.1.1")
        large_config.append("listen-port=53")

        # Add default servers
        large_config.append("server=8.8.8.8")
        large_config.append("server=1.1.1.1")

        # Add many domain rules
        print("Generating large configuration with many domain rules...")

        # Add blocked domains
        for i in range(500):
            large_config.append(f"block=/ad{i}.example.com/")

        # Add server domains
        for i in range(500):
            large_config.append(f"server=/server{i}.example.com/10.0.0.{i % 255 + 1}")

        # Add address entries
        for i in range(500):
            large_config.append(f"address=/device{i}.local/192.168.1.{i % 255 + 1}")

        # Add route entries
        for i in range(500):
            large_config.append(f"route=/service{i}.example.com/172.16.1.{i % 255 + 1}")

        # Write to file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write("\n".join(large_config).encode("utf-8"))
            temp_file = f.name

        # Parse and measure performance
        print(f"Parsing configuration with {len(large_config)} lines...")
        start_time = time.time()
        config = self.parser.parse_file(temp_file)
        parse_time = time.time() - start_time

        print(f"Configuration parsed in {parse_time * 1000:.2f} ms")
        print(
            f"Number of lines processed per second: {len(large_config) / parse_time:.2f}"
        )
        print(f"Total parsed rules: {len(config['rules'])}")

        # Print sample of the rules (first 5 of each type)
        print("\nSAMPLE OF PARSED RULES:")
        print("-" * 80)

        rule_types = {}
        for rule in config["rules"]:
            rule_type = rule.get("action", "")
            if rule_type not in rule_types:
                rule_types[rule_type] = []
            if len(rule_types[rule_type]) < 5:  # Only keep first 5 of each type
                rule_types[rule_type].append(rule)

        for rule_type, rules in rule_types.items():
            print(f"\n{rule_type.upper()} RULES (showing {len(rules)} of many):")
            for rule in rules:
                print(f"  - {rule['domain']}")

        # Clean up
        os.unlink(temp_file)
        print("\nPerformance test completed successfully\n")


if __name__ == "__main__":
    # Run the tests with visual output
    suite = unittest.TestSuite()
    suite.addTest(ConfTest("test_parse_file_with_visual"))
    suite.addTest(ConfTest("test_invalid_config_with_visual"))
    suite.addTest(ConfTest("test_invalid_ip_with_visual"))
    suite.addTest(ConfTest("test_invalid_port_with_visual"))
    suite.addTest(ConfTest("test_large_config_performance"))

    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
