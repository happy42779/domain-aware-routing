from typing import Dict, Any, Optional, Tuple, Callable, Union, Awaitable
import copy
import asyncio
import logging


class TrieNode:
    def __init__(self) -> None:
        self.children: Dict = {}
        self.rule: Optional[Dict | Any] = None


OnUpdateCallback = Callable[[str, str, str, str, str], Union[Any, Awaitable]]


logger = logging.getLogger(__name__)


class DomainTrie:
    """
    Do not use the Node above, directly using a dict.
    Attributes will be used to mark certain nodes.
    __rule__: to store the rule for a domain
    """

    def __init__(self):
        self.root = TrieNode()
        self.lock = asyncio.Lock()
        self.update_cb = None

    def add_update_cb(self, update_cb: OnUpdateCallback) -> None:
        """
        This is a function exposed to other classes to register a callback function,
        when policy udpate happens
        """
        self.update_cb = update_cb

    def lookup(self, domain: str) -> Tuple[Dict[str, Any], Optional[TrieNode]]:
        if not domain:
            raise ValueError("Domain is empty.")

        # lookup one part by one part
        current = self.root
        matched_rule = None
        wildcard_rule = None
        exact_len = 0

        labels = domain.split(".")[::-1]

        depth = len(labels)

        for i, label in enumerate(labels):
            # Check for wildcard match
            if "*" in current.children:
                wildcard_rule = current.children["*"].rule

            # Check for exact match at this level
            if label in current.children:
                current = current.children[label]
                if current.rule:
                    matched_rule = current.rule  # Most specific exact match
                    exact_len = i + 1
            else:
                # No match at this level (neither exact nor wildcard)
                break

        # If we found a specific match, return it
        if matched_rule and depth == exact_len:
            return matched_rule, current

        # If we found wildcard matches, return the most specific one
        if wildcard_rule:
            return wildcard_rule, current

        return {}, current

    def insert(self, domain: str, rule: Dict):
        """
        For building from conf files
        """
        if not self.root:
            raise Exception("Root node is None")

        try:
            labels = domain.split(".")[::-1]
            cur = self.root

            # find the rule
            for label in labels:
                if label not in cur.children:
                    cur.children[label] = TrieNode()
                cur = cur.children[label]

            cur.rule = rule
        except Exception:
            raise

    async def cow_insert(self, domain: str, rule: Dict):
        """
        Insert a rule using COW mechanisum

        Return value: indicates if a cache consistency should be checked
        """

        # check if the domain:rule already present, then, it's should be
        # udpate instead of inserting by replacing
        existing_rule, node = self.lookup(domain)
        if existing_rule and node:
            await self._cow_update(existing_rule, rule, node)
            return

        new_root = copy.deepcopy(self.root)

        # modify
        labels = domain.split(".")[::-1]
        cur = new_root

        # find the rule
        for label in labels:
            if label not in cur.children:
                cur.children[label] = TrieNode()
            cur = cur.children[label]

        cur.rule = rule

        # swap
        async with self.lock:
            self.root = new_root

    async def cow_remove(self, domain: str, directive=None) -> bool:
        """
        Remove a rule using COW mechanism
        """
        if not self._domain_exits(domain):
            raise Exception(f"{domain} is not found in the trie")
            # return False

        new_root = copy.deepcopy(self.root)

        # interate
        labels = domain.split(".")[::-1]
        cur = new_root

        for label in labels:
            if label not in cur.children:
                return False
            cur = cur.children[label]

        if cur.rule is None:
            raise Exception("rule is not supposed to be None")

        # check what directive is specified to remove
        if directive is None:
            cur.rule = None
        # otherwise
        elif directive in cur.rule:
            del cur.rule[directive]
            # if rule is now empty except for domian and dbr, remove it entirely
            remaining_keys = set(cur.rule.keys()) - {"domain", "dbr"}
            if not remaining_keys:
                cur.rule = None
        else:
            return False

        # remove
        async with self.lock:
            self.root = new_root
        # self.root = new_root

        return True

    async def _cow_update(self, existing_rule: Dict, rule: Dict, node: TrieNode):
        """
        Deepcopy a rule, and then update it.
        """
        new_rule = copy.deepcopy(existing_rule)

        logger.debug(f"old rule: {existing_rule}, new rule: {rule}")

        try:
            # delete block if presetn, when new is route
            if "block" in existing_rule and "route" in rule:
                if self.update_cb:
                    domain = existing_rule["domain"]
                    old_action = "block"
                    new_action = "route"
                    new_value = rule["route"]
                    await self.update_cb(domain, old_action, new_action, "", new_value)
                del new_rule["block"]

            elif "route" in existing_rule and "block" in rule:
                if self.update_cb:
                    domain = existing_rule["domain"]
                    old_action = "route"
                    new_action = "block"
                    old_value = existing_rule["route"]
                    await self.update_cb(domain, old_action, new_action, old_value, "")
                del new_rule["route"]

            new_rule |= rule
            async with self.lock:
                node.rule = new_rule

        except Exception:
            raise

    def _domain_exits(self, domain: str) -> bool:
        """
        Check if a rule is in the trie
        """
        labels = domain.split(".")[::-1]

        cur = self.root
        for label in labels:
            if label not in cur.children:
                return False
            cur = cur.children[label]

        return cur.rule is not None

    def purge_trie(self):
        """
        Empty the whole trie, by assigning a new root
        """
        self.root = TrieNode()

    def all_rules_flat(self):
        """
        Returns a list of rules from the entire trie
        """

        def walk(node, labels, result):
            if node.rule is not None:
                result.append((".".join(reversed(labels)), node.rule))
            for label, child in node.children.items():
                walk(child, labels + [label], result)

        result = []
        walk(self.root, [], result)
        return result

    def pretty_print(self):
        """Print the trie structure for debugging"""
        print("Current Rule set: \n")
        self._pretty_print_recursive(self.root, 0, "")

    def _pretty_print_recursive(self, node, level, prefix):
        """Recursively print the trie structure"""
        indent = "  " * level
        if node.rule:
            # rule_type = node.rule.get("action", "N/A")
            print(f"{indent}{prefix}: {node.rule}")
        else:
            print(f"{indent}{prefix}")

        for part, child in sorted(node.children.items()):
            self._pretty_print_recursive(child, level + 1, part)


