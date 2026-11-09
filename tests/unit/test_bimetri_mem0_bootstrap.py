# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi (yama 73): mem0 ilk doldurma betigi."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_DIZIN = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIZIN))

import _mem0_api as api  # noqa: E402
import _mem0_topla as topla  # noqa: E402

_spec = importlib.util.spec_from_file_location("mem0_bootstrap", _DIZIN / "mem0-bootstrap.py")
betik = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(betik)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "platform-backend"
    r.mkdir()
    _git(r, "init", "-q", "-b", "master")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "remote", "add", "origin", "https://gitea.example/Bienport-IoT/platform-backend.git")
    (r / "README.md").write_text("Spring Boot 3\ndb.password: gizli123\n")
    (r / "AGENTS.md").write_text("Kurallar")
    (r / "application.yml").write_text("spring.datasource.password=gizli")
    (r / "a" / "b" / "c").mkdir(parents=True)
    (r / "a" / "b" / "c" / "README.md").write_text("cok derin")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "ilk")
    _git(r, "checkout", "-qb", "bug/5-x")
    (r / "src").mkdir()
    (r / "src" / "Byte.java").write_text("class Byte {}")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "fix: bit maskesi (#5)")
    _git(r, "checkout", "-q", "master")
    mesaj = "Merge pull request 'Bit hatası' (#6) from bug/5-x into master\n\nReviewed-on: x"
    _git(r, "merge", "-q", "--no-ff", "bug/5-x", "-m", mesaj)
    return r


class TestTopla:
    def test_collects_docs_tree_and_merged_prs(self, repo):
        b = topla.topla(str(repo), None, 50)
        assert b.proje == "Bienport-IoT/platform-backend"
        yollar = [y for y, _ in b.belgeler]
        assert yollar == ["AGENTS.md", "README.md"]  # application.yml ve derin dosya yok
        assert "gizli123" not in b.belgeler[1][1] and "db.password: ***" in b.belgeler[1][1]
        assert "src/ (1)" in b.agac
        (pr,) = b.prlar
        assert (pr.no, pr.baslik) == (6, "Bit hatası")
        assert pr.commitler == ["fix: bit maskesi (#5)"]
        assert pr.yerler == ["src"]

    def test_feature_history_records_need_no_llm(self, repo):
        (k,) = topla.ozellik_kayitlari(topla.pr_gecmisi(str(repo), 50))
        assert k["tur"] == "ozellik_gecmisi" and k["pr"] == 6
        assert k["memory"].startswith("PR #6 (")
        assert "Commit'ler: fix: bit maskesi (#5)." in k["memory"]

    @pytest.mark.parametrize(
        "url",
        [
            "git@gitea.example:Org/repo.git",
            "https://gitea.example/Org/repo",
            "ssh://g:22/Org/repo.git",
        ],
    )
    def test_project_name_from_remote(self, tmp_path, url):
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "remote", "add", "origin", url)
        assert topla.proje_adi(str(tmp_path)) == "Org/repo"

    def test_git_error_is_readable(self, tmp_path):
        with pytest.raises(RuntimeError, match="git ls-files"):
            topla.git(str(tmp_path / "yok"), "ls-files")


