import subprocess


def create_branch(branch_name: str) -> None:
    subprocess.run(["git", "checkout", "-b", branch_name], check=True)


def commit_all(message: str) -> None:
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)


def push_branch(branch_name: str) -> None:
    subprocess.run(
        ["git", "push", "--set-upstream", "origin", branch_name], check=True
    )


def create_pr(title: str, body: str, branch: str) -> str:
    """Opens a PR and returns its URL."""
    result = subprocess.run(
        [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--head", branch,
            "--base", "main",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def approve_and_merge_pr(pr_url: str) -> None:
    subprocess.run(["gh", "pr", "review", pr_url, "--approve"], check=True)
    subprocess.run(
        ["gh", "pr", "merge", pr_url, "--merge", "--delete-branch"], check=True
    )
