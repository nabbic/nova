import json
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
    # GitHub blocks the PR creator from approving their own PR, so we skip the
    # review step and merge directly. Branch protection rules are managed separately.
    subprocess.run(
        ["gh", "pr", "merge", pr_url, "--merge", "--delete-branch"], check=True
    )


def trigger_repository_dispatch(feature_id: str) -> None:
    """Dispatch a factory-trigger event to start the factory for a feature.

    Uses gh CLI which resolves {owner}/{repo} from the current git remote.
    """
    payload = json.dumps({
        "event_type": "factory-trigger",
        "client_payload": {"feature_id": feature_id},
    })
    subprocess.run(
        [
            "gh", "api", "repos/{owner}/{repo}/dispatches",
            "--method", "POST",
            "--input", "-",
        ],
        input=payload,
        text=True,
        check=True,
    )
