"""Persistent instance authentication policy and shared library identity."""
from sqlalchemy import select

from app.models.database import async_session_maker
from app.models.entities import InstanceSettings, User


async def bootstrap_instance(session_factory=None):
    from app.api.auth import lock_bootstrap_transaction
    async with (session_factory or async_session_maker)() as db:
        await lock_bootstrap_transaction(db)
        if await db.get(InstanceSettings, 1):
            return
        users = (await db.scalars(select(User).order_by(User.id))).all()
        if len(users) == 1:
            owner = users[0]
        else:
            # Existing multi-user installations retain their independent data.
            # Prefer the local account previously bootstrapped by TrackHound.
            owner = next((user for user in users if user.password_hash or user.username == "admin"), None)
        if owner is None:
            owner = User(plex_username="admin", username="admin")
            db.add(owner)
            await db.flush()
        db.add(InstanceSettings(id=1, owner_user_id=owner.id, auth_required=False))
        await db.commit()


async def instance_settings(db):
    return await db.get(InstanceSettings, 1)
