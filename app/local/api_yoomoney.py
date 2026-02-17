from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

# from app.local.handlers import apply_balance_topup, finalize_if_paid, send_msg_balance
from app.local.utils import apply_balance_topup, send_msg_balance
from yoomoney import Quickpay, Client
from app.database.database import AsyncSessionLocal
from app.local.storage import PaymentsStore


UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def dt_to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def dt_from_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class PollingIntervals:
    fast_sec: int = 5            # < 1 hour
    mid_sec: int = 30            # 1..24 hours
    slow_sec: int = 600          # 24..48 hours (10 min)
    stop_after_sec: int = 172800 # 48 hours


def calc_interval(age: timedelta, cfg: PollingIntervals) -> Optional[int]:
    sec = int(age.total_seconds())
    if sec > cfg.stop_after_sec:
        return None
    if sec <= 3600:
        return cfg.fast_sec
    if sec <= 86400:
        return cfg.mid_sec
    return cfg.slow_sec


class YooMoneyTopUpService:
    """
    Service:
    - create payment (Quickpay)
    - check by label(uid)
    - smart global polling for all pending payments (optional)
    """

    def __init__(
        self,
        *,
        store: PaymentsStore,
        access_token: str,
        receiver: str,
        return_url_template: str,
        intervals: PollingIntervals | None = None,
        bot,
    ):
        self.store = store
        self.client = Client(token=access_token)
        self.receiver = receiver
        self.return_url_template = return_url_template
        self.intervals = intervals or PollingIntervals()

        self._poll_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.bot = bot
        # self.db = None


    def start_global_polling(self) -> None:
        if self._poll_task and not self._poll_task.done():
            return
        self._stop.clear()
        self._poll_task = asyncio.create_task(self._poll_loop(), name="local.topup.global_poll")

    async def stop_global_polling(self) -> None:
        self._stop.set()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    async def create_payment(self, *, tg_id: int, username: str, amount: Decimal) -> Dict[str, Any]:
        uid = str(uuid.uuid4())
        success_url = self.return_url_template.format(uid=uid)

        def _make_qp() -> Quickpay:
            return Quickpay(
                receiver=self.receiver,
                successURL=success_url,
                quickpay_form="shop",
                targets="Пополнение баланса",
                paymentType="SB",
                sum=float(amount),
                label=uid,
            )

        qp = await asyncio.to_thread(_make_qp)
        pay_url = qp.redirected_url

        rec = {
            "uid": uid,
            "type": "topup",
            "tg_id": str(tg_id),
            "username": username or "",
            "amount": str(amount.quantize(Decimal("0.01"))),
            "currency": "RUB",
            "status": "pending",
            "created_at": dt_to_iso(utcnow()),
            "last_checked_at": None,
            "next_check_at": dt_to_iso(utcnow() + timedelta(seconds=self.intervals.fast_sec)),
            "paid_at": None,
        }
        await self.store.upsert(uid, rec)

        return {"uid": uid, "pay_url": pay_url, "record": rec}

    async def check_payment(self, uid: str) -> bool:
        rec = await self.store.get(uid)
        if not rec:
            return False
        if rec.get("status") == "succeeded":
            return False
        if rec.get("status") in {"expired", "failed"}:
            return False

        created_at = dt_from_iso(rec["created_at"])
        age = utcnow() - created_at
        interval = calc_interval(age, self.intervals)
        if interval is None:
            await self.store.patch(uid, status="expired", expired_at=dt_to_iso(utcnow()), next_check_at=None)
            return False

        history = await asyncio.to_thread(self.client.operation_history, label=uid)

        expected = Decimal(str(rec["amount"])).quantize(Decimal("0.01"))
        for op in getattr(history, "operations", []) or []:
            print(op)
            if getattr(op, "status", None) == "success":
                try:
                    paid_amount = Decimal(str(getattr(op, "amount", "0"))).quantize(Decimal("0.01"))
                except Exception:
                    continue
                if paid_amount >= (expected * Decimal("0.92")):
                    await self.store.patch(uid, status="succeeded", paid_at=dt_to_iso(utcnow()), next_check_at=None)
                    return True

        return False

    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._poll_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(1)

    async def _poll_tick(self) -> None:
        now = utcnow()
        pending = await self.store.iter_pending()
        if not pending:
            return

        due: list[tuple[str, dict]] = []
        for uid, rec in pending.items():
            created_at = dt_from_iso(rec["created_at"])
            age = now - created_at

            interval = calc_interval(age, self.intervals)
            if interval is None:
                await self.store.patch(uid, status="expired", expired_at=dt_to_iso(now), next_check_at=None)
                continue

            next_check_at_raw = rec.get("next_check_at")
            if next_check_at_raw:
                try:
                    if now < dt_from_iso(next_check_at_raw):
                        continue
                except Exception:
                    pass

            due.append((uid, rec))

        if not due:
            return

        sem = asyncio.Semaphore(10)

        async def worker(uid: str, rec: dict) -> None:
            async with sem:
                created_at = dt_from_iso(rec["created_at"])
                age = now - created_at
                interval = calc_interval(age, self.intervals)
                if interval is None:
                    await self.store.patch(uid, status="expired", expired_at=dt_to_iso(now), next_check_at=None)
                    return

                # reserve next check to avoid duplicate work in next ticks
                await self.store.patch(
                    uid,
                    last_checked_at=dt_to_iso(now),
                    next_check_at=dt_to_iso(now + timedelta(seconds=interval)),
                )

                # is_payment_ok = await self.check_payment(uid)


                
                
                    # await cb.answer(



                ok = await self.check_payment(uid)
                if not ok:
                    return False

                rec = await self.store.get(uid)
                if not rec:
                    return False

                user_id = int(rec["tg_id"])
                amount = Decimal(str(rec["amount"])).quantize(Decimal("0.01"))

                async with AsyncSessionLocal() as db:
                    try:
                        await apply_balance_topup(db, user_id, amount)
                        await db.commit()
                    except Exception as e:
                        print(e)

                
                await send_msg_balance(self.bot, user_id, amount)
                return True


                # async with AsyncSessionLocal() as db:
                #     try:
                    

                #     # if self.db:
                #         ok = finalize_if_paid(self.bot, db, self, uid)
                #         await db.commit()
                #     except Exception as e:
                #         print(e)
                #     # await cb.answer("✅ Оплата подтверждена!" if ok else "Платёж пока не завершён.", show_alert=True)


        await asyncio.gather(*(worker(uid, rec) for uid, rec in due))
