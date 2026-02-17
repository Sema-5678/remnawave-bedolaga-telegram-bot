from __future__ import annotations

from pathlib import Path

from aiogram import Dispatcher, Bot

from .api_yoomoney import YooMoneyTopUpService
from .config import load_env
from .storage import PaymentsStore
from .handlers import topup_router


def setup_local_topup(dp: Dispatcher, bot: Bot) -> YooMoneyTopUpService:
    """
    Wire module into your project.

    Usage:
        from local.wiring import setup_local_topup
        setup_local_topup(dp, bot)

    Env:
        YOOMONEY_ACCESS_TOKEN
        YOOMONEY_RECEIVER
        TOPUP_RETURN_URL_TEMPLATE (optional)
        TOPUP_PAYMENTS_JSON_PATH (optional)
    """
    default_json = str((Path(__file__).resolve().parent / "payments.json"))
    env = load_env(default_payments_path=default_json)

    
    
    from app.local.handlers import topup_router
    dp.include_router(topup_router)

    store = PaymentsStore(env.PAYMENTS_JSON_PATH)
    svc = YooMoneyTopUpService(
        store=store,
        access_token=env.YOOMONEY_ACCESS_TOKEN,
        receiver=env.YOOMONEY_RECEIVER,
        return_url_template=env.RETURN_URL_TEMPLATE,
        bot=bot,
        # db=db,
    )

    # bot["topup_service"] = svc
    bot.topup_service = svc
    # dp.include_router(topup_router)

    # optional: global smart polling for all pending payments
    svc.start_global_polling()

    return svc
