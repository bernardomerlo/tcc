"""Ponto de entrada: `python -m pr_validator`."""
import logging
import shutil

from .app import create_app
from .config import Settings
from .database import ReviewRepository
from .github_cli import GitHubCli
from .worker import ReviewWorker


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    log = logging.getLogger("pr_validator")

    if shutil.which("gh") is None:
        log.warning("GitHub CLI (`gh`) não encontrado no PATH: instale e rode `gh auth login`.")
    if not settings.webhook_secret:
        log.warning("PR_VALIDATOR_WEBHOOK_SECRET não definido: o webhook aceitará qualquer POST local.")
    if settings.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Servidor exposto em %s: o dashboard não tem autenticação.", settings.host)

    repository = ReviewRepository(settings.db_path)
    github = GitHubCli(timeout=settings.gh_timeout)
    worker = ReviewWorker(settings, repository, github)
    worker.start()

    app = create_app(settings, repository, worker, github)
    log.info("Dashboard em http://%s:%s (modelo %s, num_ctx=%s)",
             settings.host, settings.port, settings.model_name, settings.num_ctx)
    app.run(host=settings.host, port=settings.port, threaded=True)


if __name__ == "__main__":
    main()

