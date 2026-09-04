"""
Automated tests covering the edge case scenarios.

"""
from __future__ import annotations

import pytest

from repository import Repository


@pytest.fixture
def repo(tmp_path):
    r = Repository(tmp_path)
    r.init()
    return r


def write(repo: Repository, rel_path: str, content: str) -> None:
    full_path = repo.path / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)


# --- init -------------------------------------------------------------

def test_init_creates_expected_structure(tmp_path):
    r = Repository(tmp_path)
    assert r.init() is True

    assert r.git_dir.is_dir()
    assert r.objects_dir.is_dir()
    assert r.heads_dir.is_dir()
    assert r.head_file.read_text() == "ref: refs/heads/master\n"
    assert r.read_index() == {}


def test_init_twice_returns_false(tmp_path):
    r = Repository(tmp_path)
    assert r.init() is True
    assert r.init() is False


# --- add ----------------------------------------------------------------

def test_add_missing_file_raises(repo):
    with pytest.raises(FileNotFoundError):
        repo.stage_path("missing.txt")


def test_add_missing_directory_raises(repo):
    with pytest.raises(FileNotFoundError):
        repo.stage_path("missing_dir")


def test_add_file_records_blob_hash_in_index(repo):
    write(repo, "file1.txt", "hello")
    repo.stage_path("file1.txt")

    index = repo.read_index()
    assert "file1.txt" in index
    assert len(index["file1.txt"]) == 40  # sha1 hex digest length


def test_add_directory_stages_every_file_recursively(repo):
    write(repo, "docs/readme.txt", "readme")
    write(repo, "docs/nested/more.txt", "more")
    repo.stage_path("docs")

    index = repo.read_index()
    assert set(index.keys()) == {"docs/readme.txt", "docs/nested/more.txt"}


def test_add_empty_directory_stages_nothing(repo):
    (repo.path / "empty_dir").mkdir()
    repo.stage_path("empty_dir")

    assert repo.read_index() == {}


# --- commit ---------------------------------------------------------------

def test_commit_with_nothing_staged_returns_none(repo):
    assert repo.commit("empty") is None


def test_commit_creates_commit_and_clears_index(repo):
    write(repo, "a.txt", "A")
    repo.stage_path("a.txt")

    commit_hash = repo.commit("first commit")

    assert commit_hash is not None
    assert repo.read_index() == {}
    assert repo.get_branch_head("master") == commit_hash


def test_commit_is_noop_when_tree_matches_parent(repo):
    write(repo, "a.txt", "A")
    repo.stage_path("a.txt")
    first_hash = repo.commit("first commit")

    # Re-adding the same, unchanged content should produce an identical tree.
    repo.stage_path("a.txt")
    second_result = repo.commit("second commit")

    assert second_result is None
    assert repo.get_branch_head("master") == first_hash


def test_commit_uses_custom_author(repo):
    write(repo, "a.txt", "A")
    repo.stage_path("a.txt")
    commit_hash = repo.commit("msg", author="Test Author <test@example.com>")

    commit_obj = repo.read_object(commit_hash)
    from objects import Commit
    commit = Commit.from_content(commit_obj.content)
    assert commit.author == "Test Author <test@example.com>"


def test_commit_is_cumulative_across_separate_adds(repo):
    """
    Regression test for the bug where each commit's tree only contained
    whatever was staged for that specific commit, silently dropping files
    tracked by earlier commits. A file added and committed once should stay
    tracked in every later commit without being re-added.
    """
    write(repo, "a.txt", "A")
    repo.stage_path("a.txt")
    repo.commit("commit A")

    write(repo, "b.txt", "B")
    repo.stage_path("b.txt")
    repo.commit("commit B")

    latest_commit_hash = repo.get_branch_head("master")
    commit_obj = repo.read_object(latest_commit_hash)
    from objects import Commit
    latest_tree_hash = Commit.from_content(commit_obj.content).tree_hash

    tracked_files = repo.read_tree_as_index(latest_tree_hash)
    assert set(tracked_files.keys()) == {"a.txt", "b.txt"}


# --- log --------------------------------------------------------------

def test_log_with_no_commits(repo, capsys):
    repo.log()
    assert "No commits yet!" in capsys.readouterr().out


def test_log_lists_newest_commit_first(repo, capsys):
    write(repo, "a.txt", "A")
    repo.stage_path("a.txt")
    first_hash = repo.commit("first")

    write(repo, "b.txt", "B")
    repo.stage_path("b.txt")
    second_hash = repo.commit("second")

    capsys.readouterr()  # discard the "Added"/"Created commit" noise above
    repo.log()
    output = capsys.readouterr().out
    assert output.index(second_hash) < output.index(first_hash)


