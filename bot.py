"""
    await cb.message.edit_text(text, reply_markup=make_payment_kb(prod_id), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith(CB_PAID_PREFIX))
async def on_paid_clicked(cb: CallbackQuery, state: FSMContext):
    prod_id = cb.data.split(":", 1)[1]
    prod = next((p for p in PRODUCTS if p["id"] == prod_id), None)
    if not prod:
        await cb.answer("Ürün bulunamadı", show_alert=True)
        return

    await state.update_data(selected_product=prod)
    await state.set_state(ExpectReceipt.waiting)

    await cb.message.edit_text(
        "🧾 *Ödeme bildirimi*\n\n"
        "Lütfen dekontu *fotoğraf* ya da *dosya* olarak gönderin.\n"
        "(İsterseniz işlem hash / txid bilgisini metin olarak da yollayabilirsiniz.)",
        parse_mode="Markdown",
    )
    await cb.answer()


@router.message(ExpectReceipt.waiting, F.photo | F.document | F.text)
async def on_receipt(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    prod = data.get("selected_product", {"id": "?", "name": "?"})

    pay_id_str = os.getenv("NOTIFY_CHANNEL_PAYMENTS_ID")
    if not pay_id_str:
        await msg.answer("Dekont alındı ama yönlendirme yapılamadı: NOTIFY_CHANNEL_PAYMENTS_ID ayarlı değil.")
        await state.clear()
        return

    try:
        pay_id = int(pay_id_str)
    except ValueError:
        await msg.answer("NOTIFY_CHANNEL_PAYMENTS_ID sayısal bir değer olmalı.")
        await state.clear()
        return

    order_id = f"ORD-{int(datetime.utcnow().timestamp())}"
    user = msg.from_user

    # Order kaydı (run içi)
    ORDERS[order_id] = {
        "user_id": user.id,
        "username": user.username,
        "product_id": prod.get("id"),
        "product_name": prod.get("name"),
        "status": "PENDING",
        "created_at": datetime.utcnow().isoformat(),
    }

    # Admin kanalına bilgi + Onayla/Reddet
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Onayla", callback_data=f"admin_ok:{order_id}")
    kb.button(text="❌ Reddet", callback_data=f"admin_no:{order_id}")
    kb.adjust(2)

    info_text = (
        "📣 *Yeni ödeme bildirimi*\n\n"
        f"Sipariş: `{order_id}`\n"
        f"Ürün: *{prod['name']}* (id: `{prod['id']}`)\n"
        f"Kullanıcı: `{user.id}` @{user.username or '-'} {user.full_name}\n"
        f"Durum: *PENDING*\n"
        f"Tarih (UTC): {datetime.utcnow().isoformat()}\n"
        "Dekont aşağıda kopyalandı."
    )
    await bot.send_message(pay_id, info_text, parse_mode="Markdown", reply_markup=kb.as_markup())

    try:
        await bot.copy_message(chat_id=pay_id, from_chat_id=msg.chat.id, message_id=msg.message_id)
    except Exception as e:
        await bot.send_message(pay_id, f"[Hata] Dekont kopyalanamadı: {e}")

    await msg.answer(
        "✅ Dekont alındı.\n"
        f"Sipariş No: {order_id}\n"
        "Ekibimiz manuel kontrol ettikten sonra onay/ret bilgisi gönderilecektir."
    )
    await state.clear()


# ---- Admin onay/red ----
@router.callback_query(F.data.startswith("admin_ok:"))
async def admin_approve(cb: CallbackQuery, bot: Bot):
    order_id = cb.data.split(":", 1)[1]
    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("Sipariş bulunamadı.", show_alert=True)
        return

    order["status"] = "APPROVED"
    try:
        await bot.send_message(
            order["user_id"],
            "🎉 Ödemeniz onaylandı!\n"
            f"Sipariş No: {order_id}\n"
            "Teşekkürler — ürün teslim sürecine geçiyoruz."
        )
    except Exception as e:
        await cb.message.answer(f"[Uyarı] Kullanıcıya mesaj gönderilemedi: {e}")

    new_text = (cb.message.text or "").replace("Durum: *PENDING*", "Durum: *APPROVED*")
    await cb.message.edit_text(new_text or "APPROVED", parse_mode="Markdown")
    await cb.answer("Onaylandı.")


@router.callback_query(F.data.startswith("admin_no:"))
async def admin_reject(cb: CallbackQuery, bot: Bot):
    order_id = cb.data.split(":", 1)[1]
    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("Sipariş bulunamadı.", show_alert=True)
        return

    order["status"] = "REJECTED"
    try:
        await bot.send_message(
            order["user_id"],
            "❌ Ödemeniz doğrulanamadı / reddedildi.\n"
            f"Sipariş No: {order_id}\n"
            "Lütfen dekontu ve işlem bilgilerini kontrol ederek tekrar gönderin."
        )
    except Exception as e:
        await cb.message.answer(f"[Uyarı] Kullanıcıya mesaj gönderilemedi: {e}")

    new_text = (cb.message.text or "").replace("Durum: *PENDING*", "Durum: *REJECTED*")
    await cb.message.edit_text(new_text or "REJECTED", parse_mode="Markdown")
    await cb.answer("Reddedildi.")


# --------- Main ---------
async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN ortam değişkeni ayarlı değil.")
    masked = token[:6] + "..." + token[-4:]
    logging.info(f"BOT_TOKEN yüklendi: {masked}")

    bot = Bot(token)
    dp = Dispatcher()
    dp.include_router(router)

    me = await bot.get_me()
    logging.info(f"MushBot başlıyor… Bot username: @{me.username}, id: {me.id}")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook (varsa) silindi, polling'e geçiliyor.")
    except Exception as e:
        logging.warning(f"Webhook silme denemesi hata: {e}")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.exception(f"start_polling istisna verdi: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("MushBot durduruldu.")
    except Exception as e:
        print(f"MushBot kritik hata: {e}\nEnv keys: {list(os.environ.keys())}")
