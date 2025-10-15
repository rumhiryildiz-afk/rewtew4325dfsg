#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MushBot — tek dosya Telegram botu (aiogram v3, 3.7+ uyumlu)

KULLANIM:
- Ortam değişkenleri:
    BOT_TOKEN (zorunlu)
    CRYPTO_ADDRESS (zorunlu)
    NOTIFY_CHANNEL_INTERACTIONS_ID (ör: -100...)
    NOTIFY_CHANNEL_PAYMENTS_ID (ör: -100...)
    KATALOG_IMAGE_FILE_ID / KATALOG_IMAGE_URL (opsiyonel)

- Start: python bot.py
- requirements.txt: aiogram==3.*
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import SkipHandler
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ---------- Veri dosyası ----------
DATA_FILE = Path("products.json")

# ---------- Global durum ----------
IS_LOCKED = False
router = Router()
started_users: Set[int] = set()
ORDERS: Dict[str, Dict[str, Any]] = {}

# ---------- Ürün yükleme / kaydetme ----------
def load_products() -> List[Dict[str, Any]]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logging.warning(f"products.json okunamadı ({e}), varsayılan kullanılacak.")
    # Varsayılan ürünler
    return [
        {
            "id": "mikrodoz",
            "name": "Mikrodoz Kapsül",
            "price": "Fiyat: (doldurulacak)",
            "desc": "💊 Günlük denge, odak ve huzur.\n🌿 Düşük dozlu form; berraklık ve sakinlik.\n🧠 Yaratıcılığı destekleyebilir.",
            "photo": None,
        },
        {
            "id": "pinkbuf",
            "name": "Pink Buffalo",
            "price": "Fiyat: (doldurulacak)",
            "desc": "🐃 Kökenine özgü karakteristik deneyimler.\n🌈 Yoğun görseller, derin farkındalık.",
            "photo": None,
        },
        {
            "id": "goldtea",
            "name": "Golden Teacher",
            "price": "Fiyat: (doldurulacak)",
            "desc": "👁️ Klasik, ‘öğretici’ profil.\n🕊️ İçsel yolculuk ve farkındalık odaklı.",
            "photo": None,
        },
        {
            "id": "choc",
            "name": "Mantar Çikolata",
            "price": "Fiyat: (doldurulacak)",
            "desc": (
                "🍫 %90 bitter taban; Reishi ve takviye bileşenleriyle dengelenmiş bir form.\n"
                "Her kare sakinleştirici ve farkındalığı tetikleyen bir deneyim sunabilir."
            ),
            "photo": None,
        },
    ]


def save_products(products: List[Dict[str, Any]]) -> None:
    try:
        DATA_FILE.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logging.error(f"products.json yazılamadı: {e}")


PRODUCTS: List[Dict[str, Any]] = load_products()

# ---------- Katalog görsel kaynakları (ENV) ----------
CATALOG_FILE_ID: Optional[str] = os.getenv("KATALOG_IMAGE_FILE_ID")
CATALOG_IMAGE_URL: Optional[str] = os.getenv("KATALOG_IMAGE_URL")

# ---------- Sabitler ----------
BTN_ENTER = "MushBot’un renkli dünyasına giriş yap 🎭"
BTN_CITY_IST = "🏙️ İstanbul"
BTN_CATALOG = "🗂️ Katalog"
BTN_SHOP = "🛒 Alışverişe devam et"
BTN_TICKET = "🎫 Toplu alım için ticket aç"

CB_ENTER = "enter"
CB_CITY_IST = "city_istanbul"
CB_SHOW_CATALOG = "show_catalog"
CB_SHOW_SHOP = "show_shop"
CB_OPEN_TICKET_SIMPLE = "open_ticket_simple"
CB_PRODUCTS_PREFIX = "product:"
CB_PAID_PREFIX = "paid:"
CB_ADMIN_OK_PREFIX = "admin_ok:"
CB_ADMIN_NO_PREFIX = "admin_no:"

# Geri buton callbackleri
CB_BACK_ENTER = "back_enter"
CB_BACK_CITY = "back_city"
CB_BACK_MENU = "back_menu"
CB_BACK_SHOP = "back_shop"
CB_BACK_DETAIL = "back_detail"

# ---------- FSM ----------
class ExpectReceipt(StatesGroup):
    waiting = State()

