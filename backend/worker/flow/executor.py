# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""Flow-prompt executor (ADR-009).

The run path: workspace setup (task-mode only) -> fetch the flow's data -> a
SINGLE agent call -> finalization. The agent's response is the run outcome,
stored on ``task_runs.coding_results``.

This is the only execution path: ``pipeline.execute_pipeline`` resolves the run's
flow prompt (``pr_review`` for review runs, ``implement`` otherwise) and delegates
here.
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun
from backend.repositories.flow_prompt_repo import FlowPromptRepository
from backend.services.container import ServiceContainer
from backend.worker.broadcaster import broadcaster
from backend.worker.flow._bimetri_kapsam import kapsam_eki
from backend.worker.flow.data_sources import fetch_flow_data
from backend.worker.phases._bimetri_oto import bekletildi_mi
from backend.worker.phases._helpers import (
    close_run_session,
    ensure_agent_ready,
    get_workspace_server_id,
)
from backend.worker.steps.agent_step import run_agent_step

logger = logging.getLogger("agentickode.flow.executor")


# bimetri yamasi: ajan cagrisini agent_invocations'a ekle (dashboard); commit'i kosu yapar, hata kosuyu bozmaz
def _bimetri_cagri_kaydi(run, session, agent, phase, t0, result, exc) -> None:
    try:
        from backend.models import AgentInvocation

        result = result or {}
        resp = result.get("response")
        rd = resp if isinstance(resp, dict) else {}
        out = rd.get("output") if rd else resp
        usage = result.get("usage") or {}
        rc = rd.get("exit_code")
        t1 = datetime.now(UTC)
        session.add(
            AgentInvocation(
                run_id=run.id,
                workspace_server_id=run.workspace_server_id,
                agent_name=str(agent or result.get("agent") or "?"),
                phase_name=phase,
                prompt_chars=len(result.get("prompt") or ""),
                response_chars=len(out) if isinstance(out, str) else 0,
                exit_code=rc,
                files_changed=rd.get("files_changed"),
                duration_seconds=round((t1 - t0).total_seconds(), 1),
                estimated_tokens_in=usage.get("input_tokens"),
                estimated_tokens_out=usage.get("output_tokens"),
                estimated_cost_usd=usage.get("cost_usd"),
                status="failed" if exc is not None or rc not in (None, 0) else "success",
                error_message=str(exc)[:2000] if exc is not None else None,
                started_at=t0,
                completed_at=t1,
                session_id=result.get("session_id"),
                metadata_={"model": result.get("model"), "bimetri": True},
            )
        )
    except Exception:
        logger.warning("agent_invocations kaydi eklenemedi", exc_info=True)


def _compose_prompt(prompt: str, data: dict[str, Any]) -> str:
    """Append the fetched data as a context block the agent can read."""
    if not data:
        return prompt
    block = json.dumps(data, indent=2, default=str)
    return f"{prompt}\n\n## Context (fetched by AgenticKode)\n```json\n{block}\n```"


# bimetri yamasi: issue'nun ve (biliniyorsa) PR'in durum etiketi (yalnizca Gitea); hata kosuyu bozmaz
async def _bimetri_durum(run: TaskRun, session: AsyncSession, label: str | None) -> None:
    import re

    meta = run.task_source_meta or {}
    if run.git_provider != "gitea":
        return
    targets = []
    if meta.get("issue_number"):
        targets.append(("Issue", int(meta["issue_number"])))
    m = re.search(r"/pulls/(\d+)", run.pr_url or meta.get("pr_url") or "")
    pr_no = meta.get("pr_number") or (m.group(1) if m else None)
    if pr_no:
        targets.append(("PR", int(pr_no)))
    if not targets:
        return
    try:
        from backend.services.git import get_git_provider
        from backend.services.http_client import get_http_client
        from backend.worker.phases._helpers import get_project_token

        provider = get_git_provider(
            "gitea", get_http_client(), access_token=await get_project_token(run, session)
        )
    except Exception as exc:
        await broadcaster.log(run.id, f"Durum etiketi ayarlanamadi: {exc}", level="warning", phase="agent")
        return
    for kind, n in targets:
        try:
            await provider.set_status_label(f"{run.repo_owner}/{run.repo_name}", n, label)
            await broadcaster.log(run.id, f"{kind} #{n} durumu: {label or 'temizlendi'}", phase="agent")
        except Exception as exc:
            await broadcaster.log(
                run.id, f"{kind} #{n} durum etiketi ayarlanamadi: {exc}", level="warning", phase="agent"
            )


