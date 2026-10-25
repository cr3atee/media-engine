"""PostgreSQL role audit; transactions belong to the existing scope factory."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.product_access import ProductRole, ProductRoleAction
from app.models.product_role_action_record import ProductRoleActionRecord
from app.repositories.product_role_actions import ProductRoleActionRepository


class PostgresProductRoleActionRepository(ProductRoleActionRepository):
    """Persist role audit without opening or committing independent transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, action: ProductRoleAction) -> None:
        """Flush one audit entry without committing the caller's transaction."""
        self._session.add(ProductRoleActionRecord(**asdict(action)))
        await self._session.flush()

    async def get_replay(
        self, actor_key: str, idempotency_key: str
    ) -> ProductRoleAction | None:
        """Read the persisted result for an actor-scoped idempotency key."""
        record = await self._session.scalar(
            select(ProductRoleActionRecord).where(
                ProductRoleActionRecord.actor_key == actor_key,
                ProductRoleActionRecord.idempotency_key == idempotency_key,
            )
        )
        return _to_domain(record) if record else None

    async def list_for_user(
        self, user_id: UUID, limit: int = 100
    ) -> tuple[ProductRoleAction, ...]:
        """Return at most 100 audit entries in newest-first order."""
        if not 1 <= limit <= 100:
            raise ValueError("Audit limit must be between 1 and 100.")
        records = await self._session.scalars(
            select(ProductRoleActionRecord)
            .where(ProductRoleActionRecord.user_id == user_id)
            .order_by(
                ProductRoleActionRecord.created_at.desc(),
                ProductRoleActionRecord.id.desc(),
            )
            .limit(limit)
        )
        return tuple(_to_domain(record) for record in records)


def _to_domain(record: ProductRoleActionRecord) -> ProductRoleAction:
    return ProductRoleAction(
        id=record.id,
        user_id=record.user_id,
        actor_user_id=record.actor_user_id,
        actor_key=record.actor_key,
        previous_role=ProductRole(record.previous_role),
        resulting_role=ProductRole(record.resulting_role),
        expected_version=record.expected_version,
        resulting_version=record.resulting_version,
        reason=record.reason,
        idempotency_key=record.idempotency_key,
        fingerprint=record.fingerprint,
        created_at=record.created_at,
    )
