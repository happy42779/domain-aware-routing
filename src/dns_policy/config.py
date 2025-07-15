from pathlib import Path
import pathlib
from typing import Any, Dict, List, Tuple
import ipaddress


class ConfigManager:
    """
    A conf file would look like as follow:

        listen-address = 127.0.0.1
        listen-port = 53

        server=8.8.8.8
        server=1.1.1.1

        server=/google.com/1.1.1.3
        server=/*.google.com/9.9.9.9, 8.8.8.8

        address=/router.my/192.168.1.1

        block=/facebook.com/
        block=/*.baidu.com/

        route=/apple.com/10.0.0.1
    """

    def __init__(self, base_dir: str = "conf/") -> None:
        self.base_dir = pathlib.Path(__file__).parent.parent.parent / base_dir
        # configs needed to read from config file, and keep
        # different components will need different information from here
        self.config = {
            "listen_address": "127.0.0.1",  # default listen port
            "listen_port": 53,  # default port used for DNS forwarder
            "cache-size": 1000,  # default number of cache entries
            "default_upstreams": [],  # default upstream server(s)
            "rules": [],
        }
        self.server_rule = []
        self.static_rule = []
        self.block_rule = []
        self.route_rule = []

        # define valid prefixes in the config file
        # and the functions to parse the line for each prefix
        self.valid_prefixes = {
            "listen-address": self._parse_listen_address_line,
            "listen-port": self._parse_listen_port_line,
            "cache-size": self._parse_cache_size_line,
            "server": self._batch_server_line,
            "address": self._batch_address_line,
            "block": self._batch_block_line,
            "route": self._batch_route_line,
        }

    def parse_file(self, file_path: str = "") -> Dict[str, Any]:
        """A wrapper function to facilitate tests"""
        confs = []
        if not file_path:
            # get all files in the base folder
            conf_path = Path(self.base_dir)
            confs = [f for f in conf_path.iterdir() if f.is_file()]
        else:
            confs.append(file_path)
        # check if empty
        if not confs:
            raise FileNotFoundError(f"No config file found in {self.base_dir}")

        self._parse_file(confs)
        self._merge_rules()
        return self.config

    def get_default_upstreams(self) -> List[str]:
        """
        This is the default upstreams used for domains that are
        not specified
        """
        return self.config["default_upstreams"]

    def get_port(self) -> int:
        """
        return the port that is specified for dns requests
        """
        return self.config["listen_port"]

    def get_rules(self) -> List[Dict]:
        """
        return the list of rules to build the domain trie for lookup
        this will merge differnet lines with the same domain when calling trie.insert().
        """
        return self.config["rules"]

    def get_static_records(self) -> List[Dict]:
        """
        Returns all the static dns records, they should be cached when forwarder starts.
        """
        return self.static_rule

    def _parse_file(self, confs: List[Path]) -> Dict[str, Any]:
        """
        Take any file in base folder as config file.
        Read all lines first. However, only store ones that doesnot start with "#"
        """
        # create lists to store lines for each prefix
        # batches: Dict[str, List[str]] = {prefix: [] for prefix in self.valid_prefixes}
        batches = {prefix: [] for prefix in self.valid_prefixes}
        errors = []  # record all the syntax errors found

        line_num = 0  # keep line number to track error
        for conf in confs:
            with open(conf, "r") as f:
                for line in f:
                    line_num += 1
                    line = line.strip()

                    # skip comments
                    if line.startswith("#") or (not line):
                        continue
                    # extract directive and then save each line
                    equals_pos = line.find("=")
                    if equals_pos == -1:
                        errors.append(
                            (line_num, line, "Missing '=' in configuration line")
                        )
                        continue

                    directive = line[:equals_pos]
                    value = line[equals_pos + 1 :].strip()

                    # check if directive is valid
                    if directive in self.valid_prefixes:
                        batches[directive].append((line_num, value))
                    else:
                        errors.append(
                            (line_num, line, f"Unknown directive: {directive}")
                        )

        if errors:
            error_message = [
                f"Line {line_num}: {line} - {msg}" for line_num, line, msg in errors
            ]
            raise ValueError("Configuration errors found\n" + "\n".join(error_message))

        # now, parse and verify with each spective directive
        for prefix, handler in self.valid_prefixes.items():
            if batches[prefix]:
                handler(batches[prefix])

        return self.config

    def _parse_listen_address_line(self, line: List[Tuple[int, str]]):
        """check validity of listen address"""
        # get line number, and value
        line_num, value = line[0]

        # treat the value as an ip address
        try:
            ipaddress.ip_address(value)  # only validate here
            self.config["listen_address"] = value
        except ValueError:
            raise ValueError(
                f"Line {line_num}: Invalid IP address in listen-address: {value}"
            )

    def _parse_listen_port_line(self, line: List[Tuple[int, str]]):
        """check validity of listen port"""
        line_num, value = line[0]

        try:
            port = int(value)
        except ValueError:
            raise ValueError(f"Line {line_num}: Invalid port number: {value}")

        if 1 <= port <= 65535:
            self.config["listen_port"] = port
        else:
            raise ValueError(
                f":Line {line_num}: Port must be between 1 and 65535: {value}"
            )

    def _parse_cache_size_line(self, line: List[Tuple[int, str]]):
        """
        Parse the cache size setting. Maxsize is 65536, but
        coule be larger.
        eg:
            cache_size=10000
        """
        line_num, value = line[0]

        try:
            cache_size = int(value)
        except ValueError:
            raise ValueError(f"Line {line_num}: Invalid cache size: {value}")

        if -1 <= cache_size <= 65535:
            self.config["cache_size"] = cache_size
        else:
            raise ValueError(
                f":Line {line_num}: Cache size must be between 0 and 65535: {value}"
            )

    def _batch_server_line(self, line: List[Tuple[int, str]]):
        """
        check validity of server address.
        There are two situations:
            a. server=8.8.8.8
            b. server=/google.com/1.1.1.3
        """

        for line_num, value in line:
            # if the value is a valid ip address, then it is a server
            if not value.startswith("/"):
                ip = value.strip()
                try:
                    ipaddress.ip_address(ip)
                    self.config["default_upstreams"].append(ip)
                except ValueError as e:
                    raise ValueError(f"Line {line_num}: Invalid IP address:  {e}.")
            else:
                # check if the value is valid
                self._parse_domain_server(value)

    def _batch_address_line(self, line: List[Tuple[int, str]]):
        """
        Batch proceesing the address line, that returns static ips
        """
        for line_num, value in line:
            try:
                self._parse_address_line(value)
            except ValueError as e:
                raise ValueError(f"Line {line_num}, Invalid address directive:  {e}.")

    def _parse_address_line(self, value: str):
        second_slash = value.find("/", 1)
        if second_slash == -1:
            raise ValueError("Missing '/'.")

        domain = value[1:second_slash].strip()
        ip = value[second_slash + 1 :].strip()
        if not domain:
            raise ValueError("Empty domain in address directive.")

        if not ip:
            raise ValueError("Empty ip in address directive.")

        try:
            ipaddress.ip_address(ip)
            rule = {"domain": domain, "address": ip}
            self.static_rule.append(rule)
        except ValueError as e:
            raise ValueError(f"Invalid static ip address: {e}.")

    def _batch_block_line(self, line: List[Tuple[int, str]]):
        """
        Batching parsing block lines
        """
        for line_num, value in line:
            try:
                self._parse_block_line(value)
            except ValueError as e:
                raise ValueError(f"Line {line_num}, Invalid block:  {e}.")

    def _parse_block_line(self, value: str):
        """
        Parse each block line
        """
        second_slash = value.find("/", 1)
        if second_slash == -1:
            raise ValueError("Missing '/'.")

        domain = value[1:second_slash].strip()
        if not domain:
            raise ValueError("Empty domain in block directive.")

        rule = {"domain": domain, "block": "", "dbr": True}
        self.block_rule.append(rule)
        # self._add_or_replace(domain, rule)

    def _batch_route_line(self, line: List[Tuple[int, str]]):
        """
        Batch processing route line
        """
        for line_num, value in line:
            try:
                self._parse_route_line(line_num, value)
            except ValueError as e:
                raise ValueError(f"Line {line_num}, Invalid route:  {e}.")

    def _parse_route_line(self, line_num: int, value: str):
        second_slash = value.find("/", 1)
        if second_slash == -1:
            raise ValueError(f"Wrong format, missing '/' in line {line_num}.")

        domain = value[1:second_slash].strip()
        gw = value[second_slash + 1 :].strip()
        if not domain:
            raise ValueError("Empty domain in route directive.")
        if not gw:
            raise ValueError("Empty gateway in route directive.")

        try:
            ipaddress.ip_address(gw)
            rule = {"domain": domain, "route": gw, "dbr": True}
            self.route_rule.append(rule)
            # self._add_or_replace(domain, rule)
        except ValueError:
            raise ValueError(f"Invalid gateway in route directive: {gw}.")

    def _parse_domain_server(self, value: str):
        second_slash = value.find("/", 1)
        if second_slash == -1:
            raise ValueError("Empty domain in server directive.")

        domain = value[1:second_slash].strip()
        # upstream specified
        upstream = value[second_slash + 1 :].strip()
        if not domain:
            raise ValueError("Empty domain in server directive.")
        if not upstream:
            raise ValueError("Empty upstream in server directive.")

        try:
            ipaddress.ip_address(upstream)
            # NOTE: using list to store specified upstream, to support multiple
            # upstresm in the future
            rule = {"domain": domain, "upstream": [upstream]}
            self.server_rule.append(rule)
            # self._add_or_replace(domain, rule)
        except ValueError:
            raise ValueError(f"Invalid upstream in server directive: {upstream}.")

    def _merge_rules(self):
        """
        Consider setting upstream server and route policy might be different lines, this
        function merges the rules
        """
        all_lists = (
            self.server_rule + self.static_rule + self.block_rule + self.route_rule
        )

        for rule in all_lists:
            index = -1
            for i, existing in enumerate(self.config["rules"]):
                if rule["domain"] == existing["domain"]:
                    index = i
                    break
            if index >= 0:
                self.config["rules"][index] |= rule
            else:
                self.config["rules"].append(rule)

        """
        The rules will look like:
            
        """


def test():
    sample_config = """
        # Sample configuration
        listen-address=192.168.1.5
        listen-port=5353
        
        # Default upstream servers
        server=8.8.8.8
        server=1.1.1.1
        
        # Domain-specific servers
        server=/google.com/1.1.1.3
        server=/*.google.com/9.9.9.9
        server=/facebook.com/1.1.1.3
        
        # Local DNS entries
        address=/router.my/192.168.1.1
        
        # Blocked domains
        block=/facebook.com/
        block=/*.baidu.com/
        
        # Routing
        route=/apple.com/10.0.0.1
        """

    import tempfile
    import json

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    with open(temp_file.name, "w") as f:
        f.write(sample_config)

    conf = ConfigManager("../../conf/")
    conf.parse_file(temp_file.name)
    print(f"conf: \n{json.dumps(conf.config)}")
    print(f"server: \n{json.dumps(conf.server_rule)}")
    print(f"static: \n{json.dumps(conf.static_rule)}")
    print(f"block: \n{json.dumps(conf.block_rule)}")
    print(f"route: \n{json.dumps(conf.route_rule)}")
    print(f"conf: \n{json.dumps(conf.config)}")


if __name__ == "__main__":
    test()
