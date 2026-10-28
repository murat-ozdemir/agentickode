# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: `@agentickode tekrar` - PR ya da issue'nun son basarisiz kosusunu yeniden baslatir."""

import contextlib

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun

_TEKRARLANIR = ("failed", "timeout", "cancelled")


async def son_kosu(db: AsyncSession, project_id: str, n: int, pr_mi: bool) -> TaskRun | None:
    """PR'da: test, inceleme ve duzeltme kosulari; issue'da: kod kosusu."""
    if pr_mi:
        kosul = or_(
            TaskRun.task_id.in_((f"pr-test-{n}", f"pr-{n}")),
            TaskRun.task_id.like(f"pr-comment-{n}-%"),
        )
    else:
        kosul = TaskRun.task_id == str(n)
    r = await db.execute(
        select(TaskRun)
        .where(TaskRun.project_id == project_id, kosul)
        .order_by(TaskRun.id.desc())
        .limit(1)
    )
    return r.scalar_one_or_none()


async def tekrar_baslat(db: AsyncSession, gp, full: str, project_id: str, n: int, pr_mi: bool) -> str:
    """Kosuyu yeniden baslatir; kullaniciya yazilacak yaniti dondurur."""
    from backend.api.runs_actions import reset_run_for_restart

    run = await son_kosu(db, project_id, n, pr_mi)
    if run is None:
        return "Yeniden başlatılacak koşu bulunamadı."
    if run.status in ("pending", "running"):
        return f"Koşu #{run.id} zaten sürüyor; bitmesini bekle."
    if run.status not in _TEKRARLANIR:
        return f"Son koşu #{run.id} başarısız değil ({run.status}); tekrarlanacak bir şey yok."
    await reset_run_for_restart(run, db)
    await db.commit()
    if run.task_id == f"pr-{n}":  # inceleme kosusu: PR yeniden status/review
        with contextlib.suppress(Exception):
            await gp.set_status_label(full, n, "status/review")
    baslik = (run.title or "")[:80].replace("@", "@\u200b")
    return f"Koşu #{run.id} ({baslik}) yeniden başlatıldı."
