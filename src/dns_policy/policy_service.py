from asyncio import create_subprocess_shell
import ipaddress
import logging
import dns
from typing import Any, Dict, List, Tuple, Optional
import traceback
import time
import pdb

from aiohttp import web
from aiohttp.web import Request, Response

from config import ConfigManager
from forward import DNSForwarder

logger = logging.getLogger(__name__)


class PolicyService:
    """
    Service to manage DNS policies dynamically.
    Provides a unified interface for policy management operations.
    """

    def __init__(self, config_manager: ConfigManager, forwarder: DNSForwarder):
        """
        Initialize the policy service with references to the config manager and forwarder.

        Args:
            config_manager: The configuration manager instance
            forwarder: The DNS forwarder instance
        """
        self.config_manager = config_manager
        self.forwarder = forwarder

    async def get_rules(self) -> List[Dict]:
        """
        Get all current rules., this is getting all rules from the static config files.

        Returns:
            List of rule dictionaries
        """
        return self.forwarder.domain_trie.all_rules_flat()

    async def get_rule(self, domain: str) -> Dict:
        """
        Lookup the domain in the domain trie for rules,
        and return the rules.
        """
        return self.forwarder.domain_trie.lookup(domain)[0]

    async def add_rule(self, directive: str, domain: str, value: str = "") -> bool:
        """
        Add a new rule dynamically.
        This logic is reused to implement udpate/merge when the rule exists with
            different directive(s)

        Args:
            directive: Type of rule (block, route, server, address)
            domain: Domain for the rule
            value: Value for the rule (IP for route/address, upstream for server)

        Returns:
            True if successful, False otherwise
        """

        # Validate rule parameters
        if not self._validate_rule_params(directive, domain, value):
            logger.debug(
                f"Failed to validate rule params: directive: {directive}, domain: {domain}, value: {value}"
            )
            return False

        # Create rule dict based on type
        rule = self._create_rule_dict(directive, domain, value)

        # if the rule is static, add it to the cache

        # Update domain trie directly
        await self.forwarder.domain_trie.cow_insert(domain, rule)

        # try to invalidate cache if there's any
        # await self._invalidate_cache(domain)

        if "address" in rule:
            self.forwarder.add_static_cache([rule])

        return True

    async def remove_rule(self, domain: str, directive: str) -> bool:
        """
        Remove a rule for a domain.

        Args:
            domain: Domain to remove rule for

        Returns:
            True if rule was found and removed, False otherwise
        """
        # if directive is static, invalidate the cache is only move needed
        try:
            # Find and remove rule from trie
            found = await self.forwarder.domain_trie.cow_remove(domain, directive)

            # If found in trie, also remove from config manager
            if found:
                await self._invalidate_cache(domain)

            return found

        except Exception as e:
            logger.error(f"Error while remove a rule: {e}")
            return False

    def purge(self):
        """
        Purges the trie, and then purge the cache
        """
        try:
            self.forwarder.domain_trie.purge_trie()
            self.forwarder.purge_cache()
            self.forwarder.domain_trie.pretty_print()
            return True
        except Exception as e:
            logger.error(f"Error purging rules or cache: {e}")
            return False

    def batch_build(self, rules):
        """
        Re-Builds the trie with all the rules provided
        """
        try:
            self.forwarder.domain_trie.purge_trie()
            self.forwarder.build_domain_trie(rules)
            # self.forwarder.domain_trie.pretty_print()
            return True
        except Exception as e:
            logger.error(f"Error batch building rules: {e}")
            return False

    def _validate_rule_params(self, directive: str, domain: str, value: str):
        """
        Validate rule parameters.

        Args:
            directive: Type of rule
            domain: Domain for the rule
            value: Value for the rule

        Raises:
            ValueError: If parameters are invalid
        """
        if not domain or not self._is_valid_domain(domain):
            logger.debug(f"{domain} is not a valid domain")
            return False

        if directive not in ["block", "route", "server", "address"]:
            logger.debug(f"{directive} is not a valid directive")
            return False

        # Validate value based on directive type
        if directive == "block":
            return True
        else:
            return self._is_valid_ip(value)

    def _create_rule_dict(self, directive: str, domain: str, value: str) -> Dict:
        """
        Helper to create rule dict based on type
        """
        rule: Dict[str, Any] = {"domain": domain}

        if directive == "block":
            rule["block"] = ""
            rule["dbr"] = True
        elif directive == "route":
            rule["route"] = value
            rule["dbr"] = True
        elif directive == "server":
            if isinstance(value, list):
                rule["upstream"] = value
            else:
                rule["upstream"] = [value]

        elif directive == "address":
            rule["address"] = value

        return rule

    def _invalidate_cache(self, domain: str) -> bool:
        """
        This function tries to invalidate immediately a cache entry, if it's present
        Ignores the exception for when the entry is not present in the cache, not need to use lock

        Note: if this domain is a wildcard domain, then the existing cache that was matched by an
                wildcard rule, will still be in effect until the ttl expires

        Return value: this return value indicates if a specific domain was present
        """
        # logger.debug(f"Removing an entry from the cache: {domain}")

        try:
            self.forwarder.cache.pop((domain, dns.rdatatype.A))
            logger.debug(f"{(domain, dns.rdatatype.A)} is removed successfully")
            return True
        except KeyError:
            return False

    def _is_valid_domain(self, domain: str):
        """
        Helper function to help check if a domain is valid
        """
        if len(domain) > 253:
            logger.error(f"{domain} length exceeds 253")
            return False

        if domain.startswith("*."):
            domain = domain[2:]

        # check labels
        labels = domain.split(".")
        for label in labels:
            if not label or len(label) > 63:
                logger.error(f"{label} is either None, or its length exceeds 63")
                return False

            if not all(c.isalnum() or c == "-" for c in label):
                logger.error(f"{label} contains invalid char")
                return False

            if label.startswith("-") or label.endswith("-"):
                logger.error(f"{label} is starting or ending with -")
                return False

        return True

    def _is_valid_ip(self, ip: str):
        """
        Helper function to help check if a string is a valid IP address
        """
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError as e:
            logger.error(f"Invalid ip address: {e}")
            return False


