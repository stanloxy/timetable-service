import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, Lesson


@pytest.mark.parametrize("entity", ["group", "lesson"])
async def test_reject_duplicate_primary_key(
    db_session: AsyncSession,
    lesson: Lesson,
    entity: str,
) -> None:
    db_session.add(lesson)
    await db_session.flush()

    model = Group if entity == "group" else Lesson
    record_id = lesson.group_id if entity == "group" else lesson.id

    # Копируем существующую строку вместе с её первичным ключом.
    statement = insert(model).from_select(
        [column.name for column in model.__table__.columns],
        select(model).where(model.id == record_id),
    )

    with pytest.raises(IntegrityError) as error:
        await db_session.execute(statement)

    constraint = "groups_pkey" if entity == "group" else "lessons_pkey"
    assert constraint in str(error.value.orig)
