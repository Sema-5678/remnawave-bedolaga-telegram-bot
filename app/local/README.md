# local/ — модуль пополнения баланса (aiogram 3 + YooMoney)

## Что внутри
- `payments.json` — хранилище (uid -> record)
- `storage.py` — атомарная запись JSON + lock
- `api_yoomoney.py` — создание Quickpay, проверка, умный global polling
- `handlers.py` — Router + FSM:
  - callback: `topup`
  - check callback: `topup_check:{uid}`
- `wiring.py` — подключение в твой проект
- `config.py` — загрузка env

## Установка
```bash
pip install yoomoney httpx
```

## Переменные окружения
```
YOOMONEY_ACCESS_TOKEN=...
YOOMONEY_RECEIVER=...
TOPUP_RETURN_URL_TEMPLATE=https://t.me/your_bot?start={uid}
TOPUP_PAYMENTS_JSON_PATH=/path/to/your/payments.json   # опционально
```

## Подключение (в main/bot_app)
```python
from local.wiring import setup_local_topup

setup_local_topup(dp, bot)
```

## Кнопка в твоём меню
Добавь кнопку с `callback_data="topup"`.
