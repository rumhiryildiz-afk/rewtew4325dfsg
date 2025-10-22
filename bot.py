#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mantar Madeni — Çalıştırmaya hazır tek dosya (aiogram v3.7+)

Kullanım:
- Ortam değişkenleri: BOT_TOKEN, CRYPTO_ADDRESS, NOTIFY_CHANNEL_PAYMENTS_ID
- Başlatma: python bot.py
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- Konfig ---
DATA_FILE = Path("products.json")
IS_LOCKED = False
router = Router()
started_users: Set[int] = set()
ORDERS: Dict[str, Dict[str, Any]] = {}

# Default admin id set (gerekirse ENV'den ekleyin)
DEFAULT_ADMIN_IDS = {8128551234}
ENV_ADMIN = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: Set[int] = set(DEFAULT_ADMIN_IDS)
if ENV_ADMIN:
    for part in ENV_ADMIN.split(","):
        part = part.strip()
        if part.isdigit():
            ADMIN_IDS.add(int(part))

CATALOG_FILE_ID: Optional[str] = os.getenv("KATALOG_IMAGE_FILE_ID")
CATALOG_IMAGE_URL: Optional[str] = os.getenv("KATALOG_IMAGE_URL")

BTN_ENTER = "Mantar Madeni’nin renkli dünyasına giriş yap 🎭"
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

CB_BACK_ENTER = "back_enter"
CB_BACK_CITY = "back_city"
CB_BACK_MENU = "back_menu"
CB_BACK_SHOP = "back_shop"
CB_BACK_DETAIL = "back_detail"

TRX_TAMPON_ORANI = 0.015  # %1.5 tampon

# Ürün şablonları (template_id ile referans)
PRODUCT_TEMPLATES = {
    1: {"name": "Mikrodoz Kapsül", "desc": "💊 Günlük denge, odak ve huzur.\n🌿 Dengeli içerik; berraklık ve sakinlik.", "unit_hint": "kutu"},
    2: {"name": "Pink Buffalo", "desc": "🐃 Karakteristik bir profil.\n🌈 Yoğun görsel ve farkındalık odaklı deneyim.", "unit_hint": "gr"},
    3: {"name": "Golden Teacher", "desc": "👁️ Klasik ve ‘öğretici’ profil.\n🕊️ İçsel yolculuk ve nazik ama derin etki.", "unit_hint": "gr"},
    4: {"name": "Mantar Çikolata", "desc": "🍫 Bitter taban; dengeli bir form.\n✨ Her kare sakinlik ve farkındalık anları sunabilir.", "unit_hint": "bar"},
}

@dataclass
class Listing:
    listing_id: str
    template_id: int
    unit: str
    location: str
    price_tl: int
    created_at: str
    product_name: str
    product_desc: str

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_listings() -> List[Listing]:
    if DATA_FILE.exists():
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            return [Listing(**item) for item in raw]
        except Exception as e:
            logging.warning(f"products.json okunamadı ({e}); boş liste ile devam.")
    return []

def save_listings(items: List[Listing]) -> None:
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(x) for x in items], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)

LISTINGS: List[Listing] = load_listings()

def add_listing(item: Listing) -> None:
    LISTINGS.append(item)
    save_listings(LISTINGS)

def remove_listing(listing_id: str) -> bool:
    global LISTINGS
    before = len(LISTINGS)
    LISTINGS = [x for x in LISTINGS if x.listing_id != listing_id]
    if len(LISTINGS) != before:
        save_listings(LISTINGS)
        return True
    return False

def find_listing(listing_id: str) -> Optional[Listing]:
    for it in LISTINGS:
        if it.listing_id == listing_id:
            return it
    return None

async def fetch_trx_try_rate() -> Optional[float]:
    url = "https://api.coingecko.com/api/v3/simple/price?ids=tron&vs_currencies=try"
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    val = data.get("tron", {}).get("try")
                    if isinstance(val, (int, float)) and val > 0:
                        return float(val)
    except Exception as e:
        logging.warning(f"TRX kuru çekilemedi: {e}")
    return None

