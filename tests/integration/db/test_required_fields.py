import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, Lesson


@pytest.mark.parametrize(
    ("entity", "field"),
    [
        ("group", "id"),
        ("group", "name"),
        ("group", "size"),
        ("lesson", "id"),
        ("lesson", "group_id"),
        ("lesson", "instructor_id"),
        ("lesson", "status"),
        ("lesson", "format"),
        ("lesson", "starts_at"),
        ("lesson", "ends_at"),
        ("lesson", "created_at"),
        ("lesson", "updated_at"),
    ],
)
async def test_reject_null_required_field(
    db_session: AsyncSession,
    lesson: Lesson,
    entity: str,
    field: str,
) -> None:
    db_session.add(lesson)
    await db_session.flush()

    model = Group if entity == "group" else Lesson
    record_id = lesson.group_id if entity == "group" else lesson.id

    statement = (
        update(model)
        .where(model.id == record_id)
        .values({field: None})
        .execution_options(synchronize_session=False)
    )

    with pytest.raises(IntegrityError) as error:
        await db_session.execute(statement)

    assert field in str(error.value.orig)