async def _run_phase(name: str, run: TaskRun, session: AsyncSession, services: ServiceContainer):
    """Run a builtin phase module (workspace_setup / init / finalization)."""
    from backend.worker.pipeline import _get_phase_module

    module = _get_phase_module(name)
    if module is None:
        logger.warning("Flow executor: phase module %r not found — skipping", name)
        return
    run.current_phase = name
    await broadcaster.event(run.id, "phase_changed", {"phase": name})
    await module.run(run, session, services, None)


async def execute_flow_prompt(
    run: TaskRun, session: AsyncSession, services: ServiceContainer
) -> None:
    """Execute a run via its bound flow prompt (single agent call)."""
    flow = await FlowPromptRepository(session).get_by_id(run.flow_prompt_id)
    if flow is None:
        run.status = "failed"
        run.error_message = f"flow_prompt_id={run.flow_prompt_id} not found"
        run.completed_at = datetime.now(UTC)
        await session.commit()
        await broadcaster.event(
            run.id, "run_failed", {"run_id": run.id, "error": run.error_message}
        )
        return

    run.status = "running"
    run.started_at = run.started_at or datetime.now(UTC)
    # Resolve a workspace server (the agent CLI needs one to run on) — mirrors the
    # legacy phases, which use get_workspace_server_id rather than the raw column.
    # Falls back to the project's assigned server (e.g. the local platform server).
    if not run.workspace_server_id:
        run.workspace_server_id = await get_workspace_server_id(run, session)
    await session.commit()
    await broadcaster.event(
        run.id,
        "run_started",
        {"status": "running", "title": run.title, "project_id": run.project_id, "flow": flow.name},
    )

    try:
        # bimetri yamasi: kod kosusu basladi, issue (duzeltmede PR de) status/in-progress
        if flow.flow_type != "pr_review":
            await _bimetri_durum(run, session, "status/in-progress")
        # Task-mode flows need a checked-out workspace; generate-mode (e.g. PR
        # review on a fetched diff) skips setup entirely.
        if flow.agent_mode == "task":
            await _run_phase("workspace_setup", run, session, services)
            await _run_phase("init", run, session, services)

        data = await fetch_flow_data(run, session, services, flow)
        prompt = _compose_prompt(flow.prompt, data)
        # bimetri yamasi: Turkce ve PR'i platform acar (sistem flow prompt'lari Ingilizce, DB'de, arayuzden duzenlenmiyor)
        if flow.flow_type == "pr_review":
            prompt += (
                "\n\n## Ek kurallar (yukarıdakilerden önceliklidir)\n"
                "- İncelemeni Türkçe yaz; Türkçe karakterleri (ç, ğ, ı, ö, ş, ü) kullan.\n"
                "- Biçim: önce 1-2 cümlelik özet; sonra '### Bulgular' başlığı altında her bulgu için "
                "önem (kritik/orta/düşük), dosya:satır ve kısa açıklama; sonra '### Öneriler'. "
                "Bulgu yoksa bunu açıkça yaz.\n"
                "- En sona tek satır: '**Sonuç:** Birleştirilebilir' ya da '**Sonuç:** Değişiklik gerekli'.\n"
                "- Kod değiştirme.\n"
            )
            prompt += await kapsam_eki(run, session, "inceleme")
        # bimetri yamasi: test ajani kurallari (yalnizca test kodu, calistir, sabit sonuc satiri)
        elif (run.task_source_meta or {}).get("review_mode") == "test":
            prompt += (
                "\n\n## Test ajanı kuralları (yukarıdakilerden önceliklidir)\n"
                "- Sen test ajanısın. Görevin bu PR'daki değişikliği test etmek; uygulama kodunu düzeltmek değil.\n"
                "- Repo kökündeki AGENTS.md'yi oku. 'Test yazma' yasağı sana uygulanmaz; diğer kuralları geçerli.\n"
                "- Yalnızca test klasörlerinde (`src/test/**`) dosya ekle ya da değiştir. Başka hiçbir dosyaya "
                "dokunma, pom.xml'e de. Eksik bağımlılık ya da ayar varsa raporda belirt.\n"
                "- Mevcut testleri silme; `@Disabled` ya da `@Ignore` ekleme.\n"
                "- Değişikliğe göre birim testleri yaz (JUnit 5, Mockito; `*Test.java`). Veritabanına dokunan kod "
                "için Testcontainers ile entegrasyon testi yaz (`*IT.java`); repodaki örnek IT'nin kurduğu yapıyı kullan.\n"
                "- JDK'yı `mvn`/`mvnw` repo kökündeki `.sdkmanrc`'ye göre kendisi seçer; "
                "`sdk` komutunu çalıştırma, `JAVA_HOME`'u değiştirme.\n"
                "- Testleri çalıştır: `mvnw` varsa `sh mvnw -q verify`, yoksa `mvn -q verify`. Yalnızca ilgili "
                "modül için `-pl <modül> -am` kullanabilirsin.\n"
                "- Bir test kalırsa nedenini araştır. Hata uygulama kodundaysa testi değiştirme, raporla. "
                "Hata senin testindeyse testini düzelt.\n"
                "- Commit et: Türkçe, tek satır, `test: ...` önekiyle. Push etme.\n"
                "- Son mesajın PR'a test raporu olarak yazılır; Türkçe yaz (ç, ğ, ı, ö, ş, ü): yazdığın testler, "
                "çalıştırdığın komut, geçen/kalan sayısı, kalan her test için beklenen, gerçekleşen ve olası neden.\n"
                "- Son mesajının son satırı tam olarak şunlardan biri olsun: '**Sonuç:** Testler geçti', "
                "'**Sonuç:** Testler kaldı', '**Sonuç:** Test edilemedi'. Ortam yüzünden (Docker, JDK, "
                "bağımlılık indirme, test veritabanı) çalıştıramadıysan 'Test edilemedi'.\n"
            )
        else:
            prompt += (
                "\n\n## Ek kurallar (yukarıdakilerden önceliklidir)\n"
                "- Repo kökündeki AGENTS.md dosyasındaki kurallara uy.\n"
                "- JDK'yı `mvn`/`mvnw` repo kökündeki `.sdkmanrc`'ye göre kendisi seçer; "
                "`sdk` komutunu çalıştırma, `JAVA_HOME`'u değiştirme.\n"
                "- Push etme, PR açma; PR'ı platform açar. Son mesajında PR'dan söz etme.\n"
                "- Son mesajını Türkçe yaz (ç, ğ, ı, ö, ş, ü); bu mesaj PR açıklamasına konur.\n"
            )
            if (run.task_source_meta or {}).get("review_mode") == "fix":
                prompt += await kapsam_eki(run, session, "duzeltme")

        run.current_phase = "agent"
        await broadcaster.event(run.id, "phase_changed", {"phase": "agent"})
        await broadcaster.log(run.id, f"Running flow prompt: {flow.name}", phase="agent")

        # Ensure the CLI agent is installed for the run-as (worker) user before
        # invoking it — parity with the legacy coding/reviewing phases. No-op for
        # root / non-CLI adapters; installs into the worker user's home otherwise.
        # bimetri yamasi: etiketle ajan (agent/codex) ve model (difficulty/hard) secimi
        from backend.services.adapters.cli_commands import AGENT_COMMANDS

        # bimetri yamasi: etiketler kosu basinda Gitea'dan guncel okunur (once PR, sonra issue, en son webhook yuku)
        _canli: list = []
        _m = run.task_source_meta or {}
        if run.git_provider == "gitea":
            try:
                from backend.services.git import get_git_provider as _ggp
                from backend.services.http_client import get_http_client as _ghc
                from backend.worker.phases._helpers import get_project_token as _gpt

                _gp = _ggp("gitea", _ghc(), access_token=await _gpt(run, session))
                for _n in (_m.get("pr_number"), _m.get("issue_number")):
                    if not _n:
                        continue
                    _r = await _gp._client.get(
                        f"{_gp._base_url}/api/v1/repos/{run.repo_owner}/{run.repo_name}/issues/{int(_n)}/labels",
                        headers=_gp._headers(),
                        timeout=30.0,
                    )
                    if _r.status_code == 200:
                        _canli += [la.get("name", "") for la in _r.json()]
            except Exception as exc:
                await broadcaster.log(
                    run.id, f"Guncel etiketler okunamadi, webhook'takiler kullaniliyor: {exc}",
                    level="warning", phase="agent",
                )
        labels = [
            str(lbl).strip().lower().replace("ı", "i")
            for lbl in _canli + list(_m.get("labels") or [])
        ]
        agent_name = next((lbl.split("/", 1)[1] for lbl in labels if lbl.startswith("agent/")), None)
        # bimetri yamasi: test kosusunda ajan test-agent/ etiketinden, yoksa kodu yazanin tersi
        if _m.get("review_mode") == "test":
            _yazan = agent_name or _m.get("agent_override") or flow.agent
            agent_name = next(
                (lbl.split("/", 1)[1] for lbl in labels if lbl.startswith("test-agent/")),
                {"claude": "codex", "codex": "claude"}.get(_yazan or "", "claude"),
            )
        if agent_name and agent_name not in AGENT_COMMANDS:
            await broadcaster.log(
                run.id, f"Bilinmeyen ajan etiketi: agent/{agent_name}", level="warning", phase="agent"
            )
            agent_name = None
        agent_name = agent_name or (run.task_source_meta or {}).get("agent_override") or flow.agent
        tier = next(
            (lbl.split("/", 1)[1] for lbl in labels if lbl.startswith("difficulty/")), "easy"
        ).upper()
        resolved = await services.agent_resolver.resolve_agent(
            agent_name, session, run.workspace_server_id, project_id=run.project_id
        )
        env = (resolved.agent_settings.environment_vars if resolved.agent_settings else None) or {}
        model = env.get(f"MODEL_FOR_DIFFICULTY_{tier}") or env.get(f"MODEL_FOR_{tier}") or None
        await broadcaster.log(
            run.id,
            f"Ajan: {getattr(resolved.adapter, 'agent_name', agent_name)}, difficulty: {tier.lower()}, "
            f"model: {model or 'ajanin varsayilani'}",
            phase="agent",
        )

        async def _agent_log(msg: str, level: str = "info") -> None:
            await broadcaster.log(run.id, msg, level=level, phase="agent")

        await ensure_agent_ready(
            resolved.adapter, log_fn=_agent_log, agent_settings=resolved.agent_settings
        )

        # bimetri yamasi: cagri suresi ve sonucu agent_invocations'a
        _ajan = getattr(resolved.adapter, "agent_name", agent_name)
        _t0 = datetime.now(UTC)
        try:
            result = await run_agent_step(
                run,
                session,
                services,
                # bimetri yamasi: etiketten gelen ajan ve model
                {"agent": agent_name, "model": model, "params": {"prompt": prompt, "mode": flow.agent_mode}},
            )
        except Exception as _exc:
            _bimetri_cagri_kaydi(run, session, _ajan, flow.name, _t0, None, _exc)
            raise
        _bimetri_cagri_kaydi(run, session, _ajan, flow.name, _t0, {**result, "model": model}, None)
        # bimetri yamasi: CLI hata koduyla bittiyse (limit, kimlik, cokme) kosu basarisiz
        _rd = result.get("response")
        _rc = _rd.get("exit_code") if isinstance(_rd, dict) else None
        if _rc not in (None, 0):
            raise RuntimeError(f"Ajan CLI hata koduyla bitti ({_rc})")
        run.coding_results = {
            "flow_prompt": flow.name,
            "agent": result.get("agent"),
            "mode": result.get("mode"),
            "response": result.get("response"),
            # bimetri yamasi: PR aciklamasi icin secilen model
            "model": model,
        }
        # PR-review flows: surface the response as review_result so finalization
        # posts it as a PR comment + flips the label (parity with the template path).
        if flow.flow_type == "pr_review":
            resp = result.get("response")
            # bimetri yamasi: inceleme yorumunda yalnizca ajanin son mesaji (stderr/prompt degil)
            if isinstance(resp, dict) and isinstance(resp.get("output"), str):
                resp = resp["output"]
            review_text = resp if isinstance(resp, str) else json.dumps(resp, default=str)
            run.review_result = {
                "summary": review_text,
                "approved": False,
                "issues": [],
                "suggestions": [],
            }
        await session.commit()

        await _run_phase("finalization", run, session, services)

        # bimetri yamasi: PR acilmayan kod kosusu basarili sayilmasin (listede failed gorunsun)
        if flow.flow_type != "pr_review" and not run.pr_url:
            raise RuntimeError("PR acilmadi: ajan degisiklik birakmadi ya da PR olusturulamadi")
        # bimetri yamasi: PR acik/guncellendi, issue ve PR status/review
        # (otomatik tur siniri dolduysa PR/issue status/on-hold kalir)
        if flow.flow_type != "pr_review" and not bekletildi_mi(run.id):
            await _bimetri_durum(run, session, "status/review")

        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        await session.commit()
        await broadcaster.log(run.id, "Flow complete", phase="finalization")
        await broadcaster.event(
            run.id,
            "run_completed",
            {"status": "completed", "run_id": run.id, "title": run.title},
        )
    except Exception as e:
        logger.exception("Flow run #%s failed", run.id)
        run.status = "failed"
        run.error_message = str(e)
        run.completed_at = datetime.now(UTC)
        await session.commit()
        await broadcaster.event(
            run.id, "run_failed", {"run_id": run.id, "error": str(e), "title": run.title}
        )
        with contextlib.suppress(Exception):
            await close_run_session(run, session)
        # bimetri yamasi: basarisiz kosu (inceleme dahil): issue (ve varsa PR) status/on-hold
        await _bimetri_durum(run, session, "status/on-hold")
