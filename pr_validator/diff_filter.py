"""Filtro de ruído para a saída de `gh pr diff` (lockfiles, binários, arquivos gerados)."""
import fnmatch
import re
from dataclasses import dataclass, field
from typing import List, Sequence

_HEADER = re.compile(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$')


@dataclass
class DiffBlock:
    path: str
    text: str


@dataclass
class SkippedFile:
    path: str
    reason: str


@dataclass
class FilteredDiff:
    blocks: List[DiffBlock] = field(default_factory=list)
    skipped: List[SkippedFile] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(block.text for block in self.blocks)


def split_diff(raw_diff: str) -> List[DiffBlock]:
    """Divide um diff unificado em um bloco por arquivo (`diff --git ...`)."""
    blocks: List[DiffBlock] = []
    current_path = None
    current_lines: List[str] = []

    def flush() -> None:
        if current_path is not None:
            blocks.append(DiffBlock(path=current_path, text="".join(current_lines)))

    for line in raw_diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            flush()
            match = _HEADER.match(line.rstrip("\r\n"))
            current_path = match.group(2) if match else line.strip()
            current_lines = [line]
        elif current_path is not None:
            current_lines.append(line)
    flush()
    return blocks


def _is_binary(block_text: str) -> bool:
    return "\nBinary files " in block_text or "\nGIT binary patch" in block_text


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    lowered = path.lower()
    basename = lowered.rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatchcase(lowered, pattern) or fnmatch.fnmatchcase(basename, pattern)
        for pattern in patterns
    )


def filter_diff(raw_diff: str, ignore_patterns: Sequence[str]) -> FilteredDiff:
    """Remove do diff os arquivos irrelevantes e registra o motivo de cada remoção."""
    result = FilteredDiff()
    for block in split_diff(raw_diff):
        if _is_binary(block.text):
            result.skipped.append(SkippedFile(block.path, "arquivo binário"))
        elif _matches_any(block.path, ignore_patterns):
            result.skipped.append(SkippedFile(block.path, "arquivo gerado/lockfile/mídia"))
        else:
            result.blocks.append(block)
    return result