# def test():
#     labels = dns.name.from_text("*.google.com").labels
#
#     print(labels)
#
#     labels = dns.name.from_text("*.google.co.uk").labels
#
#     print(labels)
#
#     for l in reversed(labels[:-1]):
#         print(l)
#
#     n = parse_tld("www.google.co.uk", fix_protocol=True)
#     print(f"length: {len(n)}")
#     print(parse_tld("*.google.com", fix_protocol=True))
#     for i in n:
#         print(f"type of {i}: {type(i)}")


if __name__ == "__main__":
    # test()
    trie = DomainTrie()
    if not trie:
        print("Empty trie")
    trie.insert("google.com", {"action": "normal"})
    trie.insert("facebook.com", {"action": "block"})
    trie.insert("*.youtube.com", {"action": "allow"})
    trie.insert("*.google.com", {"action": "block"})
    trie.insert("mail.google.com", {"action": "route"})
    trie.insert("*.mail.google.com", {"action": "wild_three"})

    trie.pretty_print()

    # test dynamic insert
    loop = asyncio.get_event_loop()
    coro = trie.cow_insert("*.baidu.com", {"action": "block"})
    coro1 = trie.cow_insert("*.google.com", {"upstream": "1.1.1.1"})

    loop.run_until_complete(asyncio.gather(coro, coro1))

    test_domains = [
        "google.com",
        "facebook.com",
        "youtube.com",
        "play.google.com",
        "map.google.com",
        "mail.google.com",
        "test.mail.google.com",
    ]

    for d in test_domains:
        print(f"{d}: {trie.lookup(d)}")

    result = trie.all_rules_flat()
    [print(f"{r}\n") for r in result]

    # trie.cow_remove("mail.google.com")
    # print("\nresult after removing...:\n")
    #
    # trie.pretty_print()
    #
    # for d in test_domains:
    #     print(f"{d}: {trie.lookup(d)}")