def test_log_respects_max_count(repo, capsys):
    for i in range(3):
        write(repo, f"file{i}.txt", str(i))
        repo.stage_path(f"file{i}.txt")
        repo.commit(f"msg {i}")  # avoid the word "commit" so it doesn't skew the count below

    capsys.readouterr()  # discard the "Added"/"Created commit" noise above
    repo.log(max_count=1)
    output = capsys.readouterr().out
    assert output.count("commit ") == 1


# --- branch -------------------------------------------------------------

def test_branch_list_before_any_commit_is_empty(repo, capsys):
    # No commit has happened yet, so master's branch file doesn't exist
    # yet either (it's only created on the first commit) — "branch" has
    # nothing to list.
    capsys.readouterr()
    repo.branch(None)
    assert capsys.readouterr().out.strip() == ""


def test_branch_list_shows_master_after_first_commit(repo, capsys):
    write(repo, "a.txt", "A")
    repo.stage_path("a.txt")
    repo.commit("first")

    capsys.readouterr()
    repo.branch(None)
    assert capsys.readouterr().out.strip() == "* master"


def test_branch_create_without_commits_fails(repo, capsys):
    repo.branch("feature")
    assert "No commits yet" in capsys.readouterr().out
    assert repo.get_branch_head("feature") is None


def test_branch_create_points_at_current_commit(repo):
    write(repo, "a.txt", "A")
    repo.stage_path("a.txt")
    commit_hash = repo.commit("first")

    repo.branch("feature")

    assert repo.get_branch_head("feature") == commit_hash


def test_branch_delete_existing(repo, capsys):
    write(repo, "a.txt", "A")
    repo.stage_path("a.txt")
    repo.commit("first")
    repo.branch("feature")

    repo.branch("feature", delete=True)

    assert "Deleted branch feature" in capsys.readouterr().out
    assert repo.get_branch_head("feature") is None


def test_branch_delete_nonexistent(repo, capsys):
    repo.branch("ghost", delete=True)
    assert "Branch ghost not found" in capsys.readouterr().out


# --- checkout -------------------------------------------------------------

def test_checkout_nonexistent_branch_without_create_fails(repo, capsys):
    write(repo, "a.txt", "A")
    repo.stage_path("a.txt")
    repo.commit("first")

    repo.checkout("ghost", create_branch=False)

    assert "not found" in capsys.readouterr().out
    assert repo.get_active_branch() == "master"


def test_checkout_create_branch_without_commits_fails(repo, capsys):
    repo.checkout("feature", create_branch=True)
    assert "No commits yet" in capsys.readouterr().out


def test_checkout_isolates_files_between_branches(repo):
    write(repo, "shared.txt", "shared")
    repo.stage_path("shared.txt")
    repo.commit("initial")

    repo.checkout("feature", create_branch=True)
    write(repo, "only_on_feature.txt", "feature only")
    repo.stage_path("only_on_feature.txt")
    repo.commit("add feature file")

    repo.checkout("master", create_branch=False)

    assert (repo.path / "shared.txt").exists()
    assert not (repo.path / "only_on_feature.txt").exists()

    repo.checkout("feature", create_branch=False)
    assert (repo.path / "only_on_feature.txt").exists()


# --- status -----------------------------------------------------------

def test_status_on_clean_new_repo(repo, capsys):
    repo.status()
    output = capsys.readouterr().out
    assert "On branch master" in output
    assert "nothing to commit" in output


def test_status_shows_untracked_files(repo, capsys):
    write(repo, "file1.txt", "hello")
    repo.status()
    assert "Untracked files:" in capsys.readouterr().out


def test_status_shows_staged_new_file(repo, capsys):
    write(repo, "file1.txt", "hello")
    repo.stage_path("file1.txt")

    repo.status()
    output = capsys.readouterr().out
    assert "Changes to be committed:" in output
    assert "new file: file1.txt" in output


def test_status_shows_staged_modification(repo, capsys):
    write(repo, "file1.txt", "hello")
    repo.stage_path("file1.txt")
    repo.commit("first")

    write(repo, "file1.txt", "hello world")
    repo.stage_path("file1.txt")

    repo.status()
    output = capsys.readouterr().out
    assert "modified: file1.txt" in output


def test_status_shows_deleted_file(repo, capsys):
    write(repo, "file1.txt", "hello")
    repo.stage_path("file1.txt")
    repo.commit("first")


    repo.stage_path("file1.txt")
    (repo.path / "file1.txt").unlink()

    capsys.readouterr()
    repo.status()
    output = capsys.readouterr().out

    assert "Deleted files:" in output
    assert "deleted: file1.txt" in output


def test_status_clean_after_commit(repo, capsys):
    write(repo, "file1.txt", "hello")
    repo.stage_path("file1.txt")
    repo.commit("first")

    repo.status()
    assert "nothing to commit, working tree clean" in capsys.readouterr().out
