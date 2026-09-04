from __future__ import annotations
import hashlib
import time
from typing import List, Optional, Tuple
import zlib


# Base class for anything persisted under .git/objects. Blobs, trees, and
# commits all share the same hashing, serialization, and deserialization logic.
class RepoObject:
    def __init__(self, obj_type: str, content: bytes):
        self.type = obj_type
        self.content = content

    def hash(self) -> str:
        # Identifies the object by content: identical content always produces
        # the same hash. Header layout: <type> <size>\0<content>
        header = f"{self.type} {len(self.content)}\0".encode()
        return hashlib.sha1(header + self.content).hexdigest()

    def serialize(self) -> bytes:
        # Produces the compressed representation written to disk.
        header = f"{self.type} {len(self.content)}\0".encode()
        return zlib.compress(header + self.content)

    @classmethod
    def deserialize(cls, data: bytes) -> RepoObject:
        # Reverses serialize(): decompresses the data, then separates the
        # header from the content.
        decompressed = zlib.decompress(data)
        null_idx = decompressed.find(b"\0")
        header = decompressed[:null_idx].decode()
        content = decompressed[null_idx + 1 :]

        obj_type, _ = header.split(" ")

        return cls(obj_type, content)


# A blob represents a single file's raw contents.
class Blob(RepoObject):
    def __init__(self, content: bytes):
        super().__init__("blob", content)


# A tree represents a directory listing: a set of (mode, name, hash) entries,
# where each entry references either a blob (a file) or another tree (a subdirectory).
class Tree(RepoObject):
    def __init__(self, entries: Optional[List[Tuple[str, str, str]]] = None):
        self.entries = entries or []
        content = self._serialize_entries()
        super().__init__("tree", content)

    def _serialize_entries(self) -> bytes:
        # entry format: 100644 <name>\0<hash>, repeated for each entry
        content = b""
        for mode, name, obj_hash in sorted(self.entries):
            content += f"{mode} {name}\0".encode()
            content += bytes.fromhex(obj_hash)

        return content

    def add_entry(self, mode: str, name: str, obj_hash: str):
        # Appends one entry and regenerates the tree's serialized content.
        self.entries.append((mode, name, obj_hash))
        self.content = self._serialize_entries()

    @classmethod
    def from_content(cls, content: bytes) -> Tree:
        # Parses the raw bytes back into a list of entries. Each entry
        # consists of a "mode name\0" prefix followed by a 20-byte hash.
        tree = cls()
        i = 0

        while i < len(content):
            null_idx = content.find(b"\0", i)
            if null_idx == -1:
                break

            mode_name = content[i:null_idx].decode()
            mode, name = mode_name.split(" ", 1)
            obj_hash = content[null_idx + 1 : null_idx + 21].hex()
            tree.entries.append((mode, name, obj_hash))

            # move past this entry's 20-byte hash to reach the next entry.
            i = null_idx + 21

        return tree


# A commit references a single tree (a complete snapshot) along with its
# parent commit(s); traversing parent_hashes backwards is how "log" reconstructs history.
class Commit(RepoObject):
    def __init__(
        self,
        tree_hash: str,
        parent_hashes: List[str],
        author: str,
        committer: str,
        message: str,
        timestamp: Optional[int] = None,
    ):
        self.tree_hash = tree_hash
        self.parent_hashes = parent_hashes
        self.author = author
        self.committer = committer
        self.message = message
        self.timestamp = timestamp or int(time.time())

        content = self._serialize_commit()
        super().__init__("commit", content)

    def _serialize_commit(self):
        # Builds the plain-text commit body, one field per line, with a
        # blank line separating the metadata from the commit message.
        lines = [f"tree {self.tree_hash}"]
        for parent in self.parent_hashes:
            lines.append(f"parent {parent}")

        lines.append(f"author {self.author} {self.timestamp} +0000")
        lines.append(f"committer {self.committer} {self.timestamp} +0000")
        lines.append("")
        lines.append(self.message)

        return "\n".join(lines).encode()

    @classmethod
    def from_content(cls, content: bytes) -> Commit:
        # Reverses _serialize_commit: reads each line back into its
        # corresponding field until the blank line preceding the message is reached.
        lines = content.decode().split("\n")
        tree_hash = None
        parent_hashes = []
        author = None
        committer = None
        message_start = 0

        for i, line in enumerate(lines):
            if line.startswith("tree "):
                tree_hash = line[5:]
            elif line.startswith("parent "):
                parent_hashes.append(line[7:])
            elif line.startswith("author "):
                author_parts = line[7:].rsplit(" ", 2)
                author = author_parts[0]
                timestamp = int(author_parts[1])
            elif line.startswith("committer "):
                committer_parts = line[10:].rsplit(" ", 2)
                committer = committer_parts[0]
            elif line == "":
                message_start = i + 1
                break

        message = "\n".join(lines[message_start:])

        # A well-formed commit object always has these fields; if any are
        # missing, the content is corrupt and shouldn't be treated as a commit.
        if tree_hash is None or author is None or committer is None:
            raise ValueError("Malformed commit content: missing tree, author, or committer")

        commit = cls(tree_hash, parent_hashes, author, committer, message, timestamp)
        return commit
