# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi (yama 73): OpenAI taslak uretimi, taslak dosyasi ve mem0'a yukleme.

Python 3.8 ve standart kutuphane (dev-1'de calisir).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

TURLER = ("proje", "modul", "ozellik_gecmisi", "karar", "ders", "tuzak", "calisma")
LLM_TURLERI = ("proje", "modul", "karar", "ders", "tuzak")
KAYNAK = "bootstrap"
SISTEM = """Bir yazılım projesinin kalıcı hafızası için kayıt taslağı hazırlıyorsun. Kayıtları kodlama
ajanları her işin başında okuyacak. Yalnızca verilen belgelere, klasör ağacına ve PR geçmişine
dayan; tahmin yürütme, uydurma. Türkçe yaz; dosya, sınıf ve komut adlarını aynen yaz.

JSON döndür: {"kayitlar": [{"tur": "...", "memory": "..."}]}
- "proje": tam 1 kayıt, en fazla 1200 karakter. Teknoloji yığını ve sürümler, derleme/test
  komutları, klasör düzeni, uyulması gereken kurallar.
- "modul": gerçek her modül ya da ana paket için 1 kayıt (en fazla 15), her biri en fazla 600
  karakter. Yolu, sorumluluğu, önemli sınıfları, bağlı olduğu modüller.
- "karar", "tuzak", "ders": yalnızca belgelerde ya da PR geçmişinde açık dayanağı varsa;
  toplam en fazla 10 kayıt, her biri en fazla 400 karakter, dayanağı kayıtta belirt.
"""


def istek(yontem: str, url: str, basliklar: dict, govde: object = None, zaman: int = 120):
    veri = None if govde is None else json.dumps(govde).encode()
    req = urllib.request.Request(
        url, data=veri, method=yontem, headers={"Content-Type": "application/json", **basliklar}
    )
    try:
        with urllib.request.urlopen(req, timeout=zaman) as r:
            ham = r.read()
    except urllib.error.HTTPError as e:
        ayrinti = e.read()[:300].decode(errors="replace")
        raise RuntimeError(f"{yontem} {url}: HTTP {e.code} {ayrinti}") from None
    return json.loads(ham) if ham else {}


def kullanici_istemi(baglam) -> str:
    parcalar = [f"Proje: {baglam.proje}", "", "## Belgeler"]
    for yol, metin in baglam.belgeler:
        parcalar += [f"### {yol}", metin]
    parcalar += ["", "## Klasör ağacı (klasör/ (dosya sayısı))", baglam.agac, "", "## PR geçmişi"]
    for pr in baglam.prlar:
        parcalar.append(f"- #{pr.no} {pr.tarih} {pr.baslik} | " + "; ".join(pr.commitler))
    return "\n".join(parcalar)


def taslak_uret(anahtar: str, model: str, istem: str) -> tuple[list[dict], dict]:
    yanit = istek(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {anahtar}"},
        {
            "model": model,
            "reasoning_effort": "low",
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 16000,
            "messages": [
                {"role": "system", "content": SISTEM},
                {"role": "user", "content": istem},
            ],
        },
        zaman=600,
    )
    icerik = yanit["choices"][0]["message"].get("content") or "{}"
    kayitlar = []
    for k in json.loads(icerik).get("kayitlar", []):
        metin = " ".join(str(k.get("memory") or "").split())
        if k.get("tur") in LLM_TURLERI and metin:
            kayitlar.append({"tur": k["tur"], "memory": metin})
    return kayitlar, yanit.get("usage") or {}


def taslak_yaz(yol: str, proje: str, kayitlar: list[dict]) -> None:
    with open(yol, "x", encoding="utf-8") as f:
        f.write(json.dumps({"_proje": proje}, ensure_ascii=False) + "\n")
        for k in kayitlar:
            f.write(json.dumps(k, ensure_ascii=False) + "\n")


def taslak_oku(yol: str) -> tuple[str, list[dict]]:
    """Taslagi dogrular; hatali satir varsa satir numarasiyla ValueError."""
    proje, kayitlar = "", []
    with open(yol, encoding="utf-8") as f:
        for no, satir in enumerate(f, 1):
            if not satir.strip():
                continue
            try:
                k = json.loads(satir)
            except json.JSONDecodeError as e:
                raise ValueError(f"{yol}:{no}: JSON hatali ({e.msg})") from None
            if "_proje" in k:
                proje = k["_proje"]
            elif k.get("tur") not in TURLER or not str(k.get("memory") or "").strip():
                raise ValueError(
                    f"{yol}:{no}: 'tur' {TURLER} icinden olmali, 'memory' bos olmamali"
                )
            else:
                kayitlar.append(k)
    return proje, kayitlar


def yukleme_plani(mevcut: list[dict], taslak: list[dict]) -> tuple[list[str], list[dict]]:
    """(silinecek id'ler, eklenecek kayitlar). Onceki ilk doldurma kayitlari yenisiyle degisir;
    'ozellik_gecmisi' silinmez, ayni PR'in kaydi zaten varsa yenisi atlanir."""
    silinecek, var_olan_pr = [], set()
    for m in mevcut:
        meta = m.get("metadata") or {}
        if meta.get("tur") == "ozellik_gecmisi":
            var_olan_pr.add(str(meta.get("pr")))
        elif meta.get("kaynak") == KAYNAK:
            silinecek.append(m["id"])
    eklenecek = [
        k for k in taslak if not (k["tur"] == "ozellik_gecmisi" and str(k.get("pr")) in var_olan_pr)
    ]
    return silinecek, eklenecek


class Mem0:
    def __init__(self, url: str, anahtar: str):
        self.url = url.rstrip("/")
        self.basliklar = {"X-API-Key": anahtar}

    def listele(self, proje: str) -> list[dict]:
        q = urllib.parse.urlencode({"user_id": proje, "top_k": 1000})
        yanit = istek("GET", f"{self.url}/memories?{q}", self.basliklar)
        return yanit.get("results", []) if isinstance(yanit, dict) else yanit

    def ekle(self, proje: str, kayit: dict) -> None:
        meta = {"tur": kayit["tur"], "kaynak": KAYNAK}
        meta.update({a: kayit[a] for a in ("pr", "tarih") if a in kayit})
        govde = {
            "messages": [{"role": "user", "content": kayit["memory"]}],
            "user_id": proje,
            "metadata": meta,
            "infer": False,
        }
        istek("POST", f"{self.url}/memories", self.basliklar, govde)

    def sil(self, kayit_id: str) -> None:
        istek("DELETE", f"{self.url}/memories/{kayit_id}", self.basliklar)
