import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

logger = logging.getLogger("database")

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False}
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

async def init_db():
    from app.models.server import ServerModel
    from app.models.user import AppUserModel, AppSessionModel  # noqa: F401 (registers tables)
    from app.models.audit import AuditLogModel  # noqa: F401
    from app.models.file_remote import FileRemoteModel  # noqa: F401
    from sqlalchemy import select
    
    def encrypt_legacy_credentials(connection):
        from app.core.crypto import encrypt, PREFIX
        cursor = connection.connection.cursor()
        cursor.execute("SELECT id, password, private_key FROM servers")
        rows = cursor.fetchall()
        migrated = 0
        for sid, password, private_key in rows:
            new_pw = encrypt(password) if password and not password.startswith(PREFIX) else password
            new_pk = encrypt(private_key) if private_key and not private_key.startswith(PREFIX) else private_key
            if (new_pw, new_pk) != (password, private_key):
                cursor.execute("UPDATE servers SET password = ?, private_key = ? WHERE id = ?", (new_pw, new_pk, sid))
                migrated += 1
        if migrated:
            connection.connection.commit()
            logger.info(f"Encrypted stored credentials for {migrated} server(s).")

    def check_and_migrate(connection):
        cursor = connection.connection.cursor()
        cursor.execute("PRAGMA table_info(servers)")
        columns = [row[1] for row in cursor.fetchall()]
        if "password" not in columns:
            cursor.execute("ALTER TABLE servers ADD COLUMN password VARCHAR(512)")
            connection.connection.commit()
            logger.info("Migrated 'servers' table: added 'password' column.")
        if "use_sudo" not in columns:
            cursor.execute("ALTER TABLE servers ADD COLUMN use_sudo BOOLEAN NOT NULL DEFAULT 0")
            connection.connection.commit()
            logger.info("Migrated 'servers' table: added 'use_sudo' column.")
        if "sudo_password" not in columns:
            cursor.execute("ALTER TABLE servers ADD COLUMN sudo_password TEXT")
            connection.connection.commit()
            logger.info("Migrated 'servers' table: added 'sudo_password' column.")
        if "host_key" not in columns:
            cursor.execute("ALTER TABLE servers ADD COLUMN host_key TEXT")
            connection.connection.commit()
            logger.info("Migrated 'servers' table: added 'host_key' column.")

    def migrate_app_users(connection):
        cursor = connection.connection.cursor()
        cursor.execute("PRAGMA table_info(app_users)")
        columns = {row[1] for row in cursor.fetchall()}
        additions = {
            # Accounts created before RBAC existed were full admins; keep them that way
            "role": "VARCHAR(16) NOT NULL DEFAULT 'admin'",
            "disabled": "BOOLEAN NOT NULL DEFAULT 0",
            "mfa_secret": "TEXT",
            "mfa_enabled": "BOOLEAN NOT NULL DEFAULT 0",
            "mfa_last_step": "INTEGER",
            "recovery_codes": "TEXT",
        }
        for col, ddl in additions.items():
            if col not in columns:
                cursor.execute(f"ALTER TABLE app_users ADD COLUMN {col} {ddl}")
                logger.info(f"Migrated 'app_users' table: added '{col}' column.")
        connection.connection.commit()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(migrate_app_users)
        await conn.run_sync(check_and_migrate)
        await conn.run_sync(encrypt_legacy_credentials)
        
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ServerModel).where(ServerModel.id == "local"))
        local_server = result.scalar_one_or_none()
        if not local_server:
            local_server = ServerModel(
                id="local",
                name="master",
                host="localhost",
                port=22,
                username="root",
                is_local=True,
                status="online"
            )
            session.add(local_server)
            await session.commit()
            logger.info("Default local server initialized in database.")

        if settings.LOCAL_MODE == "ssh":
            # Containerized install: the "local" node is the container host, reached over SSH
            if (local_server.host, local_server.port) != (settings.LOCAL_SSH_HOST, settings.LOCAL_SSH_PORT):
                local_server.host_key = None
            local_server.host = settings.LOCAL_SSH_HOST
            local_server.port = settings.LOCAL_SSH_PORT
            local_server.username = settings.LOCAL_SSH_USER
            local_server.auth_type = "key"
            local_server.key_path = settings.LOCAL_SSH_KEY_PATH
            local_server.use_sudo = settings.LOCAL_SSH_SUDO
            await session.commit()
            logger.info(
                f"Local node mapped to host via SSH: {settings.LOCAL_SSH_USER}@{settings.LOCAL_SSH_HOST}:{settings.LOCAL_SSH_PORT}"
                + (" (sudo)" if settings.LOCAL_SSH_SUDO else "")
            )

    await _bootstrap_admin()

async def _bootstrap_admin():
    import secrets
    from sqlalchemy import select, func
    from app.models.user import AppUserModel
    from app.core.security import hash_password

    async with AsyncSessionLocal() as session:
        count = (await session.execute(select(func.count()).select_from(AppUserModel))).scalar_one()
        if count:
            return

        password = settings.ADMIN_PASSWORD
        generated = not password
        if generated:
            password = secrets.token_urlsafe(12)

        session.add(AppUserModel(username=settings.ADMIN_USERNAME, password_hash=hash_password(password), role="admin"))
        await session.commit()

        if generated:
            logger.warning(
                "No ADMIN_PASSWORD set. Created initial account "
                f"'{settings.ADMIN_USERNAME}' with generated password: {password}  "
                "(change it after first login)"
            )
        else:
            logger.info(f"Created initial admin account '{settings.ADMIN_USERNAME}'.")
