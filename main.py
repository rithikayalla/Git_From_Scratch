import argparse
import sys

from repository import Repository


def main():
    parser = argparse.ArgumentParser(description="Git Clone")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # initializes a new repository
    init_parser = subparsers.add_parser("init", help="Initialize a new repository")

    # stages files and directories
    add_parser = subparsers.add_parser(
        "add", help="Add files and directories to the staging area"
    )
    add_parser.add_argument("paths", nargs="+", help="Files and directories to add")

    # records a new commit
    commit_parser = subparsers.add_parser("commit", help="Create a new commit")
    commit_parser.add_argument(
        "-m",
        "--message",
        help="Commit message",
        required=True,
    )
    commit_parser.add_argument(
        "--author",
        help="Author name and email",
    )

    # switches to or creates a branch
    checkout_parser = subparsers.add_parser("checkout", help="Move/Create a new branch")
    checkout_parser.add_argument("branch", help="Branch to switch to")
    checkout_parser.add_argument(
        "-b",
        "--create-branch",
        action="store_true",
        help="Create and switch to a new branch",
    )

    # lists, creates, or deletes a branch
    branch_parser = subparsers.add_parser("branch", help="List or manage branches")
    branch_parser.add_argument("name", nargs="?")
    branch_parser.add_argument(
        "-d",
        "--delete",
        action="store_true",
        help="Delete the branch",
    )

    # displays commit history
    log_parser = subparsers.add_parser("log", help="Show commit history")
    log_parser.add_argument(
        "-n",
        "--max-count",
        type=int,
        default=10,
        help="Limit commits shown",
    )

    # reports the repository's current status
    status_parser = subparsers.add_parser("status", help="Show repository status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    repo = Repository()
    try:
        # Every command other than "init" requires an existing .git directory.
        if args.command == "init":
            if not repo.init():
                print("Repository already exists")
                return
        elif args.command == "add":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return

            for path in args.paths:
                repo.stage_path(path)
        elif args.command == "commit":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return

            author = args.author or "Rithika Yalla <yallarithikareddy@gmail.com>"
            repo.commit(args.message, author)
        elif args.command == "checkout":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return
            repo.checkout(args.branch, args.create_branch)
        elif args.command == "branch":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return

            repo.branch(args.name, args.delete)
        elif args.command == "log":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return

            repo.log(args.max_count)
        elif args.command == "status":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return

            repo.status()

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


main()