# ---------- Yardımcı fonksiyonlar ----------
def get_crypto_address() -> str:
    return os.getenv("CRYPTO_ADDRESS", "(CRYPTO_ADDRESS ortam değişkenini ayarlayın)")

def find_product(pid: str) -> Optional[Dict[str, Any]]:
    return next((p for p in PRODUCTS if p.get("id") == pid), None)

def remove_product_by_id(pid: str) -> bool:
    global PRODUCTS
    before = len(PRODUCTS)
    PRODUCTS = [p for p in PRODUCTS if p.get("id") != pid]
    if len(PRODUCTS) != before:
        save_products(PRODUCTS)
        return True
    return False

# ---------- Klavyeler ----------
def kb_enter() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=BTN_ENTER, callback_data=CB_ENTER)
    kb.adjust(1)
    return kb.as_markup()

def kb_city() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=BTN_CITY_IST, callback_data=CB_CITY_IST)
    kb.button(text="⬅️ Geri", callback_data=CB_BACK_ENTER)
    kb.adjust(1)
    return kb.as_markup()

def kb_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=BTN_CATALOG, callback_data=CB_SHOW_CATALOG)
    kb.button(text=BTN_SHOP, callback_data=CB_SHOW_SHOP)
    kb.button(text=BTN_TICKET, callback_data=CB_OPEN_TICKET_SIMPLE)
    kb.button(text="⬅️ Geri", callback_data=CB_BACK_CITY)
    kb.adjust(1)
    return kb.as_markup()

def kb_products_list() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if PRODUCTS:
        for p in PRODUCTS:
            kb.button(text=f"🛍️ {p['name']}", callback_data=f"{CB_PRODUCTS_PREFIX}{p['id']}")
    else:
        kb.button(text="(Stokta ürün yok)", callback_data="noop")
    kb.button(text="⬅️ Geri", callback_data=CB_BACK_MENU)
    kb.adjust(1)
    return kb.as_markup()