async def calc_trx_amount(price_tl: int) -> Dict[str, Any]:
    rate = await fetch_trx_try_rate()
    source = "live"
    if rate is None:
        env_rate = os.getenv("TRX_TRY_RATE")
        if env_rate:
            try:
                rate = float(env_rate); source = "env"
            except:
                rate = None
    if rate is None or rate <= 0:
        return {"ok": False}
    trx = price_tl / rate
    trx *= (1 + TRX_TAMPON_ORANI)
    trx_amt = f"{trx:.6f}"
    return {"ok": True, "rate": rate, "rate_source": source, "trx_amount": trx_amt,
            "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}

class ExpectReceipt(StatesGroup):
    waiting = State()

# --- Klavye oluşturucular ---
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

def listing_button_text(it: Listing) -> str:
    if it.template_id == 4:
        return f"{it.product_name} — {it.location} ({it.price_tl} TL)"
    unit = it.unit.replace("_", " ")
    return f"{unit} {it.product_name} — {it.location} ({it.price_tl} TL)"

def kb_products_list() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if LISTINGS:
        for it in LISTINGS:
            kb.button(text=listing_button_text(it), callback_data=f"{CB_PRODUCTS_PREFIX}{it.listing_id}")
    else:
        kb.button(text="(Şu an listede ürün yok)", callback_data="noop")
    kb.button(text="⬅️ Geri", callback_data=CB_BACK_MENU)
    kb.adjust(1)
    return kb.as_markup()

def kb_payment(listing_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ödeme yaptım", callback_data=f"{CB_PAID_PREFIX}{listing_id}")
    kb.button(text="⬅️ Geri", callback_data=CB_BACK_SHOP)
    kb.adjust(1)
    return kb.as_markup()

# --- Komutlar ve callback'ler ---
@router.message(CommandStart())
async def on_start(msg: Message):
    if IS_LOCKED:
        return
    welcome = "👋 Mantar Madeni’ne hoş geldin!\n\nAşağıdaki butona dokunarak başlayabilirsin."
    await msg.answer(welcome, reply_markup=kb_enter())
    started_users.add(msg.from_user.id)

@router.message(F.text == "/ping")
async def ping(msg: Message):
    if IS_LOCKED:
        return
    await msg.answer("pong")

@router.message(F.text == "/debug")
async def debug(msg: Message):
    if IS_LOCKED:
        return
    await msg.answer(f"uid={msg.from_user.id}\nchat={msg.chat.id}")

@router.message(F.text.regexp(r"^/mola369$"))
async def cmd_lock(msg: Message):
    global IS_LOCKED
    IS_LOCKED = True
    await msg.reply("Bot devre dışı bırakıldı.")

@router.message(F.text.regexp(r"^/yoladevam$"))
async def cmd_unlock(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    global IS_LOCKED
    IS_LOCKED = False
    await msg.reply("Bot tekrar aktif edildi.")

@router.callback_query(F.data == CB_ENTER)
async def on_enter(cb: CallbackQuery):
    if IS_LOCKED:
        return
    await cb.message.edit_text("Lütfen bulunduğun şehri seç 💫", reply_markup=kb_city())
    await cb.answer()

@router.callback_query(F.data == CB_BACK_ENTER)
async def back_enter(cb: CallbackQuery):
    if IS_LOCKED:
        return
    await cb.message.edit_text("👋 Mantar Madeni’ne hoş geldin!\n\nAşağıdaki butona dokunarak başlayabilirsin.", reply_markup=kb_enter())
    await cb.answer()

@router.callback_query(F.data == CB_CITY_IST)
async def on_city(cb: CallbackQuery):
    if IS_LOCKED:
        return
    await cb.message.edit_text("📍 Şehir: *İstanbul*\n\nNe yapmak istersin?", parse_mode="Markdown", reply_markup=kb_menu())
    await cb.answer()

@router.callback_query(F.data == CB_BACK_CITY)
async def back_city(cb: CallbackQuery):
    if IS_LOCKED:
        return
    await cb.message.edit_text("Lütfen bulunduğun şehri seç 💫", reply_markup=kb_city())
    await cb.answer()

@router.callback_query(F.data == CB_SHOW_CATALOG)
async def on_show_catalog(cb: CallbackQuery, bot: Bot):
    if IS_LOCKED:
        return
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
    if IS_LOCKED:
        return
    await cb.message.edit_text("📍 Şehir: *İstanbul*\n\nNe yapmak istersin?", parse_mode="Markdown", reply_markup=kb_menu())
    await cb.answer()

@router.callback_query(F.data == CB_SHOW_SHOP)
async def on_show_shop(cb: CallbackQuery):
    if IS_LOCKED:
        return
    await cb.message.edit_text("🛍️ *Ürünler*\n\nBir ürün seçin:", parse_mode="Markdown", reply_markup=kb_products_list())
    await cb.answer()

@router.callback_query(F.data == CB_BACK_SHOP)
async def back_shop(cb: CallbackQuery):
    if IS_LOCKED:
        return
    await cb.message.edit_text("🛍️ *Ürünler*\n\nBir ürün seçin:", parse_mode="Markdown", reply_markup=kb_products_list())
    await cb.answer()

@router.callback_query(F.data.startswith(CB_PRODUCTS_PREFIX))
async def on_product_detail(cb: CallbackQuery):
    if IS_LOCKED:
        return
    listing_id = cb.data.split(":", 1)[1]
    it = find_listing(listing_id)
    if not it:
        await cb.answer("Ürün bulunamadı / stokta yok", show_alert=True)
        return

    trx_info = await calc_trx_amount(it.price_tl)
    trx_block = ""
    if trx_info.get("ok"):
        trx_block = (
            f"\n🔄 Anlık kur: 1 TRX ≈ ₺{trx_info['rate']:.2f} ({trx_info['rate_source']})"
            f"\n📊 Gönderilecek miktar: ≈{trx_info['trx_amount']} TRX"
            f"\n🕒 Kur zamanı: {trx_info['ts']}\n"
        )

    addr = os.getenv("CRYPTO_ADDRESS", "(CRYPTO_ADDRESS ortam değişkenini ayarlayın)")
    title = f"{it.product_name} — {it.location}"
    if it.template_id != 4:
        title = f"{it.unit} {title}"

    text = (
        f"*{title}*\n"
        f"💰 Fiyat: {it.price_tl} TL"
        f"{trx_block}\n"
        f"{it.product_desc}\n\n"
        "💸 *Ödeme yöntemi: Sadece KRİPTO*\n"
        "Cüzdan Adresi:\n"
        "```\n"
        f"{addr}\n"
        "```\n"
    )
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb_payment(it.listing_id))
    await cb.answer()

@router.callback_query(F.data.startswith(CB_PAID_PREFIX))
async def on_paid_clicked(cb: CallbackQuery, state: FSMContext):
    if IS_LOCKED:
        return
    listing_id = cb.data.split(":", 1)[1]
    it = find_listing(listing_id)
    if not it:
        await cb.answer("Ürün bulunamadı / stokta yok", show_alert=True)
        return
    await state.update_data(listing_id=listing_id)
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
    if IS_LOCKED:
        return
    data = await state.get_data()
    listing_id = data.get("listing_id")
    await state.clear()
    it = find_listing(listing_id) if listing_id else None
    if it:
        trx_info = await calc_trx_amount(it.price_tl)
        trx_block = ""
        if trx_info.get("ok"):
            trx_block = (
                f"\n🔄 Anlık kur: 1 TRX ≈ ₺{trx_info['rate']:.2f} ({trx_info['rate_source']})"
                f"\n📊 Gönderilecek miktar: ≈{trx_info['trx_amount']} TRX"
                f"\n🕒 Kur zamanı: {trx_info['ts']}\n"
            )
        addr = os.getenv("CRYPTO_ADDRESS", "(CRYPTO_ADDRESS ayarlanmalı)")
        title = f"{it.product_name} — {it.location}"
        if it.template_id != 4:
            title = f"{it.unit} {title}"
        text = (
            f"*{title}*\n"
            f"💰 Fiyat: {it.price_tl} TL"
            f"{trx_block}\n"
            f"{it.product_desc}\n\n"
            "💸 *Ödeme yöntemi: Sadece KRİPTO*\n"
            "Cüzdan Adresi:\n"
            "```\n"
            f"{addr}\n"
            "```\n"
        )
        await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb_payment(it.listing_id))
    else:
        await cb.message.edit_text("🛍️ *Ürünler*\n\nBir ürün seçin:", parse_mode="Markdown", reply_markup=kb_products_list())
    await cb.answer()

@router.message(ExpectReceipt.waiting, F.photo | F.document | F.text)
async def on_receipt(msg: Message, state: FSMContext, bot: Bot):
    if IS_LOCKED:
        return
    data = await state.get_data()
    listing_id = data.get("listing_id")
    it = find_listing(listing_id) if listing_id else None
    if not it:
        await state.clear()
        return

    pay_ch = os.getenv("NOTIFY_CHANNEL_PAYMENTS_ID")
    if not pay_ch:
        await msg.answer("Dekont alındı; ancak yönetim kanalına iletilemedi (NOTIFY_CHANNEL_PAYMENTS_ID ayarlanmalı).")
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
        "listing_id": listing_id,
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
        f"İlân: `{listing_id}`\n"
        f"Ürün: *{listing_button_text(it)}*\n"
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

    await msg.answer("✅ Dekont alındı.\nManuel kontrol sonrası bilgilendirileceksiniz.")
    await state.clear()

@router.callback_query(F.data.startswith(CB_ADMIN_OK_PREFIX))
async def admin_ok(cb: CallbackQuery, bot: Bot):
    if IS_LOCKED:
        return
    order_id = cb.data.split(":", 1)[1]
    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("Sipariş bulunamadı.", show_alert=True)
        return

    ORDERS[order_id]["status"] = "APPROVED"
    listing_id = order.get("listing_id")
    it = find_listing(listing_id) if listing_id else None

    try:
        await bot.send_message(
            order["user_id"],
            "🎉 Ödemen doğrulandı!\n\n"
            f"Sipariş No: {order_id}\n"
            f"Ürün: {listing_button_text(it) if it else listing_id}\n"
            "Durum: ✅ Onaylandı\n"
            "Teşekkürler, teslim süreci başlatıldı. 🍄\n"
            "🕒 *Teslimat bilgileri 24 saat içinde konumla birlikte iletilecektir.*"
        )
    except Exception:
        pass

    new_text = (cb.message.text or "").replace("Durum: *PENDING*", "Durum: *APPROVED*")
    try:
        await cb.message.edit_text(new_text or "APPROVED", parse_mode="Markdown")
    except Exception:
        pass

    if listing_id:
        remove_listing(listing_id)

    await cb.answer("Onaylandı.")

@router.callback_query(F.data.startswith(CB_ADMIN_NO_PREFIX))
async def admin_no(cb: CallbackQuery, bot: Bot):
    if IS_LOCKED:
        return
    order_id = cb.data.split(":", 1)[1]
    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("Sipariş bulunamadı.", show_alert=True)
        return

    ORDERS[order_id]["status"] = "REJECTED"

    try:
        await bot.send_message(
            order["user_id"],
            "❌ Ödemen doğrulanamadı / reddedildi.\n"
            f"Sipariş No: {order_id}\n"
            "Lütfen dekontu ve işlem bilgilerini kontrol ederek tekrar gönder."
        )
    except Exception:
        pass

    new_text = (cb.message.text or "").replace("Durum: *PENDING*", "Durum: *REJECTED*")
    try:
        await cb.message.edit_text(new_text or "REJECTED", parse_mode="Markdown")
    except Exception:
        pass
    await cb.answer("Reddedildi.")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@router.message(F.text.startswith("/ekle"))
async def add_item(msg: Message):
    if IS_LOCKED:
        return
    if not is_admin(msg.from_user.id):
        return
    text = (msg.text or "").strip()
    # Beklenen format: /ekle{template}_{location}_{unit}_{price}
    m = re.fullmatch(r"/ekle([1-4])_([^_]+)_([^_]+)_([0-9]+)", text)
    if not m:
        return
    template_id = int(m.group(1))
    location = m.group(2)  # <- DÜZELTİLDİ
    unit = m.group(3)
    price_str = m.group(4)
    try:
        price_tl = int(price_str)
    except ValueError:
        return
    tmpl = PRODUCT_TEMPLATES.get(template_id)
    if not tmpl:
        return
    listing_id = f"L{template_id}-{int(datetime.utcnow().timestamp())}"
    item = Listing(
        listing_id=listing_id,
        template_id=template_id,
        unit=unit,
        location=location.replace("-", " ").title(),
        price_tl=price_tl,
        created_at=now_utc_iso(),
        product_name=tmpl["name"],
        product_desc=tmpl["desc"],
    )
    add_listing(item)
    await msg.reply(f"✅ Eklendi: {listing_button_text(item)}\n(id: `{listing_id}`)", parse_mode="Markdown")

@router.message(F.text.regexp(r"^/duyuru_.+"))
async def announce_text(msg: Message, bot: Bot):
    if IS_LOCKED:
        return
    if not is_admin(msg.from_user.id):
        return
    content = msg.text.split("_", 1)[1].strip()
    sent, errs = 0, 0
    for uid in list(started_users):
        try:
            await bot.send_message(uid, content)
            sent += 1
            await asyncio.sleep(0.35)
        except Exception:
            errs += 1
    await msg.reply(f"📣 Duyuru gönderildi: {sent} ok, {errs} hata.")

@router.message(F.text == "/duyuru")
async def announce_media_help(msg: Message):
    if IS_LOCKED:
        return
    if not is_admin(msg.from_user.id):
        return
    await msg.reply("Bir *fotoğraf mesajına yanıt* olarak /duyuru yazarsan görsel olarak gönderirim.", parse_mode="Markdown")

@router.message(F.reply_to_message, F.text == "/duyuru")
async def announce_media(msg: Message, bot: Bot):
    if IS_LOCKED:
        return
    if not is_admin(msg.from_user.id):
        return
    ref = msg.reply_to_message
    sent, errs = 0, 0
    for uid in list(started_users):
        try:
            if ref.photo:
                ph = ref.photo[-1].file_id
                await bot.send_photo(uid, ph, caption=(ref.caption or ""))
            elif ref.document:
                await bot.send_document(uid, ref.document.file_id, caption=(ref.caption or ""))
            else:
                await bot.send_message(uid, ref.text or "")
            sent += 1
            await asyncio.sleep(0.35)
        except Exception:
            errs += 1
    await msg.reply(f"📣 Duyuru gönderildi: {sent} ok, {errs} hata.")

@router.message(F.text == "/katalog_yukle")
async def catalog_upload_start(msg: Message):
    if IS_LOCKED:
        return
    if not is_admin(msg.from_user.id):
        return
    await msg.answer("📸 Katalog fotoğrafını bu sohbete gönder. Gönderince file_id'yi bildireceğim; istersen ENV'e ekleyip kalıcı yap.")

@router.message(F.photo)
async def catalog_photo(msg: Message):
    if IS_LOCKED:
        return
    if not is_admin(msg.from_user.id):
        return
    global CATALOG_FILE_ID
    photo = msg.photo[-1]
    CATALOG_FILE_ID = photo.file_id
    await msg.answer(f"✅ Katalog görseli kaydedildi.\nfile_id: `{CATALOG_FILE_ID}`\nKalıcı yapmak için ENV'e `KATALOG_IMAGE_FILE_ID` olarak ekleyebilirsin.", parse_mode="Markdown")

@router.callback_query(F.data == CB_OPEN_TICKET_SIMPLE)
async def open_ticket_simple(cb: CallbackQuery, bot: Bot):
    if IS_LOCKED:
        return
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
    await cb.answer("Talebin iletildi.")

@router.message(lambda m: IS_LOCKED)
async def locked_block_messages(msg: Message):
    return

@router.callback_query(lambda c: IS_LOCKED)
async def locked_block_callbacks(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass

async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN ortam değişkeni ayarlı değil.")
    bot = Bot(token, default=DefaultBotProperties(parse_mode="Markdown"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"Webhook silme: {e}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot durduruldu.")
