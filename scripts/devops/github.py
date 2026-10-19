"""Small JSON-only GitHub transport. Issue content is never shell input."""

import json
import subprocess


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, repository):
        self.repository = repository

    def api(self, path, *, method="GET", data=None, paginate=False):
        args = ["gh", "api", path, "--method", method]
        if paginate:
            args += ["--paginate", "--slurp"]
        if data is not None:
            args += ["--input", "-"]
        result = subprocess.run(
            args,
            input=json.dumps(data) if data is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode:
            # Never include request bodies/credentials in diagnostics.
            raise GitHubError(f"GitHub {method} {path}: {result.stderr.strip()}")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def repo(self, path="", **kwargs):
        return self.api(f"repos/{self.repository}/{path}".rstrip("/"), **kwargs)

    def pages(self, path):
        return [item for page in self.repo(path, paginate=True) for item in page]

    def graphql(self, query, **variables):
        result = self.api(
            "graphql", method="POST", data={"query": query, "variables": variables}
        )
        if result.get("errors"):
            raise GitHubError(json.dumps(result["errors"]))
        return result["data"]
