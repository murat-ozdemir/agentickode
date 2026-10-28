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
        self._client = SimpleNamespace(get=self._get)

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
        elif "/pulls/" in yol:
            n = int(yol.rsplit("/", 1)[-1])
            pr = dict(self.pr.get(n, {}))
            pr["labels"] = [{"name": e} for e in self.etiket.get(n, [])]
            kod, veri = (200, pr) if n in self.pr else (404, {})
        else:
            kod, veri = 404, {}
        return SimpleNamespace(status_code=kod, json=lambda: veri, raise_for_status=_hata(kod))

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


def _hata(kod: int):
    def _f():
        if kod >= 400:
            raise RuntimeError(f"HTTP {kod}")

    return _f
