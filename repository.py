from __future__ import annotations
import json
from pathlib import Path
import time
from typing import Any, Dict, List

from objects import Blob, Commit, RepoObject, Tree


class Repository:
    def __init__(self, path="."):
        self.path = Path(path).resolve()
        self.git_dir = self.path / ".git"

        # directory where blobs, trees, and commits are stored
        self.objects_dir = self.git_dir / "objects"

        # branch pointer files
        self.ref_dir = self.git_dir / "refs"
        self.heads_dir = self.ref_dir / "heads"

        # file that references the currently checked-out branch
        self.head_file = self.git_dir / "HEAD"

        # file backing the staging area
        self.index_file = self.git_dir / "index"

    def init(self) -> bool:
        if self.git_dir.exists():
            return False

        # create the required directory structure
        self.git_dir.mkdir()
        self.objects_dir.mkdir()
        self.ref_dir.mkdir()
        self.heads_dir.mkdir()

        # point HEAD at the master branch by default
        self.head_file.write_text("ref: refs/heads/master\n")

        # initialize the staging area as empty
        self.write_index({})

        print(f"Initialized empty Git repository in {self.git_dir}")

        return True

    def save_object(self, obj: RepoObject) -> str:
        # Objects are stored at objects/<first 2 hash chars>/<remaining hash chars>;
        # splitting into subdirectories avoids placing every object in one folder.
        obj_hash = obj.hash()
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]

        # Skip the write if the object already exists, since identical content
        # always produces the same hash.
        if not obj_file.exists():
            obj_dir.mkdir(exist_ok=True)
            obj_file.write_bytes(obj.serialize())

        return obj_hash

    def read_index(self) -> Dict[str, str]:
        # The index is a JSON file mapping each staged path to its blob hash.
        if not self.index_file.exists():
            return {}

        try:
            return json.loads(self.index_file.read_text())
        except Exception:
            return {}

    def write_index(self, index: Dict[str, str]):
        self.index_file.write_text(json.dumps(index, indent=2))

    def stage_file(self, path: str):
        full_path = self.path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Path {path} not found")

        # Read the file contents, wrap them in a blob, and persist the blob.
        content = full_path.read_bytes()
        blob = Blob(content)
        blob_hash = self.save_object(blob)

        # Record the blob hash in the index so commit() can reference it later.
        index = self.read_index()
        index[path] = blob_hash
        self.write_index(index)

        print(f"Added {path}")

    def stage_directory(self, path: str):
        full_path = self.path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Directory {path} not found")
        if not full_path.is_dir():
            raise ValueError(f"{path} is not a directory")

        index = self.read_index()
        added_count = 0

        # Recursively stage every file found under this directory.
        for file_path in full_path.rglob("*"):
            if not file_path.is_file():
                continue
            if ".git" in file_path.parts:
                continue

            content = file_path.read_bytes()
            blob = Blob(content)
            blob_hash = self.save_object(blob)

            rel_path = str(file_path.relative_to(self.path))
            index[rel_path] = blob_hash
            added_count += 1

        self.write_index(index)

        if added_count > 0:
            print(f"Added {added_count} files from directory {path}")
        else:
            print(f"Directory {path} already up to date")

    def stage_path(self, path: str) -> None:
        # Entry point used by the "add" command; determines whether the
        # given path is a file or a directory and delegates accordingly.
        full_path = self.path / path

        if not full_path.exists():
            raise FileNotFoundError(f"Path {path} not found")

        if full_path.is_file():
            self.stage_file(path)
        elif full_path.is_dir():
            self.stage_directory(path)
        else:
            raise ValueError(f"{path} is neither a file nor a directory")

    def read_object(self, obj_hash: str) -> RepoObject:
        # Retrieves an object from disk by its hash; the inverse of save_object.
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]

        if not obj_file.exists():
            raise FileNotFoundError(f"Object {obj_hash} not found")

        return RepoObject.deserialize(obj_file.read_bytes())

    def build_tree_from_index(self, index: Dict[str, str]):
        # Converts a flat {path: blob_hash} mapping into a tree object.
        if not index:
            tree = Tree()
            return self.save_object(tree)

        # Separate staged paths into root-level files and subdirectories;
        # subdirectory contents are assembled into nested dicts one level at a time.
        root_files: Dict[str, str] = {}
        root_dirs: Dict[str, Dict] = {}

        for file_path, blob_hash in index.items():
            parts = file_path.split("/")

            if len(parts) == 1:
                root_files[parts[0]] = blob_hash
                continue

            dir_name = parts[0]
            if dir_name not in root_dirs:
                root_dirs[dir_name] = {}
            current = root_dirs[dir_name]

            for part in parts[1:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            current[parts[-1]] = blob_hash

        root_entries: Dict[str, Any] = dict(root_files)
        for dir_name, dir_contents in root_dirs.items():
            root_entries[dir_name] = dir_contents

        return self._save_tree_dict(root_entries)

    def _save_tree_dict(self, entries_dict: Dict) -> str:
        # Converts a nested dict of {name: blob_hash or {sub-dict}} into
        # persisted Tree objects, processing the innermost subdirectories first.
        tree = Tree()

        for name, value in entries_dict.items():
            if isinstance(value, dict):
                subtree_hash = self._save_tree_dict(value)
                tree.add_entry("40000", name, subtree_hash)
            else:
                tree.add_entry("100644", name, value)

        return self.save_object(tree)

    def get_active_branch(self) -> str:
        # HEAD stores a single line of the form "ref: refs/heads/<branch name>",
        # so extracting the branch name requires stripping that prefix.
        if not self.head_file.exists():
            return "master"

        head_content = self.head_file.read_text().strip()
        if head_content.startswith("ref: refs/heads/"):
            return head_content[16:]

        return "HEAD"  # not on a branch

    def get_branch_head(self, branch_name: str):
        # Each branch is represented by a file containing the hash of its latest commit.
        branch_file = self.heads_dir / branch_name

        if branch_file.exists():
            return branch_file.read_text().strip()

        return None

    def update_branch_head(self, branch_name: str, commit_hash: str):
        # Advances a branch by overwriting its file with the new commit hash.
        branch_file = self.heads_dir / branch_name
        branch_file.write_text(commit_hash + "\n")

    def commit(
        self,
        message: str,
        author: str = "Rithika Yalla <yallarithikareddy@gmail.com>",
    ):
        current_branch = self.get_active_branch()
        parent_commit = self.get_branch_head(current_branch)
        parent_hashes = [parent_commit] if parent_commit else []

        # An empty index means there is nothing new to commit.
        index = self.read_index()
        if not index:
            print("nothing to commit, working tree clean")
            return None

        # A commit should capture the full project state, not just the files
        # staged for this commit, so the staged index is merged on top of the
        # parent commit's tracked files before building the tree.
        parent_commit_data = None
        full_index = dict(index)
        if parent_commit:
            parent_repo_commit_obj = self.read_object(parent_commit)
            parent_commit_data = Commit.from_content(parent_repo_commit_obj.content)
            if parent_commit_data.tree_hash:
                full_index = self.read_tree_as_index(parent_commit_data.tree_hash)
                full_index.update(index)

        tree_hash = self.build_tree_from_index(full_index)

        # Also skip the commit if the resulting tree matches the parent
        # commit's tree, meaning the staged files are unchanged.
        if parent_commit_data and tree_hash == parent_commit_data.tree_hash:
            print("nothing to commit, working tree clean")
            return None

        commit = Commit(
            tree_hash=tree_hash,
            parent_hashes=parent_hashes,
            author=author,
            committer=author,
            message=message,
        )
        commit_hash = self.save_object(commit)

        # Advance the branch pointer and clear the staging area.
        self.update_branch_head(current_branch, commit_hash)
        self.write_index({})
        print(f"Created commit {commit_hash} on branch {current_branch}")
        return commit_hash

    def collect_files_in_tree(
        self,
        tree_hash: str,
        prefix: str = "",
    ):
        # Recursively enumerates every file path contained in a tree,
        # descending into subdirectories; prefix accumulates the path built so far.
        files = set()
        try:
            tree_obj = self.read_object(tree_hash)
            tree = Tree.from_content(tree_obj.content)
            # Each entry is a (mode, name, hash) tuple.
            for mode, name, obj_hash in tree.entries:
                full_name = f"{prefix}{name}"
                if mode.startswith("100"):
                    files.add(full_name)
                elif mode.startswith("400"):
                    subtree_files = self.collect_files_in_tree(
                        obj_hash, f"{full_name}/"
                    )
                    files.update(subtree_files)
        except Exception as e:
            print(f"Warning: Could not read tree {tree_hash}: {e}")

        return files

    def checkout(self, branch: str, create_branch: bool):
        # Determine which files belong to the branch being left.
        previous_branch = self.get_active_branch()
        files_to_clear = set()
        try:
            previous_commit_hash = self.get_branch_head(previous_branch)
            if previous_commit_hash:
                prev_commit_object = self.read_object(previous_commit_hash)
                prev_commit = Commit.from_content(prev_commit_object.content)
                if prev_commit.tree_hash:
                    files_to_clear = self.collect_files_in_tree(
                        prev_commit.tree_hash
                    )
        except Exception:
            files_to_clear = set()

        # Create the branch if requested, or switch to an existing one.
        branch_file = self.heads_dir / branch
        if not branch_file.exists():
            if create_branch:
                if previous_commit_hash:
                    self.update_branch_head(branch, previous_commit_hash)
                    print(f"Created new branch {branch}")
                else:
                    print("No commits yet, cannot create a branch")
                    return
            else:
                print(f"Branch '{branch}' not found.")
                print(
                    "Use 'python3 main.py checkout -b {branch}' to create and switch to a new branch."
                )
                return
        self.head_file.write_text(f"ref: refs/heads/{branch}\n")

        # Bring the working directory in line with the new branch.
        self.sync_working_directory(branch, files_to_clear)
        print(f"Switched to branch {branch}")

    def write_tree_to_disk(self, tree_hash: str, path: Path):
        # Inverse of build_tree_from_index: materializes the files and
        # directories described by a tree object, starting at `path`.
        tree_obj = self.read_object(tree_hash)
        tree = Tree.from_content(tree_obj.content)
        for mode, name, obj_hash in tree.entries:
            file_path = path / name
            if mode.startswith("100"):
                blob_obj = self.read_object(obj_hash)
                blob = Blob(blob_obj.content)
                file_path.write_bytes(blob.content)
            elif mode.startswith("400"):
                file_path.mkdir(exist_ok=True)
                self.write_tree_to_disk(obj_hash, file_path)

    def sync_working_directory(
        self,
        branch: str,
        files_to_clear: set[str],
    ):
        target_commit_hash = self.get_branch_head(branch)
        if not target_commit_hash:
            return

        # Remove files that belonged to the previous branch.
        for rel_path in sorted(files_to_clear):
            file_path = self.path / rel_path
            try:
                if file_path.is_file():
                    file_path.unlink()
                # Enable this to also remove empty leftover directories.
                # elif file_path.is_dir():
                #     if not any(file_path.iterdir()):
                #         file_path.rmdir()
            except Exception:
                pass

        # Write out the files belonging to the branch being switched to.
        target_commit_obj = self.read_object(target_commit_hash)
        target_commit = Commit.from_content(target_commit_obj.content)

        if target_commit.tree_hash:
            self.write_tree_to_disk(target_commit.tree_hash, self.path)

        # The staging area does not carry over between branches.
        self.write_index({})

    def branch(self, branch_name: str, delete: bool = False):
        # Handle branch deletion first.
        if delete and branch_name:
            branch_file = self.heads_dir / branch_name
            if branch_file.exists():
                branch_file.unlink()
                print(f"Deleted branch {branch_name}")
            else:
                print(f"Branch {branch_name} not found")

            return

        current_branch = self.get_active_branch()
        if branch_name:
            # Creating a branch means pointing a new branch file at the same
            # commit the current branch currently references.
            current_commit = self.get_branch_head(current_branch)
            if current_commit:
                self.update_branch_head(branch_name, current_commit)
                print(f"Created branch {branch_name}")
            else:
                print(f"No commits yet, cannot create a new branch")
        else:
            # No branch name provided, so list all known branches instead.
            branches = []
            for branch_file in self.heads_dir.iterdir():
                if branch_file.is_file() and not branch_file.name.startswith("."):
                    branches.append(branch_file.name)

            for branch in sorted(branches):
                current_marker = "* " if branch == current_branch else "  "
                print(f"{current_marker}{branch}")

    def log(self, max_count: int = 10):
        current_branch = self.get_active_branch()
        commit_hash = self.get_branch_head(current_branch)

        if not commit_hash:
            print("No commits yet!")
            return

        # Start at the most recent commit and traverse backwards through parents.
        count = 0
        while commit_hash and count < max_count:
            commit_obj = self.read_object(commit_hash)
            commit = Commit.from_content(commit_obj.content)

            print(f"commit {commit_hash}")
            print(f"Author: {commit.author}")
            print(f"Date: {time.ctime(commit.timestamp)}")
            print(f"\n    {commit.message}\n")

            # Advance to the parent commit; this becomes None at the first commit.
            commit_hash = commit.parent_hashes[0] if commit.parent_hashes else None
            count += 1

    def read_tree_as_index(self, tree_hash: str, prefix: str = ""):
        # Inverse of build_tree_from_index: flattens a tree object back
        # into a {path: blob_hash} dict in the same shape as the index file.
        index = {}
        try:
            tree_obj = self.read_object(tree_hash)
            tree = Tree.from_content(tree_obj.content)
            # Each entry is a (mode, name, hash) tuple.
            for mode, name, obj_hash in tree.entries:
                full_name = f"{prefix}{name}"
                if mode.startswith("100"):
                    index[full_name] = obj_hash
                elif mode.startswith("400"):
                    subindex = self.read_tree_as_index(obj_hash, f"{full_name}/")
                    index.update(subindex)
        except Exception as e:
            print(f"Warning: Could not read tree {tree_hash}: {e}")

        return index

    def list_working_files(self) -> List[Path]:
        # Returns every file currently present in the working directory,
        # excluding the .git directory itself.
        files = []

        for item in self.path.rglob("*"):
            if ".git" in item.parts:
                continue

            if item.is_file():
                files.append(item)

        return files

    def status(self):
        # Report the currently active branch.
        current_branch = self.get_active_branch()
        print(f"On branch {current_branch}")
        index = self.read_index()
        current_commit_hash = self.get_branch_head(current_branch)

        # Reconstruct the file listing recorded in the most recent commit.
        last_index_files = {}
        if current_commit_hash:
            try:
                commit_obj = self.read_object(current_commit_hash)
                commit = Commit.from_content(commit_obj.content)
                if commit.tree_hash:
                    last_index_files = self.read_tree_as_index(commit.tree_hash)
            except Exception:
                last_index_files = {}

        # Scan the working directory for the files currently present on disk.
        working_files = {}  # maps file path to its content hash
        for item in self.list_working_files():
            rel_path = str(item.relative_to(self.path))

            try:
                content = item.read_bytes()
                blob = Blob(content)
                working_files[rel_path] = blob.hash()
            except Exception:
                continue

        staged_files = []
        unstaged_files = []
        untracked_files = []
        deleted_files = []

        # Collect every path present in either the index or the last commit.
        all_known_paths = list(index.keys())
        for file_path in last_index_files.keys():
            if file_path not in all_known_paths:
                all_known_paths.append(file_path)

        # Identify files staged for commit.
        for file_path in all_known_paths:
            index_hash = index.get(file_path)
            last_index_hash = last_index_files.get(file_path)

            if index_hash and not last_index_hash:
                staged_files.append(("new file", file_path))
            elif index_hash and last_index_hash and index_hash != last_index_hash:
                staged_files.append(("modified", file_path))

        if staged_files:
            print("\nChanges to be committed:")
            for stage_status, file_path in sorted(staged_files):
                print(f"   {stage_status}: {file_path}")

        # Identify files that have changed but have not yet been staged.
        for file_path in working_files:
            if file_path in index:
                if working_files[file_path] != index[file_path]:
                    unstaged_files.append(file_path)

        if unstaged_files:
            print("\nChanges not staged for commit:")
            for file_path in sorted(unstaged_files):
                print(f"   modified: {file_path}")

        # Identify files that are not tracked at all.
        for file_path in working_files:
            if file_path not in index and file_path not in last_index_files:
                untracked_files.append(file_path)

        if untracked_files:
            print("\nUntracked files:")
            for file_path in sorted(untracked_files):
                print(f"   {file_path}")

        # Identify files that were previously tracked but no longer exist.
        for file_path in index:
            if file_path not in working_files:
                deleted_files.append(file_path)

        if deleted_files:
            print("\nDeleted files:")
            for file_path in sorted(deleted_files):
                print(f"   deleted: {file_path}")

        if (
            not staged_files
            and not unstaged_files
            and not deleted_files
            and not untracked_files
        ):
            print("\nnothing to commit, working tree clean")
