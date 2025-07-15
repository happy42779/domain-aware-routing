from typing import Dict, Any


class DomainTrie:
    def __init__(self):
        self.root = {}

    def insert(self, domain: str, rule: Dict) -> None:
        if not domain:
            raise ValueError("Domain is empty.")

        node = self.root
        labels = domain.split(".")[::-1]
        # if len(labels) < 3:
        #     raise ValueError("Domain is too short.")

        for label in labels:
            if not label:
                continue
            if label not in node:
                node[label] = {}
            node = node[label]

        node["__rule__"] = rule

    def lookup(self, domain: str) -> Dict[str, Any]:
        if not domain:
            raise ValueError("Domain is empty.")

        # lookup one part by one part
        trie = self.root
        rule = None
        is_exact_match = True
        labels = domain.split(".")[::-1]
        for label in labels:
            if not label:
                continue

            if label in trie:
                trie = trie[label]

            elif "*" in trie:
                rule = trie["*"]["__rule__"]
                is_exact_match = False

            # print(f"{label}: {rule} : {trie}\n")

        # print(f"depth is {depth}")
        if "__rule__" in trie and is_exact_match:
            rule = trie["__rule__"]

        return rule

    def pretty_print(self):
        import json

        print(json.dumps(self.root, indent=4))


if __name__ == "__main__":
    # test()
    trie = DomainTrie()
    if not trie:
        print("Empty trie")
    trie.insert("google.com", {"action": "normal"})
    trie.insert("facebook.com", {"action": "block"})
    trie.insert("*.youtube.com", {"action": "allow"})
    trie.insert("*.google.com", {"action": "block"})
    # trie.insert("mail.google.com", {"action": "route"})
    trie.insert("*.mail.google.com", {"action": "wild_three"})

    trie.pretty_print()

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

    # trie.cow_remove("mail.google.com")
    # print("\nresult after removing...:\n")
    #
    # trie.pretty_print()
    #
    # for d in test_domains:
    #     print(f"{d}: {trie.lookup(d)}")