class PolicyRestHandler:
    def __init__(
        self, policy_service: PolicyService, host: str = "0.0.0.0", port: int = 8054
    ):
        self.app = None
        self.policy_service = policy_service
        self.host = host
        self.port = port
        self.runner = None

        self._setup_routes()

    async def start(self):
        """
        Start the async server handling policy services
        """
        logger.info(f"Starting policy service handler at {self.host}:{self.port}")

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()

    def _setup_routes(self):
        self.app = web.Application()
        if self.app is None:
            raise Exception("rest api app is None")
        self.app.add_routes(
            [
                web.get("/api/rules", self.get_rules),
                web.get("/api/rules/{domain}", self.get_rule),
                web.post("/api/rules", self.add_rule),
                web.delete("/api/rules", self.remove_rule),
                web.post("/api/rules/batch", self.batch_build),
                web.delete("/api/rules/purge", self.purge),
                # web.delete("/api/rules", self.remove_directive),
            ]
        )

    async def get_rules(self, request: Request) -> Response:
        rules = await self.policy_service.get_rules()
        return web.json_response(rules)

    async def get_rule(self, request):
        domain = request.match_info["domain"]
        rule = await self.policy_service.get_rule(domain)
        if rule:
            return web.json_response(rule)
        else:
            return web.json_response({"error": "Rule not found"}, status=404)

    async def add_rule(self, request: Request) -> Response:
        T1 = time.perf_counter()
        try:
            data = await request.json()

            directive = data.get("directive")
            domain = data.get("domain")
            value = data.get("value", "")

            logger.debug(
                f"Request to add domain: {domain}, directive: {directive}, value: {value}"
            )
            success = await self.policy_service.add_rule(directive, domain, value)

            T2 = time.perf_counter()

            logger.info(f"Time elapsed for adding rule: {T2 - T1:.4f} ")

            if success:
                # debug:
                # self.policy_service.forwarder.domain_trie.pretty_print()
                return web.json_response(
                    {
                        "status": "success",
                        "message": "Rule added",
                        "elapsed": f"{T2 - T1:.4f}",
                    }
                )
            else:
                return web.json_response({"status": "Failed to add rule"}, status=400)

        except Exception as e:
            logger.error(f"Error adding rule: {e}")
            traceback.print_exc()
            return web.json_response({"error": str(e)}, status=500)

    async def remove_rule(self, request) -> Response:
        # domain = request.match_info["domain"]
        T1 = time.perf_counter()
        try:
            data = await request.json()
            domain = data.get("domain")

            directive = data.get("directive")

            logger.debug(f"Request to remove domain: {domain}, directive: {directive}")
            success = await self.policy_service.remove_rule(domain, directive)

            T2 = time.perf_counter()

            logger.info(f"Time elapsed for removing rule: {T2 - T1:.4f}")
            if success:
                # debug:
                # self.policy_service.forwarder.domain_trie.pretty_print()
                return web.json_response(
                    {
                        "status": "success",
                        "message": "Rule removed",
                        "elapsed": f"{T2 - T1:.4f}",
                    }
                )
            else:
                return web.json_response({"error": "Rule not found"}, status=404)
        except Exception as e:
            logger.error(f"Error removing rule: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def batch_build(self, request) -> Response:
        try:
            data = await request.json()

            rules = data.get("rules")
            # verify ruels
            if not isinstance(rules, List):
                logger.debug("Type error: expected list, got type(rules)")
                raise Exception(f"Expected List, got {type(rules)}")

            logger.debug(f"Received {len(rules)} rules for batch building")

            # build the trie
            success = self.policy_service.batch_build(rules)

            if success:
                return web.json_response(
                    {"status": "success", "message": "Trie built successfully"}
                )
            else:
                return web.json_response(
                    {"error": "Failed building the trie."}, status=500
                )

        except Exception as e:
            logger.error(f"Error batch building rules: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def purge(self, request) -> Response:
        try:
            # erase the trie
            success = self.policy_service.purge()
            if success:
                return web.json_response(
                    {"status": "success", "message": "Rules purged"}
                )

            else:
                return web.json_response(
                    {"error": "Unknown error while purging rules!"}, status=500
                )
        except Exception as e:
            logger.error(f"Error erasing building rules: {e}")
            return web.json_response({"error": str(e)}, status=500)
