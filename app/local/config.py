from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalTopUpEnv:
    # YooMoney
    YOOMONEY_ACCESS_TOKEN: str
    YOOMONEY_RECEIVER: str

    # Bot return URL, e.g. "https://t.me/your_bot?start={uid}"
    RETURN_URL_TEMPLATE: str

    # Storage
    PAYMENTS_JSON_PATH: str


def load_env(default_payments_path: str) -> LocalTopUpEnv:
    access_token = os.getenv("YOOMONEY_ACCESS_TOKEN", "").strip()
    receiver = os.getenv("YOOMONEY_RECEIVER", "").strip()
    return_url = os.getenv("TOPUP_RETURN_URL_TEMPLATE", "").strip() or "https://t.me/your_bot?start={uid}"
    payments_path = os.getenv("TOPUP_PAYMENTS_JSON_PATH", "").strip() or "/app/data/local/payments.json"

    if not access_token:
        raise RuntimeError("YOOMONEY_ACCESS_TOKEN is not set")
    if not receiver:
        raise RuntimeError("YOOMONEY_RECEIVER is not set")

    return LocalTopUpEnv(
        YOOMONEY_ACCESS_TOKEN=access_token,
        YOOMONEY_RECEIVER=receiver,
        RETURN_URL_TEMPLATE=return_url,
        PAYMENTS_JSON_PATH=payments_path,
    )
