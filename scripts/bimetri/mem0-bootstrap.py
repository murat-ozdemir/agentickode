#!/usr/bin/env python3
# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""mem0-bootstrap.py — bimetri yamasi (yama 73): projenin mem0 hafizasinin ilk doldurulmasi.

Uc adim, her biri ayri calistirilir:
  1. mem0-bootstrap.py --repo <klon>             OpenAI'a gidecekleri ve maliyet tahminini yazar.
  2. mem0-bootstrap.py --repo <klon> --generate  Taslak JSONL yazar (gpt-5-mini); sen duzeltirsin.
  3. mem0-bootstrap.py --upload <taslak.jsonl>   Taslagi mem0'a yazar (infer=False).
Anahtarlar ortam degiskeninden, yoksa AgenticKode kokundeki .env.mem0 (OPENAI_API_KEY) ve
.env (MEM0_API_KEY, MEM0_BIND) dosyalarindan, o da yoksa gizli istemle alinir.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _mem0_api as api
import _mem0_topla as topla

KOK = Path(__file__).resolve().parents[2]
CIKTI_TAHMINI = 6000  # gorunur + akil yurutme token'i (tipik)
CIKTI_SINIRI = 16000


def env_degeri(ad: str, dosya: str) -> str:
    try:
        satirlar = (KOK / dosya).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    degerler = [s.split("=", 1)[1] for s in satirlar if s.startswith(f"{ad}=")]
    return degerler[-1].strip().strip("\"'") if degerler else ""


def anahtar(ad: str, dosya: str) -> str:
    return os.environ.get(ad) or env_degeri(ad, dosya) or getpass.getpass(f"{ad}: ")


def maliyet(girdi: int, cikti: int, a: argparse.Namespace) -> float:
    return (girdi * a.input_price + cikti * a.output_price) / 1_000_000


def tahmin(b: topla.Baglam, istem: str, a: argparse.Namespace) -> None:
    print(f"Proje (mem0 user_id): {b.proje}")
    print(f"OpenAI'a gidecek dosyalar ({len(b.belgeler)}; parola/anahtar degerleri maskelendi):")
    for yol, metin in b.belgeler:
        print(f"  {yol} ({len(metin):,} karakter)")
    print(f"Klasor agaci: {b.agac.count(chr(10)) + 1} satir; merge edilmis PR: {len(b.prlar)}")
    print(f"  (PR'lardan {len(b.prlar)} 'ozellik_gecmisi' kaydi LLM'siz yazilir)")
    girdi = len(istem) // 3 + len(api.SISTEM) // 3
    print(f"Tahmini token: girdi ~{girdi:,}, cikti ~{CIKTI_TAHMINI:,} (en fazla {CIKTI_SINIRI:,})")
    print(
        f"Tahmini maliyet ({a.model}, 1M token ${a.input_price} girdi / ${a.output_price} cikti): "
        f"~${maliyet(girdi, CIKTI_TAHMINI, a):.3f} (en fazla ~${maliyet(girdi, CIKTI_SINIRI, a):.3f})"
    )
    print("Fiyat degistiyse --input-price/--output-price ile ver. Yuklemede kayit basina bir")
    print("embedding cagrisi daha yapilir (ihmal edilebilir).")
    print("Taslagi uretmek icin ayni komutu --generate ile calistir.")


def uret(b: topla.Baglam, istem: str, a: argparse.Namespace) -> None:
    cikti = a.out or f"mem0-taslak-{b.proje.replace('/', '-')}.jsonl"
    if Path(cikti).exists():
        sys.exit(f"HATA: {cikti} zaten var; duzelttigin taslak olabilir. Tasi ya da --out ver.")
    kayitlar, kullanim = api.taslak_uret(anahtar("OPENAI_API_KEY", ".env.mem0"), a.model, istem)
    kayitlar += topla.ozellik_kayitlari(b.prlar)
    api.taslak_yaz(cikti, b.proje, kayitlar)
    sayilar = {t: sum(k["tur"] == t for k in kayitlar) for t in api.TURLER}
    print(f"Taslak: {cikti}")
    print("  " + ", ".join(f"{t} {n}" for t, n in sayilar.items() if n))
    girdi, cik = kullanim.get("prompt_tokens", 0), kullanim.get("completion_tokens", 0)
    print(f"Gercek kullanim: girdi {girdi:,}, cikti {cik:,} token, ~${maliyet(girdi, cik, a):.3f}")
    print("Dosyayi oku; istemedigin satiri sil, yanlisi duzelt. Sonra: --upload " + cikti)


def yukle(a: argparse.Namespace) -> None:
    proje, taslak = api.taslak_oku(a.upload)
    proje = a.project or proje
    if not proje:
        sys.exit("HATA: taslakta _proje satiri yok; --project ver.")
    bind = env_degeri("MEM0_BIND", ".env") or "127.0.0.1"
    mem0 = api.Mem0(a.mem0_url or f"http://{bind}:8890", anahtar("MEM0_API_KEY", ".env"))
    silinecek, eklenecek = api.yukleme_plani(mem0.listele(proje), taslak)
    print(f"Proje: {proje}; mem0: {mem0.url}")
    print(f"Eklenecek: {len(eklenecek)} (atlanan, zaten var: {len(taslak) - len(eklenecek)})")
    print(f"Silinecek eski ilk doldurma kaydi: {len(silinecek)} (ozellik_gecmisi silinmez)")
    if not a.yes and input("Devam edilsin mi? [e/H] ").strip().lower() not in ("e", "evet"):
        sys.exit("Iptal edildi.")
    for i, k in enumerate(eklenecek, 1):
        mem0.ekle(proje, k)
        print(f"\r  eklendi {i}/{len(eklenecek)}", end="", flush=True)
    print()
    for kayit_id in silinecek:
        mem0.sil(kayit_id)
    print(f"Tamam: {len(eklenecek)} kayit eklendi, {len(silinecek)} eski kayit silindi.")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="mem0 proje hafizasinin ilk doldurulmasi (yama 73)")
    p.add_argument("--repo", help="hedef projenin yerel git klonu")
    p.add_argument("--project", help="sahip/repo (varsayilan: origin adresinden)")
    p.add_argument("--generate", action="store_true", help="OpenAI ile taslak uret")
    p.add_argument("--upload", metavar="TASLAK", help="duzeltilmis taslagi mem0'a yukle")
    p.add_argument("--out", help="taslak dosyasi (varsayilan: mem0-taslak-<proje>.jsonl)")
    p.add_argument("--mem0-url", help="varsayilan: http://<MEM0_BIND>:8890")
    p.add_argument("--max-prs", type=int, default=200)
    p.add_argument("--model", default="gpt-5-mini")
    p.add_argument("--input-price", type=float, default=0.25, help="$ / 1M girdi token")
    p.add_argument("--output-price", type=float, default=2.0, help="$ / 1M cikti token")
    p.add_argument("--yes", action="store_true", help="yuklemede onay sorma")
    a = p.parse_args(argv)
    try:
        if a.upload:
            return yukle(a)
        if not a.repo:
            p.error("--repo ya da --upload gerekli")
        b = topla.topla(a.repo, a.project, a.max_prs)
        istem = api.kullanici_istemi(b)
        (uret if a.generate else tahmin)(b, istem, a)
    except (ValueError, RuntimeError, OSError) as e:
        sys.exit(f"HATA: {e}")


if __name__ == "__main__":
    main()
