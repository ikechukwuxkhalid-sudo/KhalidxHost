from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import DATABASE_URL
from app.database.models import Base, VpsInstance

_kwargs = {"echo": False}
if DATABASE_URL.startswith("postgresql"):
    _kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=5)

engine = create_async_engine(DATABASE_URL, **_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # a restart kills in-flight deployment tasks -> mark them failed so the UI doesn't spin forever
    async with SessionLocal() as s:
        await s.execute(
            update(VpsInstance)
            .where(VpsInstance.status == "DEPLOYING")
            .values(status="FAILED", error="Deployment interrupted by a server restart. Delete this entry and try again.")
        )
        await s.commit()


async def get_session():
    async with SessionLocal() as session:
        yield session
