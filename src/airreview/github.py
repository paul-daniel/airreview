from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True)
class GitHubContext:
    repository: str
    server_url: str
    api_url: str
    event_name: str
    event_path: str
    pull_request_number: int | None
    token_present: bool

    @property
    def is_pull_request(self) -> bool:
        return bool(self.pull_request_number)

    @property
    def is_complete(self) -> bool:
        return bool(self.repository and self.pull_request_number and self.token_present)


def github_context() -> GitHubContext:
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    return GitHubContext(
        repository=os.getenv("GITHUB_REPOSITORY", ""),
        server_url=os.getenv("GITHUB_SERVER_URL", "https://github.com"),
        api_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
        event_name=os.getenv("GITHUB_EVENT_NAME", ""),
        event_path=event_path,
        pull_request_number=_pull_request_number(event_path),
        token_present=bool(os.getenv("GITHUB_TOKEN")),
    )


def post_pr_comment(markdown: str, dry_run: bool = False) -> dict[str, Any]:
    context = github_context()
    if dry_run:
        return {"posted": False, "dry_run": True, "context_complete": context.is_complete}
    if not context.is_complete:
        raise RuntimeError(
            "GitHub context is incomplete. Run in a pull_request workflow with pull-requests: write permission and GITHUB_TOKEN."
        )
    url = f"{context.api_url.rstrip('/')}/repos/{context.repository}/issues/{context.pull_request_number}/comments"
    response = requests.post(
        url,
        json={"body": markdown},
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"GitHub PR comment failed: {response.status_code} {response.text[:500]}")
    payload = response.json()
    return {"posted": True, "status_code": response.status_code, "url": payload.get("html_url")}


def _pull_request_number(event_path: str) -> int | None:
    if not event_path:
        return None
    path = Path(event_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    number = payload.get("pull_request", {}).get("number") or payload.get("number")
    try:
        return int(number)
    except (TypeError, ValueError):
        return None
