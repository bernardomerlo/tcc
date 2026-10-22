"""Coleta da documentação vigente: branch base + versões alteradas pelo PR."""
from dataclasses import dataclass
from typing import Iterable, List

from .config import Settings
from .github_cli import GitHubCli, GitHubCliError


@dataclass
class DocFile:
    path: str
    content: str
    origin: str  # "base" ou "pr"


def is_doc_path(path: str, settings: Settings) -> bool:
    in_scope = any(
        path == entry or (entry.endswith("/") and path.startswith(entry))
        for entry in settings.docs_paths
    )
    return in_scope and path.lower().endswith(settings.doc_extensions)


def collect_documentation(
    github: GitHubCli,
    settings: Settings,
    repo: str,
    base_ref: str,
    head_sha: str,
    changed_paths: Iterable[str],
) -> List[DocFile]:
    """Lê os docs da branch base e sobrepõe, pela versão do PR, os docs que o PR alterou.

    Docs removidos no PR (404 no head) saem do conjunto; docs novos no PR entram.
    """
    docs = {}
    for entry in github.list_tree(repo, base_ref):
        path = entry["path"]
        if is_doc_path(path, settings) and entry.get("size", 0) <= settings.max_doc_file_bytes:
            docs[path] = DocFile(path, github.read_file(repo, path, base_ref), "base")

    for path in changed_paths:
        if not is_doc_path(path, settings):
            continue
        try:
            docs[path] = DocFile(path, github.read_file(repo, path, head_sha), "pr")
        except GitHubCliError as exc:
            if "404" in str(exc) or "Not Found" in str(exc):
                docs.pop(path, None)
            else:
                raise
    return [docs[path] for path in sorted(docs)]

