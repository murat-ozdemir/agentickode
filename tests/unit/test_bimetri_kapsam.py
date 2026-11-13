# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: inceleme/duzeltme kosularina bagli issue ve kapsam kurallari."""

from unittest.mock import AsyncMock, patch

from backend.worker.flow import _bimetri_kapsam as kapsam

_ISSUE = {"title": "Seri numarası doğrulayıcı", "body": "Mevcut koda bağlama."}


def _run(make_task_run, **kw):
    kw.setdefault("git_provider", "gitea")
    return make_task_run(**kw)


class TestKapsamEki:
    async def test_review_gets_issue_from_closes_line(self, make_task_run):
        run = _run(make_task_run, description="Closes #32", task_source_meta={"pr_number": 33})
        oku = AsyncMock(return_value=_ISSUE)
        with patch.object(kapsam, "_issue_oku", new=oku):
            ek = await kapsam.kapsam_eki(run, None, "inceleme")
        assert oku.await_args.args[2] == 32
        assert "## Bağlı issue #32: Seri numarası doğrulayıcı" in ek
        assert "Mevcut koda bağlama." in ek
        assert "### Kapsam dışı" in ek
        assert "Kapsam dışı değişiklik: <dosya> hedef daldaki hâline döndürülmeli" in ek

    async def test_fix_prefers_meta_issue_number(self, make_task_run):
        run = _run(
            make_task_run,
            description="Closes #1",
            default_branch="develop",
            task_source_meta={"issue_number": 7},
        )
        oku = AsyncMock(return_value=_ISSUE)
        with patch.object(kapsam, "_issue_oku", new=oku):
            ek = await kapsam.kapsam_eki(run, None, "duzeltme")
        assert oku.await_args.args[2] == 7
        assert "doğrulanamadı" in ek
        assert "`git checkout origin/develop -- <dosya>`" in ek

    async def test_test_run_gets_issue_and_test_rules(self, make_task_run):
        run = _run(make_task_run, task_source_meta={"issue_number": 32, "review_mode": "test"})
        oku = AsyncMock(return_value=_ISSUE)
        with patch.object(kapsam, "_issue_oku", new=oku):
            ek = await kapsam.kapsam_eki(run, None, "test")
        assert oku.await_args.args[2] == 32
        assert "## Bağlı issue #32: Seri numarası doğrulayıcı" in ek
        assert "testleri koda göre değil bunlara göre yaz" in ek
        assert "Açık soru" in ek

    async def test_fetch_failure_still_adds_rules(self, make_task_run):
        run = _run(make_task_run, task_source_meta={"issue_number": 7})
        with patch.object(kapsam, "_issue_oku", new=AsyncMock(side_effect=RuntimeError("x"))):
            ek = await kapsam.kapsam_eki(run, None, "inceleme")
        assert "Bağlı issue" not in ek
        assert ek.startswith("\n## Kapsam kuralları")

    async def test_no_issue_skips_fetch(self, make_task_run):
        run = _run(make_task_run, description="", task_source_meta={})
        oku = AsyncMock()
        with patch.object(kapsam, "_issue_oku", new=oku):
            await kapsam.kapsam_eki(run, None, "duzeltme")
        oku.assert_not_awaited()


_YORUMLAR = [
    {
        "user": {"login": "agentickode"},
        "body": "## AI Test Raporu\n...",
        "created_at": "2026-11-13T16:00",
    },
    {
        "user": {"login": "mozdemir"},
        "body": "@agentickode review",
        "created_at": "2026-11-13T16:02",
    },
    {
        "user": {"login": "mozdemir"},
        "body": "@agentickode bir de .env.example dosyası oluştur.",
        "created_at": "2026-11-13T16:04",
    },
    {
        "user": {"login": "ayse"},
        "body": "README'de tablo da olsun.",
        "created_at": "2026-11-13T16:05",
    },
]


class TestInsanIstekleri:
    def test_keeps_human_requests_skips_bot_and_bare_commands(self):
        metin = kapsam._insan_istekleri(_YORUMLAR, "agentickode")
        assert ".env.example" in metin
        assert "README'de tablo" in metin
        assert "AI Test Raporu" not in metin
        assert "review" not in metin
        assert metin.index(".env.example") < metin.index("README'de tablo")

    def test_long_comment_is_clipped(self):
        uzun = [{"user": {"login": "x"}, "body": "a" * 5000, "created_at": ""}]
        assert kapsam._insan_istekleri(uzun, "bot").endswith(" [...]")

    async def test_review_prompt_has_requests_and_scope_rule(self, make_task_run):
        run = _run(make_task_run, task_source_meta={"pr_number": 6, "issue_number": 5})
        with (
            patch.object(kapsam, "_issue_oku", new=AsyncMock(return_value=_ISSUE)),
            patch.object(
                kapsam, "_pr_yorumlari", new=AsyncMock(return_value=(_YORUMLAR, "agentickode"))
            ),
        ):
            ek = await kapsam.kapsam_eki(run, None, "inceleme")
        assert "## PR'da insanın istekleri (PR #6" in ek
        assert ".env.example" in ek
        assert (
            ek.index("## Bağlı issue #5")
            < ek.index("## PR'da insanın")
            < ek.index("## Kapsam kuralları")
        )
        assert "onu 'Kapsam dışı değişiklik' sayma" in ek

    async def test_fix_rules_do_not_revert_human_requests(self, make_task_run):
        run = _run(make_task_run, task_source_meta={"pr_number": 6})
        with patch.object(
            kapsam, "_pr_yorumlari", new=AsyncMock(return_value=(_YORUMLAR, "agentickode"))
        ):
            ek = await kapsam.kapsam_eki(run, None, "duzeltme")
        assert ek.startswith("\n\n## PR'da insanın istekleri")
        assert "bir insan istemişse geri alma" in ek

    async def test_comment_fetch_failure_is_ignored(self, make_task_run):
        run = _run(make_task_run, task_source_meta={"pr_number": 6})
        with patch.object(kapsam, "_pr_yorumlari", new=AsyncMock(side_effect=RuntimeError("x"))):
            ek = await kapsam.kapsam_eki(run, None, "test")
        assert ek.startswith("\n## Kapsam kuralları")
