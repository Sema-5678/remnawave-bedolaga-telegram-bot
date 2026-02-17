from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from aiogram import F, Router, Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from app.local.utils import apply_balance_topup, send_msg_balance
from sqlalchemy.ext.asyncio import AsyncSession
from .api_yoomoney import YooMoneyTopUpService
from app.database.crud.user import add_user_balance, get_user_by_id, get_user_by_telegram_id

from app.keyboards.inline import get_back_keyboard

class TopUpStates(StatesGroup):
    amount = State()


topup_router = Router()
topup_router.message.filter(F.chat.type == "private")
topup_router.callback_query.filter(F.message.chat.type == "private")


_AMOUNT_RE = re.compile(r"^\s*([0-9]+(?:[.,][0-9]{1,2})?)\s*$")


def parse_amount(text: str) -> Optional[Decimal]:
    m = _AMOUNT_RE.match(text or "")
    if not m:
        return None
    raw = m.group(1).replace(",", ".")
    try:
        amount = Decimal(raw).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0:
        return None
    return amount


async def _edit_same_message(event: CallbackQuery | Message, *, text: str, reply_markup=None) -> None:
    msg = event.message if isinstance(event, CallbackQuery) else event
    if msg is None:
        return

    try:
        if getattr(msg, "photo", None):
            await msg.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        else:
            await msg.edit_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        # fallback: send new
        if isinstance(event, CallbackQuery):
            await event.message.answer(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        else:
            await event.answer(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


def kb_pay_and_check(pay_url: str, uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"topup_check:{uid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")],
    ])



async def finalize_if_paid(bot: Bot, db, svc: YooMoneyTopUpService, uid: str) -> bool:
    ok = await svc.check_payment(uid)
    if not ok:
        return False

    rec = await svc.store.get(uid)
    if not rec:
        return False

    user_id = int(rec["tg_id"])
    amount = Decimal(str(rec["amount"])).quantize(Decimal("0.01"))
    await apply_balance_topup(db, user_id, amount)

    await send_msg_balance(bot, user_id, amount)
  
    return True















@topup_router.callback_query(F.data == "yoomoney_topup")
async def topup_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TopUpStates.amount)

    text = (
        "💰 <b>Пополнение баланса</b>\n\n"
        "Введите сумму пополнения (например: <code>100</code> или <code>100,50</code>)."
    )
    # get_back_keyboard()
    # texts = get_texts(DEFAULT_LANGUAGE)
    kb = get_back_keyboard(callback_data='balance_topup')
    await _edit_same_message(cb, text=text, reply_markup=kb)
    await cb.answer()


@topup_router.message(TopUpStates.amount)
async def topup_amount_input(msg: Message, state: FSMContext, bot: Bot, db: AsyncSession):
    svc: YooMoneyTopUpService = msg.bot.topup_service  # см. local/wiring.py

    amount = parse_amount(msg.text)
    if amount is None:
        await msg.answer("❌ Некорректная сумма. Пример: <code>100</code> или <code>100,50</code>", parse_mode=ParseMode.HTML)
        return

    created = await svc.create_payment(
        tg_id=msg.from_user.id,
        username=msg.from_user.username or "",
        amount=amount,
    )
    uid = created["uid"]
    pay_url = created["pay_url"]

    text = (
        "💳 <b>Оплата пополнения</b>\n\n"
        f"Сумма: <b>{amount}</b> ₽\n\n"
        "Нажмите «Оплатить», затем при необходимости «Проверить оплату».\n"
        "Автопроверка также будет выполняться."
    )

    await msg.answer(
        text,
        reply_markup=kb_pay_and_check(pay_url, uid),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    # локальный polling конкретного uid (быстрый)
    # async def one_poll():
    #     while True:
    #         rec = await svc.store.get(uid)
    #         if not rec:
    #             return
    #         if rec.get("status") in {"succeeded", "expired", "failed"}:
    #             return
    #         ok = await finalize_if_paid(bot, db, svc, uid)
    #         if ok:
    #             return
    #         await asyncio.sleep(5)

    # asyncio.create_task(one_poll(), name=f"local.topup.one_poll.{uid}")
    await state.clear()


@topup_router.callback_query(F.data.startswith("topup_check:"))
async def topup_check(cb: CallbackQuery, bot: Bot, db: AsyncSession):
    svc: YooMoneyTopUpService = cb.bot.topup_service
    uid = cb.data.split(":", 1)[1]

    rec = await svc.store.get(uid)

    if rec.get('status')=='succeeded':
        await cb.answer("✅ Оплата уже подтверждена!")
        return

    # if not rec:
    #     await cb.answer("❌ Невалидный токен", show_alert=True)
    #     return
    # if str(cb.from_user.id) != str(rec.get("tg_id")):
    #     await cb.answer("❌ Это не ваша оплата", show_alert=True)
    #     return

    # is_payment_ok = await bot.svc.check_payment(uid)

    # if is_payment_ok:
    ok = await finalize_if_paid(bot, db, svc, uid)
    await cb.answer("✅ Оплата подтверждена!" if ok else "Платёж пока не завершён.", show_alert=True)
    # else:
    #     await cb.answer("⏳ Ожидание оплаты" if ok else "Платёж пока не завершён.", show_alert=True)

