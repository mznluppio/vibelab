"""Regression coverage for project deletion after the automation runtime reset."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models, models_automations  # noqa: F401 -- register all metadata
from app.database import Base
from app.models import PROJECT_KIND_WORKSPACE, Project, Team, User


@pytest.mark.asyncio
async def test_project_delete_does_not_load_dropped_legacy_schedule_table() -> None:
    """ORM deletion must work after migration 0074 removes agent_schedules."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            await connection.run_sync(Base.metadata.create_all)
            await connection.exec_driver_sql("DROP TABLE agent_schedules")

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            user_id = uuid.uuid4()
            team_id = uuid.uuid4()
            project_id = uuid.uuid4()
            db.add(
                User(
                    id=user_id,
                    email=f"user-{user_id.hex}@example.com",
                    hashed_password="x",
                    is_active=True,
                    is_superuser=False,
                    is_verified=False,
                    name="Test user",
                    username=f"user-{user_id.hex[:10]}",
                    slug=f"user-{user_id.hex[:10]}",
                )
            )
            db.add(
                Team(
                    id=team_id,
                    slug=f"team-{team_id.hex[:10]}",
                    name="Test team",
                    is_personal=True,
                    created_by_id=user_id,
                )
            )
            db.add(
                Project(
                    id=project_id,
                    name="Project to delete",
                    slug=f"project-{project_id.hex[:10]}",
                    owner_id=user_id,
                    team_id=team_id,
                    visibility="team",
                    project_kind=PROJECT_KIND_WORKSPACE,
                )
            )
            await db.commit()

            project = await db.get(Project, project_id)
            assert project is not None
            await db.delete(project)
            await db.commit()

            assert (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none() is None
    finally:
        await engine.dispose()
