# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi (yama 73): mem0 ilk doldurma icin repodan bilgi toplama.

Yalnizca git'te izlenen belge ve derleme dosyalari okunur; parola/anahtar gorunumlu satirlarin
degeri maskelenir. Merge edilmis PR'lardan LLM'siz 'ozellik_gecmisi' kayitlari cikar.
Python 3.8 ve standart kutuphane (dev-1'de calisir).
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

# Oncelik sirasiyla; derinlik: en fazla 2 klasor altinda
BELGE_DESENLERI = (
    "agents.md",
    "claude.md",
    "readme*",
    "contributing*",
    "architecture*",
    "pom.xml",
    "build.gradle*",
    "settings.gradle*",
    "package.json",
    "pyproject.toml",
    "go.mod",
    "cargo.toml",
    "makefile",
    "dockerfile",
    "docker-compose*.yml",
)
DOSYA_SINIRI = 15_000
BELGE_TOPLAM = 150_000
AGAC_SATIR = 400
_GIZLI = re.compile(
    r"(?i)\b([\w.-]*(?:password|passwd|secret|token|api[_-]?key)[\w.-]*\s*[:=]\s*)(\S+)"
)
_MERGE = re.compile(r"^Merge pull request '(?P<baslik>.+)' \(#(?P<no>\d+)\)")
_SQUASH = re.compile(r"^(?P<baslik>.+?) \(#(?P<no>\d+)\)$")


@dataclass
class PR:
    no: int
    tarih: str
    baslik: str
    commitler: list[str] = field(default_factory=list)
    yerler: list[str] = field(default_factory=list)


@dataclass
class Baglam:
    proje: str
    belgeler: list[tuple[str, str]]
    agac: str
    prlar: list[PR]


def git(repo: str, *args: str) -> str:
    r = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", repo, *args], capture_output=True, text=True
    )
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def proje_adi(repo: str) -> str:
    """origin adresinden 'sahip/repo' (yama 72'deki user_id ile ayni)."""
    url = git(repo, "remote", "get-url", "origin").strip()
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise ValueError(f"origin adresinden proje adi cikmadi: {url}")
    return f"{m.group(1)}/{m.group(2)}"


def maskele(metin: str) -> str:
    return _GIZLI.sub(lambda m: m.group(1) + "***", metin)


def _belge_sirasi(yol: str) -> int | None:
    p = PurePosixPath(yol)
    if len(p.parts) > 3:
        return None
    ad = p.name.lower()
    for i, desen in enumerate(BELGE_DESENLERI):
        if fnmatch.fnmatch(ad, desen):
            return i
    return None


def belgeleri_topla(repo: str, dosyalar: list[str]) -> list[tuple[str, str]]:
    adaylar = sorted(
        (s, yol.count("/"), yol) for yol in dosyalar if (s := _belge_sirasi(yol)) is not None
    )
    belgeler, toplam = [], 0
    for _, _, yol in adaylar:
        try:
            with open(f"{repo}/{yol}", encoding="utf-8", errors="replace") as f:
                metin = maskele(f.read(DOSYA_SINIRI))
        except OSError:
            continue
        if toplam + len(metin) > BELGE_TOPLAM:
            break
        belgeler.append((yol, metin))
        toplam += len(metin)
    return belgeler


def agac(dosyalar: list[str]) -> str:
    """Klasor -> altindaki dosya sayisi; en fazla AGAC_SATIR satir."""
    sayac: Counter[str] = Counter()
    for yol in dosyalar:
        parcalar = yol.split("/")[:-1]
        for i in range(1, len(parcalar) + 1):
            sayac["/".join(parcalar[:i])] += 1
    satirlar = [f"{k}/ ({n})" for k, n in sorted(sayac.items())]
    return "\n".join(satirlar[:AGAC_SATIR])


def _yerler(repo: str, sha: str) -> list[str]:
    try:
        degisen = git(repo, "diff", "--name-only", f"{sha}^1", sha).split()
    except RuntimeError:
        return []
    klasorler = Counter(str(PurePosixPath(y).parent) for y in degisen)
    return [k for k, _ in klasorler.most_common(5)]


def pr_gecmisi(repo: str, sinir: int) -> list[PR]:
    """Ana daldaki merge commit'lerinden PR listesi (en yenisi once)."""
    ham = git(
        repo,
        "log",
        "--first-parent",
        f"-n{sinir}",
        "--date=short",
        "--format=%H%x1f%P%x1f%ad%x1f%s",
    )
    prlar = []
    for satir in ham.splitlines():
        sha, ebeveyn, tarih, konu = satir.split("\x1f", 3)
        m = _MERGE.match(konu) or _SQUASH.match(konu)
        if not m:
            continue
        pr = PR(int(m.group("no")), tarih, m.group("baslik"), yerler=_yerler(repo, sha))
        ebeveynler = ebeveyn.split()
        if len(ebeveynler) > 1:
            pr.commitler = git(
                repo, "log", "--format=%s", "-n5", f"{ebeveynler[0]}..{ebeveynler[1]}"
            ).splitlines()
        prlar.append(pr)
    return prlar


def topla(repo: str, proje: str | None, pr_siniri: int) -> Baglam:
    dosyalar = git(repo, "ls-files").splitlines()
    return Baglam(
        proje or proje_adi(repo),
        belgeleri_topla(repo, dosyalar),
        agac(dosyalar),
        pr_gecmisi(repo, pr_siniri),
    )


def ozellik_kayitlari(prlar: list[PR]) -> list[dict]:
    kayitlar = []
    for pr in prlar:
        metin = f"PR #{pr.no} ({pr.tarih}): {pr.baslik}."
        if pr.commitler:
            metin += " Commit'ler: " + "; ".join(pr.commitler) + "."
        if pr.yerler:
            metin += " Değişen yerler: " + ", ".join(pr.yerler) + "."
        kayitlar.append(
            {"tur": "ozellik_gecmisi", "memory": metin[:800], "pr": pr.no, "tarih": pr.tarih}
        )
    return kayitlar