def kb_payment(prod_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ödeme yaptım", callback_data=f"{CB_PAID_PREFIX}{prod_id}")
    kb.button(text="⬅️ Geri", callback_data=CB_BACK_SHOP)
    kb.adjust(1)
    return kb.as_markup()

# ---------- Global gate (düzeltildi: SkipHandler kullanılıyor) ----------
@router.message()
async def gate_messages(msg: Message):
    """
    Bu handler aiogram'ın önceki davranışına göre 'first match wins' etkisi
    gösterebilir; bu yüzden burada yalnızca kilit (IS_LOCKED) kontrolü yaparız.
    Eğer komut /yoladevam veya /mola369 ise SkipHandler fırlatılır ki
    diğer handler'lar çalışsın. Kilitliyken diğer mesajlar sessizce yutulur.
    """
    text = (msg.text or "").strip()
    # bu iki komut diğer handlerlara geçsin
    if text.startswith("/yoladevam") or text.startswith("/mola369"):
        raise SkipHandler
    # kilitliyse sessizce yut
    if IS_LOCKED:
        return
    # değilse diğer handlerlara geç
    raise SkipHandler

@router.callback_query()
async def gate_callbacks(cb: CallbackQuery):
    # callback'lerde kilitliyse kullanıcıyı uyar; değilse diğer callback handlerlara geç
    if IS_LOCKED:
        try:
            await cb.answer("Bot şu an molada. /yoladevam yaz.", show_alert=True)
        except Exception:
            await cb.answer()
        return
    raise SkipHandler

# ---------- Komutlar ----------
@router.message(CommandStart())
async def on_start(msg: Message, bot: Bot):
    welcome = "👋 *MushBot* burada!\n\nAşağıdaki butona dokunarak başlayabilirsin."
    await msg.answer(welcome, parse_mode="Markdown", reply_markup=kb_enter())

    uid = msg.from_user.id
    if uid not in started_users:
        started_users.add(uid)
        ch = os.getenv("NOTIFY_CHANNEL_INTERACTIONS_ID")
        if ch:
            try:
                ch_id = int(ch)
                u = msg.from_user
                info = (
                    "👤 *Yeni kullanıcı etkileşimi!*\n\n"
                    f"🆔 ID: `{u.id}`\n"
                    f"🪪 Ad: {u.full_name} (@{u.username or '-'})\n"
                    f"🕒 Zaman (UTC): {datetime.utcnow().isoformat()}"
                )
                await bot.send_message(ch_id, info, parse_mode="Markdown")
            except Exception as e:
                logging.warning(f"[start notify] gönderilemedi: {e}")

@router.message(F.text == "/ping")
async def ping(msg: Message):
    await msg.answer("pong")

@router.message(F.text == "/debug")
async def debug(msg: Message):
    await msg.answer(f"uid={msg.from_user.id}\nchat={msg.chat.id}")

# Kilit komutları (şifresiz)
@router.message(F.text.regexp(r"^/mola369$"))
async def cmd_lock(msg: Message):
    global IS_LOCKED
    IS_LOCKED = True
    await msg.reply("🔒 Bot kilitlendi. Yalnızca `/yoladevam` komutu çalışır.", parse_mode="Markdown")

@router.message(F.text.regexp(r"^/yoladevam$"))
async def cmd_unlock(msg: Message):
    global IS_LOCKED
    IS_LOCKED = False
    await msg.reply("✅ Bot tekrar aktif.", parse_mode="Markdown")

# ---------- Akış callback'leri ----------
@router.callback_query(F.data == CB_ENTER)
async def on_enter(cb: CallbackQuery):
    await cb.message.edit_text("Lütfen bulunduğun şehri seç 💫", reply_markup=kb_city())
    await cb.answer()

@router.callback_query(F.data == CB_BACK_ENTER)
async def back_enter(cb: CallbackQuery):
    await cb.message.edit_text("👋 *MushBot* burada!\n\nAşağıdaki butona dokunarak başlayabilirsin.", parse_mode="Markdown", reply_markup=kb_enter())
    await cb.answer()

@router.callback_query(F.data == CB_CITY_IST)
async def on_city(cb: CallbackQuery):
    await cb.message.edit_text("📍 Şehir: *İstanbul*\n\nNe yapmak istersin?", parse_mode="Markdown", reply_markup=kb_menu())
    await cb.answer()

@router.callback_query(F.data == CB_BACK_CITY)
async def back_city(cb: CallbackQuery):
    await cb.message.edit_text("Lütfen bulunduğun şehri seç 💫", reply_markup=kb_city())
    await cb.answer()

@router.callback_query(F.data == CB_SHOW_CATALOG)
async def on_show_catalog(cb: CallbackQuery, bot: Bot):
    if CATALOG_FILE_ID:
        await bot.send_photo(cb.message.chat.id, CATALOG_FILE_ID, caption="🗂️ Katalog")
    elif CATALOG_IMAGE_URL:
        await bot.send_photo(cb.message.chat.id, CATALOG_IMAGE_URL, caption="🗂️ Katalog")
    else:
        await cb.message.answer("🗂️ Katalog görseli hazır değil. /katalog_yukle komutuyla foto ekleyebilirsin.")
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Geri", callback_data=CB_BACK_MENU)
    kb.adjust(1)
    await cb.message.answer("Menüye dönmek için geri tuşunu kullan.", reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data == CB_BACK_MENU)
async def back_menu(cb: CallbackQuery):
    await cb.message.edit_text("📍 Şehir: *İstanbul*\n\nNe yapmak istersin?", parse_mode="Markdown", reply_markup=kb_menu())
    await cb.answer()

@router.callback_query(F.data == CB_SHOW_SHOP)
async def on_show_shop(cb: CallbackQuery):
    await cb.message.edit_text("🛍️ *Ürünler*\n\nBir ürün seçin:", parse_mode="Markdown", reply_markup=kb_products_list())
    await cb.answer()

@router.callback_query(F.data == CB_BACK_SHOP)
async def back_shop(cb: CallbackQuery):
    await cb.message.edit_text("🛍️ *Ürünler*\n\nBir ürün seçin:", parse_mode="Markdown", reply_markup=kb_products_list())
    await cb.answer()

@router.callback_query(F.data.startswith(CB_PRODUCTS_PREFIX))
async def on_product_detail(cb: CallbackQuery):
    pid = cb.data.split(":", 1)[1]
    prod = find_product(pid)
    if not prod:
        await cb.answer("Ürün bulunamadı / stokta yok", show_alert=True)
        return
    addr = get_crypto_address()
    text = (
        f"*{prod['name']}*\n"
        f"{prod['price']}\n\n"
        f"{prod['desc']}\n\n"
        "*Ödeme yöntemi: Sadece KRİPTO*\n"
        "Aşağıdaki cüzdan adresine tutarı gönderin, sonra *Ödeme yaptım* butonuna basın.\n\n"
        "Cüzdan Adresi:\n"
        "```\n"
        f"{addr}\n"
        "```\n"
    )
    if prod.get("photo"):
        await cb.message.answer_photo(prod["photo"], caption=prod["name"])
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb_payment(pid))
    await cb.answer()

