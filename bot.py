import asyncio
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from dateutil import parser as date_parser
from database import init_db, add_homework, get_all_homework, get_homework_by_id, update_homework, delete_homework
from config import BOT_TOKEN

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния редактирования ДЗ
class EditHomework(StatesGroup):
    waiting_for_field = State()      # Ждём выбор поля (предмет/задание/дата)
    waiting_for_value = State()      # Ждём новое значение

# Временное хранилище: какой ДЗ сейчас редактируем
editing_homework_id = {}

# Главное меню (постоянная клавиатура внизу)
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Мои ДЗ")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True,  # Делает кнопки компактными
    input_field_placeholder="Выберите действие..."
)

# Парсит дату #
def parse_date(date_str: str) -> datetime:
    """Парсит дату из текста"""
    date_str = date_str.strip()

    # Пробуем форматы по порядку
    formats = [
        "%d.%m.%Y",  # 09.10.2026
        "%d.%m",  # 09.10
        "%d/%m/%Y",  # 09/10/2026
        "%d/%m",  # 09/10
    ]

    for fmt in formats:
        try:
            date = datetime.strptime(date_str, fmt)
            # Если год не указан, берём текущий
            if date.year == 1900:
                date = date.replace(year=datetime.now().year)
            return date
        except ValueError:
            continue

    # Если ничего не подошло — возвращаем None
    return None

# Парсит текст #

def parse_homework_text(text: str):
    """
    Умный парсер текста ДЗ.
    Поддерживает форматы:
    - "Предмет: Задание, до ДД.ММ"
    - "Предмет: Задание 1-4, до ДД.ММ"
    - "Предмет: Задание. ДД.ММ"
    """
    text = text.strip()

    # Ищем двоеточие (разделитель предмета)
    colon_pos = text.find(':')
    if colon_pos == -1:
        return None

    subject = text[:colon_pos].strip()
    rest = text[colon_pos + 1:].strip()

    if not subject or not rest:
        return None

    # Ищем дату в конце (ДД.ММ или ДД.ММ.ГГГГ)
    date_pattern = r'(\d{2}[./]\d{2}(?:[./]\d{4})?)\s*$'
    date_match = re.search(date_pattern, rest)

    if not date_match:
        return None

    date_str = date_match.group(1)
    deadline = parse_date(date_str)

    if not deadline:
        return None

    # Всё, что перед датой — это задание
    task = rest[:date_match.start()].strip()

    # Убираем "до" или "до:" в конце задания
    task = re.sub(r',?\s*до\s*:?\s*$', '', task).strip()

    # Убираем лишние запятые/точки в конце
    task = task.rstrip(',. ').strip()

    if not task:
        return None

    return subject, task, deadline

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    text = (
        "👋 <b>Привет! Я твой ДЗ-помощник</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 <b>Как добавить ДЗ:</b>\n"
        "<code>Предмет: Задание, до ДД.ММ</code>\n\n"
        "💡 <b>Пример:</b>\n"
        "<code>Математика: №123-125, до 08.10</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📋 <b>Команды:</b>\n"
        "/homework — Список всех ДЗ\n"
        "/help — Помощь\n\n"
        "🚀 Поехали!"
    )
    await message.answer(text, reply_markup=main_keyboard, parse_mode="HTML")

# Обработчик команды /homework
@dp.message(Command("homework"))
async def cmd_homework(message: types.Message):
    homework_list = await get_all_homework()

    if not homework_list:
        await message.answer(
            "🎉 <b>Ура!</b>\n\n"
            "У тебя нет невыполненных домашних заданий.\n"
            "Можно отдохнуть или добавить новое ДЗ 😉",
            parse_mode="HTML"
        )
        return

    text = "📚 <b>Твои домашние задания</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    keyboard = []
    for i, hw in enumerate(homework_list, 1):
        # Считаем, сколько дней осталось
        days_left = (hw.deadline - datetime.now()).days

        # Выбираем цвет индикатора
        if days_left < 0:
            urgency = "🔴 ПРОСРОЧЕНО"
        elif days_left == 0:
            urgency = "🟠 СЕГОДНЯ"
        elif days_left == 1:
            urgency = "🟡 ЗАВТРА"
        else:
            urgency = f"🟢 через {days_left} дн."

        # Формируем текст для одного ДЗ
        text += f"<b>{i}. {hw.subject}</b>  {urgency}\n"
        text += f"📝 {hw.task}\n"
        text += f"📅 <code>{hw.deadline.strftime('%d.%m.%Y')}</code>\n"
        text += "──────────────────────\n"

        # Кнопки для этого ДЗ
        keyboard.append([
            InlineKeyboardButton(text="✅ Готово", callback_data=f"done_{hw.id}"),
            InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{hw.id}"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit_{hw.id}")
        ])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )

# Обработчик добавления ДЗ (обычное сообщение)
@dp.message(F.text & ~F.text.startswith('/') & ~F.text.in_({"📋 Мои ДЗ", "❓ Помощь"}))
async def handle_homework(message: types.Message):
    # Если это текст кнопки — игнорируем
    if message.text in {"📋 Мои ДЗ", "❓ Помощь"}:
        return

    parsed = parse_homework_text(message.text)

    if not parsed:
        await message.answer(
            "❌ Не понял формат. Используй:\n"
            "<code>Предмет: Задание, до ДД.ММ</code>\n\n"
            "<b>Пример:<b>\n"
            "<code>Математика: №123-125, до 08.10</code>",
            parse_mode="HTML"
        )
        return

    subject, task, deadline = parsed
    homework_id = await add_homework(subject, task, deadline)

    await message.answer(
        f"✅ ДЗ добавлено!\n\n"
        f"<b>{subject}</b>\n"
        f"📝 {task}\n"
        f"📅 До: <code>{deadline.strftime('%d.%m.%Y')}</code>\n",
        parse_mode="HTML"
    )

