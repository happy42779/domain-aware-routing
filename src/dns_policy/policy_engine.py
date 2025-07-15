import sys
import asyncio
import logging
import pathlib
import dns.rdatatype
from typing import Dict, List
from config import ConfigManager
from forward import DNSForwarder
from nb_api_client import AsyncNBApiClient
from policy_service import PolicyService, PolicyRestHandler

# set the logging folder to be ../../log/
log_path = pathlib.Path(__file__).parent.parent.parent / "log"

log_file = log_path / "policy_engine.log"

# unix_sock_file = "/tmp/ryu.sock"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class PolicyEngine:
    def __init__(
        self,
        listen_addr: str = "127.0.0.1",
        listen_port: int = 5335,
        controller_url: str = "http://127.0.0.1:8080",
        policy_service_url: str = "http://0.0.0.0:8054",
    ):
        self.listen_addr = listen_addr
        self.listen_port = listen_port

        # asyncio lock
        # self.controller_lock = None
        self.controller_url = controller_url
        self.nb_api_client = None

        # policy services
        self.policy_service_url = policy_service_url
        self.policy_service = None
        self.policy_service_handler = None

    async def _setup_async(self):
        """
        Function to setup any initiation related to asyncio objects
        """
        # load configuration
        try:
            self.conf_manager = ConfigManager()
            self.conf_manager.parse_file()
            self.upstreams = self.conf_manager.get_default_upstreams()
            # self.trie = DomainTrie(self.upstreams)

            # configure forwarder
            self.forwarder = DNSForwarder(
                listen_addr=self.listen_addr,
                listen_port=self.listen_port,
                upstreams=self.upstreams,
            )

            # set the callback function when there's a rule policy
            self.forwarder.add_response_cb(self.__on_dns_policy)
            # set the callback to update conflict rules
            self.forwarder.domain_trie.add_update_cb(self.__on_rule_udpate)

            # load static dns records
            self.forwarder.add_static_cache(self.conf_manager.get_static_records())

            # build the domain trie
            self.forwarder.build_domain_trie(self.conf_manager.get_rules())

            # setup the restapi for dynamic
            self.policy_service = PolicyService(self.conf_manager, self.forwarder)
            self.policy_service_handler = PolicyRestHandler(self.policy_service)

            self.forwarder.domain_trie.pretty_print()

        except Exception as e:
            logger.error(f"Failed to start policy engine: {e}")
            sys.exit(1)

        logger.info("Policy engine started")

    async def __on_dns_policy(self, rule: Dict, ips: List[str]):
        """
        This is a callback function, and it will only be
        called externally. It will be called whenever there's
        a dns policy available.
        """

        result = None
        if self.nb_api_client is None:
            raise Exception("NB Api client is None")
        try:
            # ips are tuples of (ip,ttl)
            if "route" in rule:
                nexthop = rule["route"]
                result = await self.nb_api_client.route(nexthop, ips)
            elif "block" in rule:
                result = await self.nb_api_client.block(ips)

            logger.info(f"Received response from controller: {result}")
        except Exception as e:
            logger.error(f"Error sendding command to controller: {e}")

    async def __on_rule_udpate(
        self,
        domain: str,
        old_action: str,
        new_action: str,
        old_value: str,
        new_value: str,
    ):
        """
        Update the openflow and routes to achieve consistency between rule and forwarding plane
        """

        try:
            # check if ip is still valid, if there's no cache, it means that
            # the rule is not currently depolyed
            cached = self.forwarder.cache.get((domain, dns.rdatatype.A), None)
            if not cached or not self.nb_api_client:
                logger.debug("No cache found...")
                return

            # extract ip
            resp = dns.message.from_wire(cached[0].to_wire())
            ips = self.forwarder._extract_A_records(resp)

            result = None
            if "block" == old_action and "route" == new_action:
                logger.debug(
                    f"old_rule: {old_action, old_value}, new_rule: {new_action, new_value}"
                )
                # delete openflow drop
                result = await self.nb_api_client.route(nexthop=new_value, ips=ips)

            elif "route" in old_action and "block" in new_action:
                logger.debug(
                    f"old_rule: {old_action, old_value}, new_rule: {new_action, new_value}"
                )
                # delete routes(removal of openflow should trigger the update of routes)
                # update the openflow
                commands = [
                    {"ips": ips, "action": "block", "type": "flow"},
                    {"ips": ips, "action": "remove", "type": "route"},
                ]
                result = await self.nb_api_client.batch(commands=commands)

            if result:
                logger.debug(f"Rule update result: {result}")
        except Exception as e:
            logger.debug("failed to update rules to keep consistency")

    async def _start_dns_forwarder(self):
        """
        Call the coroutine from forwarder to start the listening of udp datagram
        """
        try:
            await self.forwarder.start()
            # run forever
            await asyncio.sleep(float("inf"))
        except Exception as e:
            logger.error(f"Error starting forwarder: {e}")
            raise

    async def _start_dynamic_rest_policy_server(self):
        """
        Start the async rest api server for dynamic policy changing
        """
        if self.policy_service_handler is None:
            raise Exception("Policy service handler is not initialized")

        try:
            await self.policy_service_handler.start()

        except Exception as e:
            logger.error(f"Error staring policy server: {e}")

        pass

    async def _start_nb_api_client(self):
        """
        Start the async NB REST Api client
        """
        if self.controller_url is None:
            raise Exception(f"Invalid url specified: {self.controller_url}")
        try:
            self.nb_api_client = await AsyncNBApiClient(
                self.controller_url
            ).__aenter__()
        except Exception as e:
            logger.error(f"Error starting NB Api client: {e}")
            raise

    async def start_engine(self):
        await self._setup_async()

        forwarder = asyncio.create_task(self._start_dns_forwarder())
        api_client = asyncio.create_task(self._start_nb_api_client())
        rest_policy_server = asyncio.create_task(
            self._start_dynamic_rest_policy_server()
        )

        try:
            await asyncio.gather(forwarder, api_client, rest_policy_server)
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            raise
        except FileNotFoundError:
            pass
        except ConnectionRefusedError:
            pass
        finally:
            await self.forwarder.stop()


def main(args):
    policy_engine = PolicyEngine(args.listen, args.port)

    try:
        asyncio.run(policy_engine.start_engine())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Error in policy engine: {repr(e)}")
    finally:
        logger.info("Policy engine stopped")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DNS Policy Engine")
    parser.add_argument("--listen", default="127.0.0.1", help="Listen address")
    parser.add_argument("--port", default=5335, help="Listen port")

    args = parser.parse_args()

    main(args)
