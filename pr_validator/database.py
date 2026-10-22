"""Persistência SQLite da tabela PullRequestReviews."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

PENDING = "PENDING"
PROCESSING = "PROCESSING"
WAITING_APPROVAL = "WAITING_APPROVAL"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
ERROR = "ERROR"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS PullRequestReviews (
    Id            INTEGER PRIMARY KEY AUTOINCREMENT,
    Repo          TEXT    NOT NULL,
    PrNumber      INTEGER NOT NULL,
    Author        TEXT    NOT NULL DEFAULT '',
    Title         TEXT    NOT NULL DEFAULT '',
    HeadBranch    TEXT    NOT NULL DEFAULT '',
    CommitSha     TEXT    NOT NULL DEFAULT '',
    Status        TEXT    NOT NULL,
    DiffContent   TEXT,
    AiVerdictJson TEXT,
    ErrorMessage  TEXT,
    DecisionComment TEXT,
    CreatedAt     TEXT    NOT NULL,
    UpdatedAt     TEXT    NOT NULL,
    UNIQUE (Repo, PrNumber)
);
"""

# Colunas devolvidas na listagem (sem o diff, que pode ser grande).
_SUMMARY_COLUMNS = (
    "Id, Repo, PrNumber, Author, Title, HeadBranch, CommitSha, Status, "
    "AiVerdictJson, ErrorMessage, CreatedAt, UpdatedAt"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReviewRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        directory = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(directory, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão por operação, com commit/rollback e fechamento garantidos."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def upsert_pending(
        self, repo: str, pr_number: int, author: str, title: str, head_branch: str, commit_sha: str
    ) -> int:
        """Cria o registro do PR ou, em um novo push, reinicia a validação do mesmo PrNumber."""
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO PullRequestReviews
                    (Repo, PrNumber, Author, Title, HeadBranch, CommitSha, Status, CreatedAt, UpdatedAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (Repo, PrNumber) DO UPDATE SET
                    Author = excluded.Author, Title = excluded.Title,
                    HeadBranch = excluded.HeadBranch, CommitSha = excluded.CommitSha,
                    Status = excluded.Status, DiffContent = NULL, AiVerdictJson = NULL,
                    ErrorMessage = NULL, DecisionComment = NULL, UpdatedAt = excluded.UpdatedAt
                """,
                (repo, pr_number, author, title, head_branch, commit_sha, PENDING, now, now),
            )
            row = conn.execute(
                "SELECT Id FROM PullRequestReviews WHERE Repo = ? AND PrNumber = ?", (repo, pr_number)
            ).fetchone()
        return int(row["Id"])

    def claim_for_processing(self, review_id: int) -> bool:
        """Transição atômica PENDING -> PROCESSING; evita processar a mesma fila duas vezes."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE PullRequestReviews SET Status = ?, UpdatedAt = ? WHERE Id = ? AND Status = ?",
                (PROCESSING, _now(), review_id, PENDING),
            )
            return cursor.rowcount == 1

    def get(self, review_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM PullRequestReviews WHERE Id = ?", (review_id,)).fetchone()
        return dict(row) if row else None

    def list_summaries(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_SUMMARY_COLUMNS} FROM PullRequestReviews ORDER BY UpdatedAt DESC, Id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def unfinished_ids(self) -> List[int]:
        """IDs que ficaram na fila (PENDING/PROCESSING) caso o servidor tenha sido reiniciado."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE PullRequestReviews SET Status = ? WHERE Status = ?", (PENDING, PROCESSING)
            )
            rows = conn.execute(
                "SELECT Id FROM PullRequestReviews WHERE Status = ? ORDER BY Id", (PENDING,)
            ).fetchall()
        return [int(row["Id"]) for row in rows]

    def save_result(self, review_id: int, commit_sha: str, diff_content: str, verdict_json: str) -> bool:
        """Grava o veredito apenas se o PR ainda está no commit validado (descarta resultado obsoleto)."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE PullRequestReviews
                SET Status = ?, DiffContent = ?, AiVerdictJson = ?, ErrorMessage = NULL, UpdatedAt = ?
                WHERE Id = ? AND CommitSha = ? AND Status = ?
                """,
                (WAITING_APPROVAL, diff_content, verdict_json, _now(), review_id, commit_sha, PROCESSING),
            )
            return cursor.rowcount == 1

    def save_error(self, review_id: int, commit_sha: str, message: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE PullRequestReviews SET Status = ?, ErrorMessage = ?, UpdatedAt = ?
                WHERE Id = ? AND CommitSha = ? AND Status = ?
                """,
                (ERROR, message, _now(), review_id, commit_sha, PROCESSING),
            )
            return cursor.rowcount == 1

    def save_decision(self, review_id: int, status: str, comment: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE PullRequestReviews SET Status = ?, DecisionComment = ?, UpdatedAt = ? WHERE Id = ?",
                (status, comment, _now(), review_id),
            )

    def requeue(self, review_id: int) -> bool:
        """Recoloca na fila um registro em ERROR ou aguardando decisão (revalidar com o mesmo commit)."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE PullRequestReviews SET Status = ?, ErrorMessage = NULL, UpdatedAt = ? "
                "WHERE Id = ? AND Status IN (?, ?)",
                (PENDING, _now(), review_id, ERROR, WAITING_APPROVAL),
            )
            return cursor.rowcount == 1
