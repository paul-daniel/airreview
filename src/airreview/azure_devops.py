from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class AzureDevOpsContext:
    collection_uri: str
    project: str
    repository_id: str
    pull_request_id: str
    source_branch: str | None
    target_branch: str | None
    token_present: bool

    @property
    def is_complete(self) -> bool:
        return bool(self.collection_uri and self.project and self.repository_id and self.pull_request_id and self.token_present)


def pr_context() -> AzureDevOpsContext:
    return AzureDevOpsContext(
        collection_uri=os.getenv("SYSTEM_COLLECTIONURI", ""),
        project=os.getenv("SYSTEM_TEAMPROJECT", ""),
        repository_id=os.getenv("BUILD_REPOSITORY_ID", ""),
        pull_request_id=os.getenv("SYSTEM_PULLREQUEST_PULLREQUESTID", ""),
        source_branch=os.getenv("SYSTEM_PULLREQUEST_SOURCEBRANCH"),
        target_branch=os.getenv("SYSTEM_PULLREQUEST_TARGETBRANCH"),
        token_present=bool(os.getenv("SYSTEM_ACCESSTOKEN")),
    )


def post_pr_comment(markdown: str, dry_run: bool = False) -> dict[str, Any]:
    context = pr_context()
    if dry_run:
        return {"posted": False, "dry_run": True, "context_complete": context.is_complete}
    if not context.is_complete:
        raise RuntimeError(
            "Azure DevOps context is incomplete. Ensure PR variables are present and Allow scripts to access OAuth token is enabled."
        )
    url = (
        f"{context.collection_uri.rstrip('/')}/{context.project}/_apis/git/repositories/"
        f"{context.repository_id}/pullRequests/{context.pull_request_id}/threads?api-version=7.1"
    )
    payload = {
        "comments": [{"parentCommentId": 0, "content": markdown, "commentType": 1}],
        "status": 1,
    }
    response = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {os.environ['SYSTEM_ACCESSTOKEN']}", "Content-Type": "application/json"},
        timeout=30,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"Azure DevOps comment failed: {response.status_code} {response.text[:500]}")
    return {"posted": True, "status_code": response.status_code}