class TestTaslak:
    def test_generate_keeps_only_llm_kinds(self):
        icerik = {
            "kayitlar": [
                {"tur": "proje", "memory": "Java  21\n Maven"},
                {"tur": "ozellik_gecmisi", "memory": "LLM yazmamali"},
                {"tur": "modul", "memory": ""},
            ]
        }
        yanit = {"choices": [{"message": {"content": json.dumps(icerik)}}], "usage": {"x": 1}}
        with patch.object(api, "istek", return_value=yanit) as istek:
            kayitlar, kullanim = api.taslak_uret("k", "gpt-5-mini", "istem")
        assert kayitlar == [{"tur": "proje", "memory": "Java 21 Maven"}]
        assert kullanim == {"x": 1}
        govde = istek.call_args.args[3]
        assert govde["model"] == "gpt-5-mini" and govde["messages"][1]["content"] == "istem"
        assert istek.call_args.args[2] == {"Authorization": "Bearer k"}

    def test_draft_roundtrip_and_no_overwrite(self, tmp_path):
        yol = str(tmp_path / "t.jsonl")
        api.taslak_yaz(yol, "O/r", [{"tur": "karar", "memory": "Gradle değil Maven"}])
        assert "Maven" in Path(yol).read_text(encoding="utf-8")  # Turkce okunur kalir
        assert api.taslak_oku(yol) == ("O/r", [{"tur": "karar", "memory": "Gradle değil Maven"}])
        with pytest.raises(FileExistsError):
            api.taslak_yaz(yol, "O/r", [])

    def test_invalid_draft_line_reports_line_number(self, tmp_path):
        yol = tmp_path / "t.jsonl"
        yol.write_text('{"_proje": "O/r"}\n\n{"tur": "yanlis", "memory": "x"}\n')
        with pytest.raises(ValueError, match=r"t.jsonl:3"):
            api.taslak_oku(str(yol))


class TestYukleme:
    def test_plan_replaces_bootstrap_records_and_skips_known_prs(self):
        mevcut = [
            {"id": "a", "metadata": {"tur": "proje", "kaynak": "bootstrap"}},
            {"id": "b", "metadata": {"tur": "ders", "kaynak": "onay"}},
            {"id": "c", "metadata": {"tur": "ozellik_gecmisi", "kaynak": "merge", "pr": 6}},
        ]
        taslak = [
            {"tur": "proje", "memory": "yeni"},
            {"tur": "ozellik_gecmisi", "memory": "eski PR", "pr": 6},
            {"tur": "ozellik_gecmisi", "memory": "yeni PR", "pr": 7},
        ]
        silinecek, eklenecek = api.yukleme_plani(mevcut, taslak)
        assert silinecek == ["a"]
        assert [k["memory"] for k in eklenecek] == ["yeni", "yeni PR"]

    def test_upload_adds_with_infer_false_then_deletes_old(self, tmp_path, capsys):
        yol = tmp_path / "t.jsonl"
        api.taslak_yaz(str(yol), "O/r", [{"tur": "ozellik_gecmisi", "memory": "m", "pr": 7}])
        cagrilar = []

        def sahte(yontem, url, basliklar, govde=None, zaman=120):
            cagrilar.append((yontem, url, govde))
            eski = [{"id": "e1", "metadata": {"tur": "modul", "kaynak": "bootstrap"}}]
            return {"results": eski} if yontem == "GET" else {}

        with (
            patch.object(api, "istek", side_effect=sahte),
            patch.dict("os.environ", {"MEM0_API_KEY": "k"}),
        ):
            betik.main(["--upload", str(yol), "--mem0-url", "http://m:1", "--yes"])
        assert [c[0] for c in cagrilar] == ["GET", "POST", "DELETE"]
        assert "user_id=O%2Fr" in cagrilar[0][1]
        assert cagrilar[1][2] == {
            "messages": [{"role": "user", "content": "m"}],
            "user_id": "O/r",
            "metadata": {"tur": "ozellik_gecmisi", "kaynak": "bootstrap", "pr": 7},
            "infer": False,
        }
        assert cagrilar[2][1] == "http://m:1/memories/e1"
        assert "1 kayit eklendi, 1 eski kayit silindi" in capsys.readouterr().out


class TestTahmin:
    def test_estimate_lists_files_and_cost_without_calling_openai(self, repo, capsys):
        with patch.object(api, "istek") as istek:
            betik.main(["--repo", str(repo)])
        istek.assert_not_called()
        cikti = capsys.readouterr().out
        assert "Bienport-IoT/platform-backend" in cikti
        assert "  AGENTS.md (" in cikti and "application.yml" not in cikti
        assert "Tahmini maliyet (gpt-5-mini" in cikti and "--generate" in cikti