# ---------- Ödeme bildirimi (dekont) ----------
@router.callback_query(F.data.startswith(CB_PAID_PREFIX))
async def on_paid_clicked(cb: CallbackQuery, state: FSMContext):
    pid = cb.data.split(":", 1)[1]
    prod = find_product(pid)
    if not prod:
        await cb.answer("Ürün bulunamadı / stokta yok", show_alert=True)
        return
    await state.update_data(selected_product=prod)
    await state.set_state(ExpectReceipt.waiting)
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Geri", callback_data=CB_BACK_DETAIL)
    kb.adjust(1)
    await cb.message.edit_text(
        "🧾 *Ödeme bildirimi*\n\nDekontu *fotoğraf* ya da *dosya* olarak gönderin.\n(İsterseniz işlem hash / txid bilgisini metin olarak da yollayabilirsiniz.)",
        parse_mode="Markdown",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()

@router.callback_query(F.data == CB_BACK_DETAIL)
async def back_detail(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prod = data.get("selected_product")
    await state.clear()
    if prod and find_product(prod.get("id")):
        pid = prod["id"]
        addr = get_crypto_address()
        text = (
            f"*{prod['name']}*\n"
            f"{prod['price']}\n\n"
            f"{prod['desc']}\n\n"
            "*Ödeme yöntemi: Sadece KRİPTO*\n"
            "Aşağıdaki cüzdan adresine tutarı gönderin, sonra *Ödeme yaptım* butonuna basın.\n\n"
            "Cüzdan Adresi:\n"
            "```\n"
            f"{addr}\n"
            "```\n"
        )
        await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb_payment(pid))
    else:
        await cb.message.edit_text("🛍️ *Ürünler*\n\nBir ürün seçin:", parse_mode="Markdown", reply_markup=kb_products_list())
    await cb.answer()

@router.message(ExpectReceipt.waiting, F.photo | F.document | F.text)
async def on_receipt(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    prod = data.get("selected_product", {"id": "?", "name": "?"})
    pay_ch = os.getenv("NOTIFY_CHANNEL_PAYMENTS_ID")
    if not pay_ch:
        await msg.answer("Dekont alındı ama yönlendirme yapılamadı: NOTIFY_CHANNEL_PAYMENTS_ID ayarlı değil.")
        await state.clear()
        return
    try:
        pay_id = int(pay_ch)
    except ValueError:
        await msg.answer("NOTIFY_CHANNEL_PAYMENTS_ID sayısal olmalı.")
        await state.clear()
        return
    order_id = f"ORD-{int(datetime.utcnow().timestamp())}"
    user = msg.from_user
    ORDERS[order_id] = {
        "user_id": user.id,
        "username": user.username,
        "product_id": prod.get("id"),
        "product_name": prod.get("name"),
        "status": "PENDING",
        "created_at": datetime.utcnow().isoformat(),
    }
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Onayla", callback_data=f"{CB_ADMIN_OK_PREFIX}{order_id}")
    kb.button(text="❌ Reddet", callback_data=f"{CB_ADMIN_NO_PREFIX}{order_id}")
    kb.adjust(2)
    info = (
        "📣 *Yeni ödeme bildirimi*\n\n"
        f"Sipariş: `{order_id}`\n"
        f"Ürün: *{prod.get('name')}* (id: `{prod.get('id')}`)\n"
        f"Kullanıcı: `{user.id}` @{user.username or '-'} {user.full_name}\n"
        f"Durum: *PENDING*\n"
        f"Tarih (UTC): {datetime.utcnow().isoformat()}\n"
        "Dekont aşağıda kopyalandı."
    )
    await bot.send_message(pay_id, info, parse_mode="Markdown", reply_markup=kb.as_markup())
    try:
        await bot.copy_message(chat_id=pay_id, from_chat_id=msg.chat.id, message_id=msg.message_id)
    except Exception as e:
        await bot.send_message(pay_id, f"[Hata] Dekont kopyalanamadı: {e}")
    await msg.answer("✅ Dekont alındı.\n" f"Sipariş No: {order_id}\n" "Manuel kontrol sonrası bilgilendirileceksiniz.")
    await state.clear()

# ---------- Admin onay / red ----------
@router.callback_query(F.data.startswith(CB_ADMIN_OK_PREFIX))
async def admin_ok(cb: CallbackQuery, bot: Bot):
    order_id = cb.data.split(":", 1)[1]
    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("Sipariş bulunamadı.", show_alert=True)
        return
    order["status"] = "APPROVED"
    pid = order.get("product_id")
    removed = remove_product_by_id(pid) if pid else False
    try:
        await bot.send_message(order["user_id"], f"🎉 Ödemeniz onaylandı!\nSipariş No: {order_id}")
    except Exception:
        pass
    repl = (cb.message.text or "").replace("Durum: *PENDING*", "Durum: *APPROVED*")
    if removed:
        repl += "\n\n🗑️ Ürün stoktan düşüldü."
    try:
        await cb.message.edit_text(repl or "APPROVED", parse_mode="Markdown")
    except Exception:
        pass
    await cb.answer("Onaylandı. Ürün stoktan düşüldü." if removed else "Onaylandı.")

@router.callback_query(F.data.startswith(CB_ADMIN_NO_PREFIX))
async def admin_no(cb: CallbackQuery, bot: Bot):
    order_id = cb.data.split(":", 1)[1]
    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("Sipariş bulunamadı.", show_alert=True)
        return
    order["status"] = "REJECTED"
    try:
        await bot.send_message(order["user_id"], f"❌ Ödemeniz doğrulanamadı / reddedildi.\nSipariş No: {order_id}")
    except Exception:
        pass
    repl = (cb.message.text or "").replace("Durum: *PENDING*", "Durum: *REJECTED*")
    try:
        await cb.message.edit_text(repl or "REJECTED", parse_mode="Markdown")
    except Exception:
        pass
    await cb.answer("Reddedildi.")

# ---------- Katalog yükleme ----------
@router.message(F.text == "/katalog_yukle")
async def catalog_upload_start(msg: Message):
    await msg.answer("📸 Katalog fotoğrafını bu sohbete gönder. Gönderince file_id kaydedilecek; kalıcı olması için ENV'e ekleyin.")

@router.message(F.photo)
async def catalog_photo(msg: Message):
    global CATALOG_FILE_ID
    photo = msg.photo[-1]
    CATALOG_FILE_ID = photo.file_id
    await msg.answer(f"✅ Katalog görseli kaydedildi.\nfile_id: `{CATALOG_FILE_ID}`\nENV'e kaydetmeyi unutmayın.", parse_mode="Markdown")

# ---------- Basit ticket ----------
@router.callback_query(F.data == CB_OPEN_TICKET_SIMPLE)
async def open_ticket_simple(cb: CallbackQuery, bot: Bot):
    pay_ch = os.getenv("NOTIFY_CHANNEL_PAYMENTS_ID")
    if pay_ch:
        try:
            pay_id = int(pay_ch)
            u = cb.from_user
            text = (
                "🎫 *Toplu Alım Talebi*\n\n"
                f"Kullanıcı: `{u.id}` @{u.username or '-'} {u.full_name}\n"
                f"Zaman (UTC): {datetime.utcnow().isoformat()}\n"
                "_Kullanıcı ticket butonuna bastı. Lütfen DM ile iletişime geçin._"
            )
            await bot.send_message(pay_id, text, parse_mode="Markdown")
        except Exception as e:
            logging.warning(f"Ticket bildirimi gönderilemedi: {e}")
    await cb.answer("Talebin iletildi. Ekip seninle iletişime geçecek.")

# ---------- Main ----------
async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN ortam değişkeni ayarlı değil.")
    # aiogram 3.7+ uyumu: parse_mode doğrudan verilmez, DefaultBotProperties kullanılır
    bot = Bot(token, default=DefaultBotProperties(parse_mode="Markdown"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"Webhook silme hatası: {e}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("MushBot durduruldu.")
    except Exception as e:
        print(f"MushBot kritik hata: {e}")
