"""/start, onboarding, join-gate, and main-menu text routing."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.bot import ui
from app.bot.handlers.common import missing_channels, missing_channels_detailed
from app.config import settings
from app.services.earning import get_or_create_user

router = Router(name="start")


def _parse_ref(text: str | None) -> int | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    arg = parts[1].strip()
    return int(arg) if arg.isdigit() else None


async def _send_home(message: Message, user_id: int, first_name: str | None) -> None:
    is_admin = settings.is_admin(user_id)
    caption = ui.welcome(first_name)
    banner = kb.app_banner_url()
    sent = False
    if banner:
        try:
            await message.answer_photo(banner, caption=caption, reply_markup=kb.main_menu(is_admin))
            sent = True
        except Exception:  # noqa: BLE001
            sent = False
    if not sent:
        await message.answer(caption, reply_markup=kb.main_menu(is_admin))

    inline = kb.open_app_inline()
    if inline:
        await message.answer(
            "👇 Tap below to open the app — your wallet, tasks, invites and "
            "withdrawals, all in one place.",
            reply_markup=inline,
        )


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    u = message.from_user
    referred_by = _parse_ref(message.text)
    user = await get_or_create_user(u.id, u.username, u.first_name, referred_by)

    # Join gate
    missing = await missing_channels(bot, u.id)
    if missing:
        await message.answer(
            "🔓 <b>Join to unlock</b>\n\n"
            "Please join the channel(s) below, then tap <b>I've Joined</b>.",
            reply_markup=kb.join_gate(missing),
        )
        return

    await _send_home(message, u.id, u.first_name)
    if not user.wallet_address:
        await message.answer(ui.need_wallet())


@router.callback_query(F.data == "gate:check")
async def gate_check(cb: CallbackQuery, bot: Bot) -> None:
    detailed = await missing_channels_detailed(bot, cb.from_user.id)
    if detailed:
        # User-facing: just name the channel(s) still to join — no raw status
        # or admin hints (those are diagnostics, see /checkadmin for admins).
        names = ", ".join(c for c, _ in detailed)
        await cb.answer(
            f"We couldn't confirm you joined {names} yet. "
            "Make sure you've joined, then tap ✅ I've Joined again.",
            show_alert=True,
        )
        return
    await cb.message.delete()
    await cb.answer("Verified ✅")
    await _send_home(cb.message, cb.from_user.id, cb.from_user.first_name)
    user = await get_or_create_user(
        cb.from_user.id, cb.from_user.username, cb.from_user.first_name, None
    )
    if not user.wallet_address:
        await cb.message.answer(ui.need_wallet())


@router.message(F.text == kb.BTN_HELP)
async def help_handler(message: Message) -> None:
    await message.answer(ui.help_text())


@router.message(F.text == "🛠️ Admin")
async def admin_menu_hint(message: Message) -> None:
    if not settings.is_admin(message.from_user.id):
        return
    await message.answer("🛠️ Admin — use /stats, /pending, /fund to manage the bot.")
