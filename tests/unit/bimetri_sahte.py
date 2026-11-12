# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi testleri icin bellek ici sahte Gitea saglayicisi."""

from types import SimpleNamespace

BASE = "https://gitea.test"
API = f"{BASE}/api/v1"


class SahteGitea:
    """Etiketler, yorumlar ve PR'lar bellekte; GET yanitlari `yanitlar` ile ezilebilir."""

    def __init__(self, bot: str = "agentickode"):
        self._base_url = BASE
        self.bot = bot
        self.etiket: dict[int, list[str]] = {}
        self.yorum: dict[int, list[str]] = {}
        self.pr: dict[int, dict] = {}
        self.durum: dict[int, str] = {}
        self.yanitlar: dict[str, tuple[int, object]] = {}
        self.dosya: dict[int, list[str]] = {}
        self.ci_durum: dict[str, list[str]] = {}
        self.dispatch: list[tuple[str, dict]] = []
        self.dispatch_kodu = 204
        self.workflow_var = True
        self._client = SimpleNamespace(get=self._get, post=self._post)

    def _headers(self) -> dict:
        return {}

    async def _get(self, url: str, **_kw):
        yol = url.removeprefix(API)
        if yol in self.yanitlar:
            kod, veri = self.yanitlar[yol]
        elif yol == "/user":
            kod, veri = 200, {"login": self.bot}
        elif yol.endswith("/labels"):
            n = int(yol.split("/")[-2])
            kod, veri = 200, [{"name": e} for e in self.etiket.get(n, [])]
        elif yol.endswith("/comments"):
            n = int(yol.split("/")[-2])
            kod, veri = 200, [{"body": b} for b in self.yorum.get(n, [])]
        elif yol.endswith("/files"):
            kod, veri = 200, [{"filename": d} for d in self.dosya.get(int(yol.split("/")[-2]), [])]
        elif "/contents/.gitea/workflows/" in yol:
            kod, veri = (200, {}) if self.workflow_var else (404, {})
        elif yol.endswith("/status"):
            sha = yol.split("/")[-2]
            kod, veri = 200, {"statuses": [{"context": c} for c in self.ci_durum.get(sha, [])]}
        elif "/pulls/" in yol:
            n = int(yol.rsplit("/", 1)[-1])
            pr = dict(self.pr.get(n, {}))
            pr["labels"] = [{"name": e} for e in self.etiket.get(n, [])]
            kod, veri = (200, pr) if n in self.pr else (404, {})
        else:
            kod, veri = 404, {}
        metin = veri if isinstance(veri, str) else ""
        return SimpleNamespace(
            status_code=kod, json=lambda: veri, text=metin, raise_for_status=_hata(kod)
        )

    async def _post(self, url: str, json: dict | None = None, **_kw):
        self.dispatch.append((url.removeprefix(API), json or {}))
        return SimpleNamespace(status_code=self.dispatch_kodu)

    async def add_label(self, rp: str, n: int, ad: str) -> None:
        if ad not in self.etiket.setdefault(n, []):
            self.etiket[n].append(ad)

    async def remove_label(self, rp: str, n: int, ad: str) -> None:
        if ad in self.etiket.get(n, []):
            self.etiket[n].remove(ad)

    async def set_status_label(self, rp: str, n: int, ad: str) -> None:
        self.durum[n] = ad
        self.etiket[n] = [e for e in self.etiket.get(n, []) if not e.startswith("status/")] + [ad]

    async def post_pr_comment(self, rp: str, n: int, govde: str) -> None:
        self.yorum.setdefault(n, []).append(govde)


class SahteGit:
    """RemoteGitOps yerine: duzeltme kosusunun sordugu git komutlarina sabit yanit."""

    def __init__(self, ahead: str = "1", diff: str = "", mvnw: bool = True):
        self.yanit = {
            "status": "",
            "rev-list": ahead,
            "diff": diff,
            "ls-files": "mvnw" if mvnw else "",
        }
        self.komutlar: list[list[str]] = []

    async def run_git(self, args: list[str], cwd: str | None = None):
        self.komutlar.append(args)
        return SimpleNamespace(stdout=self.yanit.get(args[0], ""))


def _hata(kod: int):
    def _f():
        if kod >= 400:
            raise RuntimeError(f"HTTP {kod}")

    return _f
