"""Servidor Flask: recepção do webhook, API do dashboard e ações de decisão do chefe."""
import hmac
import json
import re
from typing import Any, Dict, Tuple
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_from_directory

from . import database
from .config import Settings
from .database import ReviewRepository
from .github_cli import GitHubCli, GitHubCliError
from .worker import ReviewWorker

_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DECIDABLE = {database.WAITING_APPROVAL, database.ERROR}


def _camel(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {key[0].lower() + key[1:]: value for key, value in row.items()}
    verdict = out.pop("aiVerdictJson", None)
    out["aiVerdict"] = json.loads(verdict) if verdict else None
    return out


def _fail(message: str, status: int) -> Tuple[Any, int]:
    return jsonify({"error": message}), status


def create_app(
    settings: Settings, repository: ReviewRepository, worker: ReviewWorker, github: GitHubCli
) -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.before_request
    def _guard():
        # Proteção contra DNS rebinding: só aceita Host local.
        if urlsplit("//" + (request.host or "")).hostname not in _ALLOWED_HOSTS:
            return _fail("Host não permitido.", 403)
        if request.method == "POST" and request.path.startswith("/api/reviews/"):
            # Exigir JSON força preflight CORS (que não habilitamos), bloqueando CSRF de páginas externas.
            if not request.is_json:
                return _fail("Content-Type deve ser application/json.", 415)

    @app.get("/")
    def dashboard():
        return send_from_directory(app.root_path + "/static", "index.html")

    def receive_pr():
        if settings.webhook_secret:
            given = request.headers.get("X-Webhook-Secret", "")
            if not hmac.compare_digest(given, settings.webhook_secret):
                return _fail("Segredo do webhook inválido.", 401)
        payload = request.get_json(silent=True) or {}
        repo = str(payload.get("repo", ""))
        try:
            pr_number = int(payload.get("prNumber"))
        except (TypeError, ValueError):
            return _fail("prNumber inválido.", 400)
        if not _REPO_PATTERN.match(repo) or pr_number <= 0:
            return _fail("repo (owner/nome) ou prNumber inválido.", 400)

        review_id = repository.upsert_pending(
            repo=repo,
            pr_number=pr_number,
            author=str(payload.get("author", "")),
            title=str(payload.get("title", "")),
            head_branch=str(payload.get("headBranch", "")),
            commit_sha=str(payload.get("commitSha", "")),
        )
        worker.enqueue(review_id)
        return jsonify({"id": review_id, "status": database.PENDING}), 202

    app.add_url_rule("/api/webhook/pr", "webhook_pr", receive_pr, methods=["POST"])
    app.add_url_rule("/api/pr/validate", "webhook_pr_legacy", receive_pr, methods=["POST"])

    @app.get("/api/reviews")
    def list_reviews():
        return jsonify([_camel(row) for row in repository.list_summaries()])

    @app.get("/api/reviews/<int:review_id>")
    def get_review(review_id: int):
        row = repository.get(review_id)
        return jsonify(_camel(row)) if row else _fail("Revisão não encontrada.", 404)

    def decide(review_id: int, approve: bool):
        row = repository.get(review_id)
        if not row:
            return _fail("Revisão não encontrada.", 404)
        if row["Status"] not in _DECIDABLE:
            return _fail(f"Revisão em {row['Status']} não pode receber decisão agora.", 409)
        comment = str((request.get_json(silent=True) or {}).get("comment", "")).strip()
        try:
            if approve:
                comment = comment or "✅ Validado com a documentação e aprovado."
                github.approve(row["Repo"], row["PrNumber"], comment)
                new_status = database.APPROVED
            else:
                if not comment:
                    return _fail("Informe o motivo para solicitar mudanças.", 400)
                github.request_changes(row["Repo"], row["PrNumber"], comment)
                new_status = database.REJECTED
        except GitHubCliError as exc:
            if "own pull request" in str(exc).lower():
                return _fail(
                    "O GitHub não permite que o autor aprove ou peça mudanças no próprio PR. "
                    "O PR precisa ser aberto por outra conta que não seja a autenticada no `gh`.",
                    409,
                )
            return _fail(str(exc), 502)
        repository.save_decision(review_id, new_status, comment)
        return jsonify({"id": review_id, "status": new_status})

    @app.post("/api/reviews/<int:review_id>/approve")
    def approve(review_id: int):
        return decide(review_id, approve=True)

    @app.post("/api/reviews/<int:review_id>/reject")
    def reject(review_id: int):
        return decide(review_id, approve=False)

    @app.post("/api/reviews/<int:review_id>/retry")
    def retry(review_id: int):
        if not repository.requeue(review_id):
            return _fail("Só é possível reprocessar revisões em ERROR.", 409)
        worker.enqueue(review_id)
        return jsonify({"id": review_id, "status": database.PENDING}), 202

    return app
