import json
import os
import tempfile
import unittest
from dataclasses import replace

from pr_validator import database
from pr_validator.ai_validator import AiResult, AiValidationError, parse_verdict
from pr_validator.app import create_app
from pr_validator.config import Settings
from pr_validator.database import ReviewRepository
from pr_validator.diff_filter import filter_diff
from pr_validator.docs_collector import DocFile
from pr_validator.github_cli import GitHubCliError
from pr_validator.prompt_builder import PromptTooLargeError, build_prompt
from pr_validator.worker import ReviewWorker

SAMPLE_DIFF = """diff --git a/app/service.py b/app/service.py
index 1..2 100644
--- a/app/service.py
+++ b/app/service.py
@@ -1 +1 @@
-x = 1
+x = 2
diff --git a/package-lock.json b/package-lock.json
index 1..2 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1 +1 @@
-a
+b
diff --git a/Data/Migrations/20240101_Init.Designer.cs b/Data/Migrations/20240101_Init.Designer.cs
+generated
diff --git a/logo.png b/logo.png
index 1..2 100644
Binary files a/logo.png and b/logo.png differ
diff --git a/docs/api.md b/docs/api.md
--- a/docs/api.md
+++ b/docs/api.md
@@ -1 +1 @@
-old
+new
"""


def make_settings(db_path: str, **overrides) -> Settings:
    base = Settings(
        host="127.0.0.1", port=5000, db_path=db_path, webhook_secret="", ollama_base_url="http://x",
        model_name="m", num_ctx=32768, output_reserve_tokens=2048, ollama_timeout=5, gh_timeout=5,
        docs_paths=("docs/", "README.md"), doc_extensions=(".md",), max_doc_file_bytes=200_000,
        diff_ignore_patterns=Settings.from_env().diff_ignore_patterns,
    )
    return replace(base, **overrides)


class FakeGithub:
    def __init__(self, diff=SAMPLE_DIFF):
        self.diff = diff
        self.reviews = []
        self.fail_review = False

    def pr_view(self, repo, number):
        return {"title": "T", "body": "B", "baseRefName": "main", "headRefOid": "abc",
                "files": [{"path": "docs/api.md"}, {"path": "app/service.py"}]}

    def pr_diff(self, repo, number):
        return self.diff

    def list_tree(self, repo, ref):
        return [{"path": "docs/api.md", "size": 10}, {"path": "docs/img.png", "size": 10},
                {"path": "README.md", "size": 10}, {"path": "src/notes.md", "size": 10}]

    def read_file(self, repo, path, ref):
        if path == "docs/api.md" and ref == "abc":
            return "NEW API DOC"
        return f"doc {path}@{ref}"

    def approve(self, repo, number, body):
        self._review("approve", repo, number, body)

    def request_changes(self, repo, number, body):
        self._review("request_changes", repo, number, body)

    def _review(self, kind, repo, number, body):
        if self.fail_review:
            raise GitHubCliError("gh pr review falhou: own PR")
        self.reviews.append((kind, repo, number, body))


class DiffFilterTests(unittest.TestCase):
    def test_removes_noise_and_keeps_source_and_docs(self):
        result = filter_diff(SAMPLE_DIFF, make_settings("x").diff_ignore_patterns)
        self.assertEqual([b.path for b in result.blocks], ["app/service.py", "docs/api.md"])
        self.assertEqual({s.path for s in result.skipped},
                         {"package-lock.json", "Data/Migrations/20240101_Init.Designer.cs", "logo.png"})


class PromptTests(unittest.TestCase):
    def test_truncates_diff_explicitly(self):
        blocks = filter_diff(SAMPLE_DIFF, ()).blocks
        big = blocks[0].__class__("big.py", "+" + "x" * 30000 + "\n")
        docs = [DocFile("docs/a.md", "regra", "base")]
        bundle = build_prompt("t", "b", docs, [blocks[0], big, blocks[1]], [], num_ctx=4096, output_reserve=512)
        self.assertEqual(bundle.omitted_diff_files, ["big.py", blocks[1].path])
        self.assertIn("TRUNCADO", bundle.prompt)
        self.assertIn("regra", bundle.prompt)

    def test_docs_too_large_for_context(self):
        docs = [DocFile("docs/a.md", "x" * 60000, "base")]
        with self.assertRaises(PromptTooLargeError):
            build_prompt("t", "b", docs, [], [], num_ctx=8192, output_reserve=1024)


class VerdictTests(unittest.TestCase):
    def test_is_valid_forced_false_when_issues_listed(self):
        verdict = parse_verdict(json.dumps({"isValid": True, "summary": "s", "inconsistencies": ["a"]}))
        self.assertFalse(verdict["isValid"])
        self.assertEqual(verdict["missingDocUpdates"], [])

    def test_invalid_json(self):
        with self.assertRaises(AiValidationError):
            parse_verdict("not json")


class WorkerAndApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(os.path.join(self.tmp.name, "t.sqlite3"))
        self.repo = ReviewRepository(self.settings.db_path)
        self.github = FakeGithub()
        self.prompts = []

        def fake_ai(settings, bundle):
            self.prompts.append(bundle)
            return AiResult({"isValid": False, "summary": "s", "missingDocUpdates": ["d"],
                             "missingCodeUpdates": [], "inconsistencies": []}, 1234)

        self.worker = ReviewWorker(self.settings, self.repo, self.github, ai=fake_ai)
        self.client = create_app(self.settings, self.repo, self.worker, self.github).test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def post_pr(self, **overrides):
        payload = {"repo": "o/r", "prNumber": 7, "title": "t", "author": "dev",
                   "headBranch": "feat", "commitSha": "abc"}
        payload.update(overrides)
        return self.client.post("/api/webhook/pr", json=payload)

    def test_webhook_returns_202_and_pending(self):
        response = self.post_pr()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.repo.get(response.json["id"])["Status"], database.PENDING)

    def test_legacy_route_and_validation(self):
        self.assertEqual(self.client.post("/api/pr/validate", json={"repo": "o/r", "prNumber": 1}).status_code, 202)
        self.assertEqual(self.post_pr(repo="bad repo; rm").status_code, 400)
        self.assertEqual(self.post_pr(prNumber="x").status_code, 400)

    def test_webhook_secret(self):
        settings = replace(self.settings, webhook_secret="s3")
        client = create_app(settings, self.repo, self.worker, self.github).test_client()
        body = {"repo": "o/r", "prNumber": 1}
        self.assertEqual(client.post("/api/webhook/pr", json=body).status_code, 401)
        self.assertEqual(client.post("/api/webhook/pr", json=body, headers={"X-Webhook-Secret": "s3"}).status_code, 202)

    def test_csrf_and_host_guards(self):
        review_id = self.post_pr().json["id"]
        self.assertEqual(self.client.post(f"/api/reviews/{review_id}/approve", data="x",
                                          content_type="text/plain").status_code, 415)
        self.assertEqual(self.client.get("/api/reviews", headers={"Host": "evil.com"}).status_code, 403)

    def test_full_flow_with_docs_overlay_and_filter(self):
        review_id = self.post_pr().json["id"]
        self.worker.process(review_id)
        row = self.repo.get(review_id)
        self.assertEqual(row["Status"], database.WAITING_APPROVAL)
        verdict = json.loads(row["AiVerdictJson"])
        self.assertFalse(verdict["isValid"])
        self.assertEqual(verdict["meta"]["docFiles"], ["README.md", "docs/api.md"])
        self.assertIn("NEW API DOC", self.prompts[0].prompt)       # versão do PR sobrepõe a da base
        self.assertNotIn("package-lock", row["DiffContent"])        # ruído removido do diff
        self.assertIn("package-lock.json", self.prompts[0].prompt)  # mas citado como ignorado

    def test_synchronize_resets_and_discards_stale_result(self):
        review_id = self.post_pr().json["id"]
        self.assertTrue(self.repo.claim_for_processing(review_id))
        same_id = self.post_pr(commitSha="def").json["id"]          # novo push durante o processamento
        self.assertEqual(same_id, review_id)
        self.assertFalse(self.repo.save_result(review_id, "abc", "d", "{}"))
        self.assertEqual(self.repo.get(review_id)["CommitSha"], "def")
        self.assertEqual(self.repo.get(review_id)["Status"], database.PENDING)

    def test_error_status_and_retry(self):
        review_id = self.post_pr().json["id"]
        self.github.pr_diff = lambda *a: (_ for _ in ()).throw(GitHubCliError("boom"))
        self.worker.process(review_id)
        self.assertEqual(self.repo.get(review_id)["Status"], database.ERROR)
        self.assertEqual(self.client.post(f"/api/reviews/{review_id}/retry", json={}).status_code, 202)
        self.assertEqual(self.repo.get(review_id)["Status"], database.PENDING)

    def test_approve_and_reject(self):
        review_id = self.post_pr().json["id"]
        self.assertEqual(self.client.post(f"/api/reviews/{review_id}/approve", json={}).status_code, 409)
        self.worker.process(review_id)
        self.assertEqual(self.client.post(f"/api/reviews/{review_id}/reject", json={"comment": " "}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/reviews/{review_id}/reject", json={"comment": "ajuste"}).status_code, 200)
        self.assertEqual(self.github.reviews[-1], ("request_changes", "o/r", 7, "ajuste"))
        self.assertEqual(self.repo.get(review_id)["Status"], database.REJECTED)

    def test_approve_failure_keeps_status(self):
        review_id = self.post_pr().json["id"]
        self.worker.process(review_id)
        self.github.fail_review = True
        response = self.client.post(f"/api/reviews/{review_id}/approve", json={})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.repo.get(review_id)["Status"], database.WAITING_APPROVAL)


if __name__ == "__main__":
    unittest.main()

