from sqlalchemy import Column, Integer, String, DateTime, Boolean, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from config import DATABASE_URL

Base = declarative_base()


class Homework(Base):
    __tablename__ = 'homework'

    id = Column(Integer, primary_key=True)
    subject = Column(String(100), nullable=False)
    task = Column(String(500), nullable=False)
    deadline = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_completed = Column(Boolean, default=False)


engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Инициализация базы данных"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def add_homework(subject: str, task: str, deadline: datetime) -> int:
    """Добавить ДЗ"""
    async with async_session() as session:
        homework = Homework(subject=subject, task=task, deadline=deadline)
        session.add(homework)
        await session.commit()
        await session.refresh(homework)
        return homework.id


async def get_all_homework() -> list:
    """Получить все невыполненные ДЗ, отсортированные по дедлайну"""
    async with async_session() as session:
        result = await session.execute(
            select(Homework)
            .where(Homework.is_completed == False)
            .order_by(Homework.deadline)
        )
        return result.scalars().all()


async def get_homework_by_id(homework_id: int):
    """Получить ДЗ по ID"""
    async with async_session() as session:
        result = await session.execute(
            select(Homework).where(Homework.id == homework_id)
        )
        return result.scalar_one_or_none()


async def update_homework(homework_id: int, **kwargs):
    """Обновить ДЗ"""
    async with async_session() as session:
        result = await session.execute(
            select(Homework).where(Homework.id == homework_id)
        )
        homework = result.scalar_one_or_none()
        if homework:
            for key, value in kwargs.items():
                setattr(homework, key, value)
            await session.commit()
            return True
        return False


async def delete_homework(homework_id: int):
    """Удалить ДЗ"""
    async with async_session() as session:
        result = await session.execute(
            select(Homework).where(Homework.id == homework_id)
        )
        homework = result.scalar_one_or_none()
        if homework:
            await session.delete(homework)
            await session.commit()
            return True
        return False