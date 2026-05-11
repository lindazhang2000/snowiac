"""GitHub repository integration for opening pull requests."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from github import Auth, Github, GithubException

from ..config import get_settings

log = logging.getLogger(__name__)


@dataclass
class PullRequestInfo:
    url: str
    number: int
    branch: str


class GitHubRepoClient(Protocol):
    def open_pr(
        self, *, branch: str, title: str, body: str, files: dict[str, str]
    ) -> PullRequestInfo: ...


class RealGitHubRepoClient:
    def __init__(self, token: str, repo_full_name: str, base_branch: str):
        self._gh = Github(auth=Auth.Token(token))
        self._repo = self._gh.get_repo(repo_full_name)
        self._base = base_branch

    def open_pr(
        self, *, branch: str, title: str, body: str, files: dict[str, str]
    ) -> PullRequestInfo:
        base_ref = self._repo.get_branch(self._base)
        try:
            self._repo.create_git_ref(ref=f"refs/heads/{branch}", sha=base_ref.commit.sha)
        except GithubException as e:
            if e.status != 422:  # already exists
                raise

        for path, content in files.items():
            try:
                existing = self._repo.get_contents(path, ref=branch)
                self._repo.update_file(
                    path=path,
                    message=f"snowiac: update {path}",
                    content=content,
                    sha=existing.sha,  # type: ignore[union-attr]
                    branch=branch,
                )
            except GithubException as e:
                if e.status == 404:
                    self._repo.create_file(
                        path=path,
                        message=f"snowiac: add {path}",
                        content=content,
                        branch=branch,
                    )
                else:
                    raise

        try:
            pr = self._repo.create_pull(title=title, body=body, head=branch, base=self._base)
        except GithubException as e:
            if e.status == 422:
                # PR already exists for this branch — return the existing one.
                owner = self._repo.owner.login
                existing = list(self._repo.get_pulls(state="open", head=f"{owner}:{branch}"))
                if existing:
                    pr = existing[0]
                    log.info("PR already exists for %s — reusing #%d", branch, pr.number)
                else:
                    raise
            else:
                raise
        return PullRequestInfo(url=pr.html_url, number=pr.number, branch=branch)


class MockGitHubRepoClient:
    def __init__(self) -> None:
        self.prs: list[dict] = []

    def open_pr(
        self, *, branch: str, title: str, body: str, files: dict[str, str]
    ) -> PullRequestInfo:
        n = len(self.prs) + 1
        info = PullRequestInfo(
            url=f"https://github.com/mock/mock/pull/{n}", number=n, branch=branch
        )
        self.prs.append({"branch": branch, "title": title, "body": body, "files": files})
        log.info("[MOCK GH] opened PR #%d on %s with %d files", n, branch, len(files))
        return info


def build_client() -> GitHubRepoClient:
    s = get_settings()
    if s.snowiac_use_mocks or not s.github_token or not s.github_repo:
        return MockGitHubRepoClient()
    return RealGitHubRepoClient(s.github_token, s.github_repo, s.github_base_branch)
