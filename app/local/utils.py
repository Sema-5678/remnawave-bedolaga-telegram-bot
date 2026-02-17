


from decimal import Decimal, InvalidOperation

from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message

from app.database.crud.user import add_user_balance, get_user_by_id, get_user_by_telegram_id

from aiogram.enums import ParseMode




def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")],
    ])




async def send_msg_balance(bot, user_id, amount):

     await bot.send_message(
        chat_id=user_id,
        text=f"✅ Баланс успешно пополнен на <b>{amount}</b> ₽",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_back()
    )






async def apply_balance_topup(db, user_id: int, amount: Decimal) -> None:
    """
    По умолчанию работает с user_data['balance'].
    Если у тебя другой формат/поле — поменяй тут.
    """
    # user = get_user_data(user_id)
    user = await get_user_by_telegram_id(db, user_id)
    amount =  int(amount * 100)
    await add_user_balance(db, user, amount, create_transaction=False)
    # curr = user.get("balance", "0")
    # try:
    #     curr_dec = Decimal(str(curr)).quantize(Decimal("0.01"))
    # except Exception:
    #     curr_dec = Decimal("0.00")

    # user["balance"] = str((curr_dec + amount).quantize(Decimal("0.01")))
    # update_user_data(user_id, user)

