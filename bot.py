#!/usr/bin/env python3
"""
MushBot – temel akış (aiogram v3)

Akış (özet):
1) /start -> "MushBot’un renkli dünyasına giriş yap" butonu
2) Şehir seçimi: İstanbul
3) Menü: 🗂️ Katalog | 🛒 Alışverişe devam et
4) Katalog: görsel gönder (ENV: KATALOG_IMAGE_FILE_ID veya KATALOG_IMAGE_URL; yoksa /katalog_yukle ile ayarla)
5) Alışveriş: ürün isimleri -> ürüne basınca emojili açıklama + kripto adresi + "Ödeme yaptım"
6) Ödeme yaptım: dekont iste -> Ödemeler kanalına bildirim + Onayla/Reddet
7) İlk /start’ta Etkileşimler kanalına kullanıcı bildirimi (tek sefer)
"""

import asyncio
import os
import logging
from datetime import datetime
from typing import Set, Dict, Any, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext


# --------- Ortam değişkenleri ----------
# Zorunlu:
#   BOT_TOKEN
#   CRYPTO_ADDRESS
#   NOTIFY_CHANNEL_INTERACTIONS_ID   (Etkileşimler kanalı id, -100... )
#   NOTIFY_CHANNEL_PAYMENTS_ID       (Ödemeler kanalı id, -100... )
# Opsiyonel:
#   KATALOG_IMAGE_FILE_ID            (Telegram file_id)
#   KATALOG_IMAGE_URL                (Foto URL)

# --------- Sabitler ----------
BTN_ENTER = "MushBot’un renkli dünyasına giriş yap 🎭"
BTN_CITY_IST = "🏙️ İstanbul"
BTN_CATALOG = "🗂️ Katalog"
BTN_SHOP = "🛒 Alışverişe devam et"

CB_ENTER = "enter"
CB_CITY_IST = "city_istanbul"
CB_SHOW_CATALOG = "show_catalog"
CB_SHOW_SHOP = "show_shop"
CB_PRODUCTS_PREFIX = "product:"
CB_PAID_PREFIX = "paid:"

# --------- Ürünler ----------
PRODUCTS = [
    {
        "id": "mikrodoz",
        "name": "Mikrodoz Kapsül",
        "price": "(doldurulacak)",
        "desc": (
            "💊 Günlük denge, odak ve huzur.\n"
            "🌿 Düşük dozlu form; zihinsel berraklık ve sakinlik.\n"
            "🧠 Yaratıcılığı ve farkındalığı destekleyebilir."
        ),
    },
    {
        "id": "pinkbuf",
        "name": "Pink Buffalo",
        "price": "(doldurulacak)",
        "desc": (
            "🐃 Tayland kökenli güçlü bir tür.\n"
            "🌈 Derin farkındalık, yoğun görsel deneyimler.\n"
            "⚡ Ruhsal içgörü arayanlar için."
        ),
    },
    {
        "id": "goldtea",
        "name": "Golden Teacher",
        "price": "(doldurulacak)",
        "desc": (
            "👁️ Klasik, ‘öğretici’ deneyim.\n"
            "🕊️ İçsel yolculuk ve bilinç farkındalığı.\n"
            "🌟 Nazik ama derin etki."
        ),
    },
    {
        "id": "choc",
        "name": "Mantar Çikolata",
        "price": "(doldurulacak)",
        "desc": (
            "🍫 Derin bitter kakao, toprağın özünden gelen Reishi’nin sakin nefesiyle buluşur; "
            "kreatin ve magnezyum bedeni dengeye çağırırken, taurin ve besin mayası içsel ritmi hizalar. "
            "Her kare, nefesin yavaşladığı, zamanın esnediği bir an’a dönüşür. "
            "Doğal psilosibin, farkındalığın kapısını aralayıp sınırları eritir; "
            "zihni genişletir, benliği sessiz bir huzura taşır. "
            "Mantar çikolata yalnızca bir tat değil, karanlığın içinde parlayan küçük bir ışık gibidir."
        ),
    },
]


# --------- FSM ---------
class ExpectReceipt(StatesGroup):
    waiting = State()


# --------- Router / Hafıza ---------
router = Router()
started_users: Set[int] = set()
ORDERS: Dict[str, Dict[str, Any]] = {}
CATALOG_FILE_ID: Optional[str] = os.getenv("KATALOG_IMAGE_FILE_ID")
CATALOG_IMAGE_URL: Optional[str] = os.getenv("KATALOG_IMAGE_URL")


