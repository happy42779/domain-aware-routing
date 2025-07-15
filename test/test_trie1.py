import asyncio


class TrieNode:
    def __init__(self):
        self.children = {}
        self.rule = None


class DomainTrie:
    """
    Original DomainTrie class with COW capabilities added.
    This preserves your implementation while adding the COW mechanism.
    """

    def __init__(self, default_upstreams):
        self.root = TrieNode()
        self.default_upstreams = default_upstreams
        self.lock = asyncio.Lock()  # Only used for pointer swap in COW operations

    # Original lookup implementation - unchanged
    def lookup(self, domain):
        """Look up a domain in the trie."""
        parts = domain.split(".")[::-1]  # Reverse for trie traversal

        current = self.root
        matched_rule = None

        for part in parts:
            # Check for exact match at this level
            if part in current.children:
                current = current.children[part]
                if current.rule:
                    matched_rule = current.rule
            # Check for wildcard match
            elif "*" in current.children:
                current = current.children["*"]
                if current.rule:
                    matched_rule = current.rule
            else:
                # No match at this level
                break

        return matched_rule or {"type": "default", "upstreams": self.default_upstreams}

    # Original insert implementation - used for initial building
    def insert(self, domain, rule):
        """
        Insert a rule directly (non-COW version).
        This is your original implementation, used for initial trie building.
        """
        parts = domain.split(".")[::-1]

        current = self.root
        for part in parts:
            if part not in current.children:
                current.children[part] = TrieNode()
            current = current.children[part]

        current.rule = rule

    # New COW-based methods for dynamic updates
    async def cow_insert(self, domain, rule):
        """
        Insert a rule using COW mechanism for concurrent safety.
        Use this for dynamic updates to avoid blocking reads.
        """
        # Create a copy with the modification
        new_root = self._copy_and_modify(self.root, domain, rule)

        # Atomic swap with minimal locking
        async with self.lock:
            self.root = new_root

    async def cow_remove(self, domain):
        """
        Remove a rule using COW mechanism for concurrent safety.
        Use this for dynamic updates to avoid blocking reads.
        """
        # Check if domain exists first
        if not self._domain_exists(domain):
            return False

        # Create a copy with the domain rule removed
        new_root = self._copy_and_remove(self.root, domain)

        # Atomic swap with minimal locking
        async with self.lock:
            self.root = new_root

        return True

    # Helper methods for COW operations
    def _domain_exists(self, domain):
        """Check if a domain has a rule in the trie"""
        parts = domain.split(".")[::-1]

        current = self.root
        for part in parts:
            if part not in current.children:
                return False
            current = current.children[part]

        return current.rule is not None

    def _copy_and_modify(self, node, domain, rule):
        """Create a partial copy of the trie with the domain modified"""
        parts = domain.split(".")[::-1]
        return self._copy_and_modify_recursive(node, parts, 0, rule)

    def _copy_and_modify_recursive(self, node, parts, index, rule):
        """Recursively create a partial copy with the modification"""
        # Create a shallow copy of the current node
        new_node = TrieNode()
        new_node.children = node.children.copy()  # Shallow copy of children dict
        new_node.rule = node.rule  # Copy rule reference

        # If we've reached the end of the domain parts, set the rule
        if index == len(parts):
            new_node.rule = rule
            return new_node

        # Get the current part
        part = parts[index]

        # Create or copy the child for this part
        if part in new_node.children:
            # Copy this child and continue recursion
            new_node.children[part] = self._copy_and_modify_recursive(
                new_node.children[part], parts, index + 1, rule
            )
        else:
            # Create new path for remaining parts
            new_child = TrieNode()
            new_node.children[part] = new_child

            # If this is the last part, set the rule
            if index == len(parts) - 1:
                new_child.rule = rule
            else:
                # Continue building the path
                current = new_child
                for i in range(index + 1, len(parts)):
                    next_child = TrieNode()
                    current.children[parts[i]] = next_child
                    current = next_child

                    # Set rule at the end
                    if i == len(parts) - 1:
                        current.rule = rule

        return new_node

    def _copy_and_remove(self, node, domain):
        """Create a partial copy with the domain rule removed"""
        parts = domain.split(".")[::-1]
        return self._copy_and_remove_recursive(node, parts, 0)

    def _copy_and_remove_recursive(self, node, parts, index):
        """Recursively create a partial copy with the rule removed"""
        # Create a shallow copy of the current node
        new_node = TrieNode()
        new_node.children = node.children.copy()
        new_node.rule = node.rule

        # If we've reached the end, remove the rule
        if index == len(parts):
            new_node.rule = None
            return new_node

        part = parts[index]

        # Only continue if this part exists
        if part in new_node.children:
            # Copy this child and continue recursion
            new_node.children[part] = self._copy_and_remove_recursive(
                new_node.children[part], parts, index + 1
            )

            # If the child is now empty (no rule and no children), remove it
            child = new_node.children[part]
            if child.rule is None and not child.children:
                del new_node.children[part]

        return new_node

    # Keep your original pretty_print methods
    def pretty_print(self):
        """Print the trie structure for debugging"""
        self._pretty_print_recursive(self.root, 0, "")

    def _pretty_print_recursive(self, node, level, prefix):
        """Recursively print the trie structure"""
        indent = "  " * level
        if node.rule:
            rule_type = node.rule.get("type", "unknown")
            print(f"{indent}{prefix} [{rule_type}]")
        else:
            print(f"{indent}{prefix}")

        for part, child in sorted(node.children.items()):
            self._pretty_print_recursive(child, level + 1, part)


if __name__ == "__main__":
    # test()
    trie = DomainTrie(["1.1.1.1"])
    if not trie:
        print("Empty trie")
    trie.insert("google.com", {"action": "normal"})
    trie.insert("facebook.com", {"action": "block"})
    trie.insert("*.youtube.com", {"action": "allow"})
    trie.insert("*.google.com", {"action": "block"})
    trie.insert("mail.google.com", {"action": "route"})
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
