"""Wrapper do GitHub CLI (`gh`): coleta de dados do PR e ações de decisão.

Tudo roda via subprocess (sem shell) usando a autenticação já existente do `gh` na máquina.
"""
import json
import os
import subprocess
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote


class GitHubCliError(RuntimeError):
    """Falha na execução de um comando `gh`."""


class GitHubCli:
    def __init__(self, timeout: int = 120, runner: Callable[..., Any] = subprocess.run):
        self.timeout = timeout
        self._runner = runner

    def _run(self, args: List[str], stdin: Optional[str] = None) -> str:
        env = {**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}
        try:
            completed = self._runner(
                ["gh", *args],
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=env,
            )
        except FileNotFoundError as exc:
            raise GitHubCliError("GitHub CLI (`gh`) não encontrado no PATH. Instale e rode `gh auth login`.") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitHubCliError(f"Timeout ({self.timeout}s) ao executar: gh {' '.join(args[:3])}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise GitHubCliError(f"gh {' '.join(args[:3])} falhou: {detail}")
        return completed.stdout

    def pr_view(self, repo: str, pr_number: int) -> Dict[str, Any]:
        out = self._run([
            "pr", "view", str(pr_number), "--repo", repo,
            "--json", "files,body,title,baseRefName,headRefOid",
        ])
        return json.loads(out)

    def pr_diff(self, repo: str, pr_number: int) -> str:
        return self._run(["pr", "diff", str(pr_number), "--repo", repo, "--color", "never"])

    def list_tree(self, repo: str, ref: str) -> List[Dict[str, Any]]:
        """Lista recursivamente os arquivos (blobs) de uma branch/commit via API."""
        out = self._run(["api", f"repos/{repo}/git/trees/{quote(ref, safe='')}?recursive=1"])
        data = json.loads(out)
        return [entry for entry in data.get("tree", []) if entry.get("type") == "blob"]

    def read_file(self, repo: str, path: str, ref: str) -> str:
        return self._run([
            "api", "-H", "Accept: application/vnd.github.raw+json",
            f"repos/{repo}/contents/{quote(path)}?ref={quote(ref, safe='')}",
        ])

    def approve(self, repo: str, pr_number: int, body: str) -> None:
        self._review(repo, pr_number, "--approve", body)

    def request_changes(self, repo: str, pr_number: int, body: str) -> None:
        self._review(repo, pr_number, "--request-changes", body)

    def _review(self, repo: str, pr_number: int, action: str, body: str) -> None:
        # O corpo vai por stdin (-F -) para suportar texto multilinha/Unicode sem limite de linha de comando.
        self._run(["pr", "review", str(pr_number), "--repo", repo, action, "-F", "-"], stdin=body)