# --------- Klavyeler ----------
def make_enter_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=BTN_ENTER, callback_data=CB_ENTER)
    kb.adjust(1)
    return kb.as_markup()


def make_city_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=BTN_CITY_IST, callback_data=CB_CITY_IST)
    kb.adjust(1)
    return kb.as_markup()


def make_post_city_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=BTN_CATALOG, callback_data=CB_SHOW_CATALOG)
    kb.button(text=BTN_SHOP, callback_data=CB_SHOW_SHOP)
    kb.adjust(1)
    return kb.as_markup()


def make_products_list_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in PRODUCTS:
        kb.button(text=f"🛍️ {p['name']}", callback_data=f"{CB_PRODUCTS_PREFIX}{p['id']}")
    kb.adjust(1)
    return kb.as_markup()


def make_payment_kb(prod_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ödeme yaptım", callback_data=f"{CB_PAID_PREFIX}{prod_id}")
    kb.adjust(1)
    return kb.as_markup()


# --------- Komutlar ----------
@router.message(CommandStart())
async def on_start(msg: Message, bot: Bot):
    welcome = (
        "👋 *MushBot* burada!\n\n"
        "MushBot'un renkli dünyasına hoş geldin. Aşağıdaki butona dokunarak başlayabilirsin."
    )
    await msg.answer(welcome, parse_mode="Markdown", reply_markup=make_enter_kb())

    uid = msg.from_user.id
    if uid not in started_users:
        started_users.add(uid)
        interact_id_str = os.getenv("NOTIFY_CHANNEL_INTERACTIONS_ID")
        if interact_id_str:
            try:
                interact_id = int(interact_id_str)
                u = msg.from_user
                info = (
                    "👤 *Yeni kullanıcı etkileşimi!*\n\n"
                    f"🆔 ID: `{u.id}`\n"
                    f"🪪 Ad: {u.full_name} (@{u.username or '-'})\n"
                    f"🕒 Zaman (UTC): {datetime.utcnow().isoformat()}"
                )
                await bot.send_message(interact_id, info, parse_mode="Markdown")
            except Exception as e:
                print(f"[start notify] gönderilemedi: {e}")


@router.callback_query(F.data == CB_ENTER)
async def on_enter(cb: CallbackQuery):
    await cb.message.edit_text("Lütfen bulunduğun şehri seç 💫", reply_markup=make_city_kb())
    await cb.answer()


@router.callback_query(F.data == CB_CITY_IST)
async def on_city_istanbul(cb: CallbackQuery):
    text = "📍 Şehir: *İstanbul*\n\nNe yapmak istersin?"
    await cb.message.edit_text(text, reply_markup=make_post_city_menu_kb(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data == CB_SHOW_CATALOG)
async def on_show_catalog(cb: CallbackQuery, bot: Bot):
    if CATALOG_FILE_ID:
        await bot.send_photo(cb.message.chat.id, CATALOG_FILE_ID, caption="🗂️ Katalog")
    elif CATALOG_IMAGE_URL:
        await bot.send_photo(cb.message.chat.id, CATALOG_IMAGE_URL, caption="🗂️ Katalog")
    else:
        await cb.message.answer("🗂️ Katalog görseli hazır değil. /katalog_yukle komutuyla foto ekleyebilirsin.")
    await cb.answer()


@router.callback_query(F.data == CB_SHOW_SHOP)
async def on_show_shop(cb: CallbackQuery):
    text = "🛍️ *Ürünler*\n\nBir ürün seçin:"
    await cb.message.edit_text(text, reply_markup=make_products_list_kb(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith(CB_PRODUCTS_PREFIX))
async def on_product_detail(cb: CallbackQuery):
    prod_id = cb.data.split(":", 1)[1]
    prod = next((p for p in PRODUCTS if p["id"] == prod_id), None)
    if not prod:
        await cb.answer("Ürün bulunamadı", show_alert=True)
        return

    addr = os.getenv("CRYPTO_ADDRESS", "(CRYPTO_ADDRESS ortam değişkenini ayarlayın)")
    text = f"""*{prod['name']}*
Fiyat: {prod['price']}

{prod['desc']}

*Ödeme yöntemi: Sadece KRİPTO*
Aşağıdaki cüzdan adresine tutarı gönderin, sonra *Ödeme yaptım* butonuna basın.

Cüzdan Adresi:
```
{addr}
```
"""
    await cb.message.edit_text(text, reply_markup=make_payment_kb(prod_id), parse_mode="Markdown")
    await cb.answer()


# --------- Main ---------
async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN ortam değişkeni ayarlı değil.")
    bot = Bot(token)
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("MushBot durduruldu.")
