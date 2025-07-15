import dns.message
import dns.rcode
import dns.asyncquery
import dns.rdatatype
import dns.rrset
import logging
import asyncio
from cachetools import TLRUCache

from typing import (
    Any,
    Awaitable,
    Dict,
    List,
    Optional,
    Tuple,
    Callable,
    Union,
)

# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from trie import DomainTrie

logger = logging.getLogger(__name__)


""" 
As of 6.0.0b4 cachetools provides a ttlcache that support custom time calculation, called 
TLRUCache    
"""
# class AsyncTLRUCache:
#     def __init__(self, maxsize):
#         self.cache = TLRUCache(maxsize, self._ttl_func)
#         self.lock = asyncio.Lock()
#
#     async def get(self, key):
#         async with self.lock:
#             return self.cache.get(key)
#
#     async def set(self, key, value, ttl):
#         async with self.lock:
#             self.cache[key] = (value, ttl)
#
#     def _ttl_func(self, _key, value, now):
#         # value is a Tuple(value, ttu)
#         return now + value[1]


# class AyncTTLCache:
#     ''' this is a per-key ttlcache impelentation to serve as a cname cache'''
#     def __init__(self, max_size =10000, loop = None):
#         self.cache = {}
#         self.lock = asyncio.Lock()
#         self.loop = loop or asyncio.get_event_loop()
#         self.max_size = max_size
#
#     async def get(self, cname: str):
#         ''' Check if a cname is already checked before '''
#         async with self.lock:
#             entry = self.cache.get(cname)
#             # not found
#             if not entry:
#                 return None
#
#             # check ttl
#             if self.loop.time() > entry['expires_at']:
#                 del self.cache[cname]
#                 return None
#
#             # return the valid cached cname
#             return entry['value']
#
#     async   def set(self, key:str, value, ttl:int):
#         ''' Add a cname record to the the cname cache with a ttl '''
#         async with self.lock:
#
#             expires_at =self.loop.time() + ttl
#
#             self.cache[key]={
#                 'value': value,
#                 'expires_at': expires_at
#             }
#
#             # set the deletion for after ttl expires
#             self.loop.call_later(ttl, self._delete_expired, key, expires_at)
#
#
#     def _delete_expired(self, key, expected_expiry):
#         ''' Remove expired entries '''
#         async def _delete():
#             async with self.lock:
#                 entry = self.cache.get(key)
#                 if entry and entry['expires_at']== expected_expiry:
#                     del self.cache[key]
#
#             # schedule eviction tasks
#             asyncio.create_task(_delete())


# The following definition is a type alias for callback functions,
# defined within the class
OnResponseCallback = Callable[[Dict[str, str], List[str]], Union[Any, Awaitable]]