# Обработчик inline-кнопок
@dp.callback_query(F.data.startswith('done_'))
async def callback_done(callback: types.CallbackQuery):
    homework_id = int(callback.data.split('_')[1])
    await delete_homework(homework_id)
    await callback.answer("✅ ДЗ отмечено как выполненное!")
    await callback.message.edit_text(f"🗑️ ДЗ удалено.")


@dp.callback_query(F.data.startswith('delete_'))
async def callback_delete(callback: types.CallbackQuery):
    homework_id = int(callback.data.split('_')[1])
    await delete_homework(homework_id)
    await callback.answer("❌ ДЗ удалено!")
    await callback.message.edit_text(f"🗑️ ДЗ удалено.")


# Нажали "✏️ Изменить"
@dp.callback_query(F.data.startswith('edit_'))
async def callback_edit(callback: types.CallbackQuery, state: FSMContext):
    homework_id = int(callback.data.split('_')[1])
    homework = await get_homework_by_id(homework_id)

    if not homework:
        await callback.answer("❌ ДЗ не найдено", show_alert=True)
        return

    # Сохраняем, какой ДЗ редактируем
    editing_homework_id[callback.from_user.id] = homework_id

    # Переводим бота в режим ожидания выбора поля
    await state.set_state(EditHomework.waiting_for_field)

    # Показываем текущее ДЗ и кнопки выбора
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📚 Предмет", callback_data="field_subject"),
            InlineKeyboardButton(text="📝 Задание", callback_data="field_task")
        ],
        [InlineKeyboardButton(text="📅 Дата", callback_data="field_deadline")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="edit_cancel")]
    ])

    text = (
        f"✏️ <b>Редактирование ДЗ #{homework_id}</b>\n\n"
        f"📚 Предмет: <b>{homework.subject}</b>\n"
        f"📝 Задание: <i>{homework.task}</i>\n"
        f"📅 Дата: <code>{homework.deadline.strftime('%d.%m.%Y')}</code>\n\n"
        f"Что хочешь изменить?"
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# Выбрали, какое поле менять
@dp.callback_query(F.data.startswith('field_'))
async def callback_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split('_')[1]  # subject / task / deadline

    # Сохраняем выбранное поле в состоянии
    await state.update_data(field=field)
    await state.set_state(EditHomework.waiting_for_value)

    # Подсказка в зависимости от поля
    hints = {
        'subject': "📚 Введи новое название предмета:",
        'task': "📝 Введи новое описание задания:",
        'deadline': "📅 Введи новую дату (например, <code>15.10</code>):"
    }

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="edit_cancel")]
    ])

    await callback.message.edit_text(hints[field], reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# Ввели новое значение
@dp.message(EditHomework.waiting_for_value)
async def process_new_value(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    homework_id = editing_homework_id.get(user_id)

    if not homework_id:
        await state.clear()
        await message.answer("❌ Что-то пошло не так. Начни заново.")
        return

    data = await state.get_data()
    field = data['field']
    new_value = message.text.strip()

    # Если меняем дату — парсим её
    if field == 'deadline':
        new_date = parse_date(new_value)
        if not new_date:
            await message.answer(
                "❌ Не понял дату. Используй формат <code>ДД.ММ</code> или <code>ДД.ММ.ГГГГ</code>",
                parse_mode="HTML"
            )
            return
        await update_homework(homework_id, deadline=new_date)
    elif field == 'subject':
        await update_homework(homework_id, subject=new_value)
    elif field == 'task':
        await update_homework(homework_id, task=new_value)

    # Очищаем состояние
    await state.clear()
    editing_homework_id.pop(user_id, None)

    await message.answer("✅ ДЗ обновлено!")


# Отмена редактирования
@dp.callback_query(F.data == "edit_cancel")
async def callback_edit_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    editing_homework_id.pop(user_id, None)
    await callback.message.edit_text("❌ Редактирование отменено.")
    await callback.answer()

# Обработчик команды /help
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📖 *Помощь*\n\n"
        "*Добавление ДЗ:*\n"
        "`Предмет: Задание, до ДД.ММ`\n\n"
        "*Примеры:*\n"
        "`Математика: №123-125, до 08.10`\n"
        "`Физика: Глава 5, до 15.10.2026`\n\n"
        "*Команды:*\n"
        "/homework - Список всех ДЗ\n"
        "/help - Эта справка"
    )

# Реакция на кнопку "📋 Мои ДЗ"
@dp.message(F.text == "📋 Мои ДЗ")
async def cmd_homework_button(message: types.Message):
    # Вызываем ту же логику, что и для команды /homework
    await cmd_homework(message)
    # Важно: не возвращаем ничего, чтобы не срабатывали другие обработчики

# Реакция на кнопку "❓ Помощь"
@dp.message(F.text == "❓ Помощь")
async def cmd_help_button(message: types.Message):
    await cmd_help(message)

async def main():
    # Инициализация БД
    await init_db()

    # Запуск бота
    print("🤖 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())