class DNSForwarder:
    """
    An async DNS forwarder, loads predefined rules, accepts requests from other devices,
    and then forward the request to the upstream server(s), upstreams can also be
    specified with rules.
    """

    def __init__(
        self,
        listen_addr: str,
        listen_port: int,
        upstreams: List[str],
        cache_size: int = 10000,
        cache_ttl: int = 900,
        timeout: float = 3.0,
    ) -> None:
        # Initialization for a dns forwarder
        self.listen_addr = listen_addr
        self.listen_port = listen_port
        self.upstreams = upstreams
        self.cache_size = cache_size
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.response_cb: Optional[OnResponseCallback] = None
        self.MAX_DNS_TTL = 2_147_483_647

        # transport handles
        self.udp_transport = None

        try:
            # Initialize cache
            # domain/ip cache
            self.cache = TLRUCache(maxsize=cache_size, ttu=self._my_ttu)
            ### NOTE: cache should include static routes immediately, with max ttl
            self.block_cache: Dict = {}

            # cname cache
            # self.cname_cache = TLRUCache(maxsize=5000, ttu=self._my_ttu)

            # DomainTrie instance, used for rule searching
            self.domain_trie = DomainTrie()
        except Exception as e:
            logger.error(f"Error occurred during initialization: {e}")
            # sys.exit(1)
            raise  # pass to the callee

        logger.info(
            f"Async DNS Forwarder initialzed, using upstreams: {self.upstreams}"
        )

    def _my_ttu(self, _key, value, now):
        # value is a Tuple(value, ttu)
        return now + value[1]

    async def handle_request(
        self,
        data: bytes,
        client_addr: Tuple[str, int],
        transport: asyncio.DatagramTransport,
    ) -> None:
        """address and port are represented in Tuple[str, int]"""
        try:
            # parse query
            query = dns.message.from_wire(data)
            query_id = query.id
            qname = query.question[0].name.to_text()
            if qname.endswith("."):
                qname = qname[:-1]
            qtype = query.question[0].rdtype
            # qclass = query.question[0].rdclass

            logger.info(f"Received query for {qname}")

            # check domain trie for rule
            rule, _ = self.domain_trie.lookup(qname)

            # check block cache
            # if qname in self.block_cache:
            #     logger.info(f"Received block cache hit for {qname}")
            #     # return empty response
            #     nresp = self.make_NXDOMAIN_response(query)
            #     transport.sendto(empty_resp.to_wire(), client_addr)
            #     return

            # check if v6, currently ignore v6
            if qtype == dns.rdatatype.AAAA:
                logger.info(f"Received AAAA type query for {qname}, ignoring")
                empty_resp = dns.message.make_response(query)
                transport.sendto(empty_resp.to_wire(), client_addr)
                return

            resp = None

            # check cache and reply to client
            # cached are statics, block and normal ones
            cached_resp = self.cache.get((qname, qtype))
            if cached_resp:  # return te cached resp
                logger.info(f"Cache hit for {qname} with cache: {cached_resp}")
                # cached is a tuple (resp, ttl)
                resp = dns.message.from_wire(cached_resp[0].to_wire())
                resp.id = query_id
                if "block" not in rule:
                    transport.sendto(resp.to_wire(), client_addr)
                    return

            # check if rule is block, and it's not cached or cached ttl is expired
            if "block" in rule:
                # return NXDOMAIN immediately, and then resolve the ip,
                # and block the resolved ip
                nx_resp = self.make_NXDOMAIN_response(query)
                transport.sendto(nx_resp.to_wire(), client_addr)

            # value of this key is a list of upstream(s)
            upstream = rule.get("upstream", self.upstreams)

            # DEBUG: check rule
            logger.debug(f"Rule for {qname}: {rule}")

            logger.info(f"Querying {qname} from {upstream}")
            # forward to upstream
            resp = await self._forward_query(query, upstream)

            # cache response
            self._add_cache(qname, qtype, resp)

            # forward if there's rule associated with domain
            if "dbr" in rule:
                # extract ip
                ips = self._extract_A_records(resp)
                # forward
                logger.debug(f"sending {rule} to policy engine")
                # TODO: TTL for block rule? How does it do?
                if self.response_cb:
                    await self.response_cb(rule, ips)
                else:
                    raise Exception("No policy engine registered")

            # send response back to client
            if "block" not in rule:
                transport.sendto(resp.to_wire(), client_addr)
        except Exception as e:
            logger.error(f"Error handling request: {str(e)}")
            raise

    def _extract_A_records(self, resp: dns.message.Message) -> List[str]:
        """
        Extract all A records from a dns response message, together with ttls
        """
        ips = [
            rr.address
            for rrset in resp.answer
            if rrset.rdtype == dns.rdatatype.A
            for rr in rrset
        ]
        logger.debug(f"Extracted A records from response: {ips}")
        return ips

    def _extract_A_records_with_ttl(self, resp: dns.message.Message) -> List[Tuple]:
        """
        Extract all A records from a dns response message, together with ttls
        """
        ips = [
            (rr.address, rrset.ttl)
            for rrset in resp.answer
            if rrset.rdtype == dns.rdatatype.A
            for rr in rrset
        ]
        logger.debug(f"Extracted A records from response: {ips}")
        return ips

    def _add_cache(
        self, qname: str, qtype: int, response: dns.message.Message, ttl: int = -1
    ):
        """Add dns response to cache"""
        # check response
        if response.rcode() != dns.rcode.NOERROR:
            return

        if -1 == ttl:
            ttl = self.cache_ttl
            # ip = None
            if response.answer:
                for rrset in response.answer:
                    if rrset.rdtype == dns.rdatatype.A:
                        # ip = rrset[0].address
                        if rrset.ttl > ttl:
                            # use the shorter ttl
                            ttl = rrset.ttl

        # add cache
        self.cache[(qname, qtype)] = (response, ttl)
        # logger.debug(f"Cached {qname}: {response}")

    def purge_cache(self):
        """
        Iterate through the cache, purge any that is not static cache
        """
        for key, val in self.cache.items():
            if val[1] != self.MAX_DNS_TTL:
                del self.cache[key]

    async def _forward_query(
        self, query: dns.message.Message, upstreams: List[str]
    ) -> dns.message.Message:
        for upstream in upstreams:
            try:
                # return value is a tuple, (dns.message, bool)
                return await dns.asyncquery.udp(query, upstream, timeout=self.timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout from upstream {upstream}, will try next one")
                continue
            except Exception as e:
                logger.error(f"Error forwarding to {upstream}: {str(e)}")
                continue
        # if program gets here, meaning that all upstream failed
        logger.error("All upstreams failed")

        # making a response for client
        response = dns.message.make_response(query)
        response.set_rcode(dns.rcode.SERVFAIL)
        return response

    def make_NXDOMAIN_response(self, query: dns.message.Message) -> dns.message.Message:
        """
        Make NXDOMAIN response for those are blocked
        """
        resp = dns.message.make_response(query)
        resp.set_rcode(dns.rcode.NXDOMAIN)
        return resp

    ######################### function to be called externally ###############
    def add_static_cache(self, statics: List[Dict]):
        """
        This function loads all statics ips into the cache, make response for these records
        """

        try:
            for static in statics:
                # need to make a response for these records
                domain = static.get("domain")
                if not domain:
                    raise ValueError

                query = dns.message.make_query(domain, dns.rdatatype.A)
                resp = dns.message.make_response(query)
                # create rrset, only do A type
                rrset = dns.rrset.from_text(
                    domain + ".", 3600, "IN", "A", static["address"]
                )
                resp.answer.append(rrset)
                self._add_cache(domain, dns.rdatatype.A, resp, self.MAX_DNS_TTL)

                logger.debug(f"Static cache: {static}")
        except Exception as e:
            # TODO: what to catch here?
            logger.error(f"Error adding statics: {repr(e)}")

    def build_domain_trie(self, rules: List[Dict]):
        """
        Populate the domian trie with rules
        """
        try:
            for rule in rules:
                self.domain_trie.insert(rule["domain"], rule)
        except Exception:
            raise

    def add_response_cb(self, response_cb: OnResponseCallback) -> None:
        """
        This is a function exposed to other classes to register a callback function
        """
        self.response_cb = response_cb

    class UDPProtocol(asyncio.DatagramProtocol):
        """The protocol factory for create_datagram_endpoint"""

        def __init__(self, server):
            self.server = server

        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            """this is a call back function for udp server"""
            # data is a bytes object
            # addr is a tuple
            # create a task to handle requests
            asyncio.create_task(self.server.handle_request(data, addr, self.transport))

    async def start_udp_server(self):
        """start the udp server at :53"""
        loop = asyncio.get_running_loop()

        # create a udp server
        transport, _ = await loop.create_datagram_endpoint(
            lambda: self.UDPProtocol(self),
            local_addr=(self.listen_addr, self.listen_port),
        )

        self.udp_transport = transport
        logger.info(
            f"Async DNS Forwarder listening on {self.listen_addr}: {self.listen_port}/udp"
        )

    async def start(self):
        """Run the dns forwarder listening at :53"""
        self.running = True

        # call start_udp_server
        await self.start_udp_server()

    async def stop(self):
        """Stops the udp server listening for dns requests"""
        logger.info("Stopping Async DNS Forwarder")
        self.running = False

        if self.udp_transport:
            self.udp_transport.close()

        logger.info("Async DNS Forwarder stopped")


async def main():
    forwarder = DNSForwarder(
        listen_addr="127.0.0.1",
        listen_port=5335,
        upstreams=["223.5.5.5", "119.29.29.29"],
    )

    try:
        await forwarder.start()
        # run forever
        await asyncio.sleep(float("inf"))
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        await forwarder.stop()


def test():
    qeury = dns.message.make_query("www.baidu.com", rdtype="A")
    response = dns.query.udp(qeury, "223.5.5.5", timeout=3.0)

    # Check for CNAME records in the answer section
    has_cname = False
    if response.answer:
        for rrset in response.answer:
            print(f"\nRecord set: {rrset.name}")
            print(f"TTL: {rrset.ttl}")
            print(f"Record type: {dns.rdatatype.to_text(rrset.rdtype)}")

            if rrset.rdtype == dns.rdatatype.CNAME:
                has_cname = True
                print("This is a CNAME record pointing to:")
                for rr in rrset:
                    print(f"  → {rr.target}")
            else:
                print("Records:")
                for rr in rrset:
                    if rrset.rdtype == dns.rdatatype.A:
                        print(f"  IP: {rr.address}")
                    else:
                        print(f"  {rr}")
    else:
        print("No answer records in response")

    print(
        f"\nSummary: This domain {'has' if has_cname else 'does not have'} a CNAME record in the response."
    )

    return has_cname, response


if __name__ == "__main__":
    asyncio.run(main())
    # test()
