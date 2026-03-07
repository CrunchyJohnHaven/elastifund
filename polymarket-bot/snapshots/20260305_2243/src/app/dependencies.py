"""FastAPI dependency injection utilities."""
from typing import Optional

from fastapi import Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.store.database import DatabaseManager

_settings: Optional[Settings] = None


def set_settings(s: Settings) -> None:
    """Set the global settings instance (for testing and initialization)."""
    global _settings
    _settings = s


def get_config() -> Settings:
    """Get the current settings instance.
    
    Returns:
        Settings instance (either globally set or fresh from get_settings())
    """
    if _settings is None:
        return get_settings()
    return _settings


async def get_db_session() -> AsyncSession:
    """FastAPI dependency to get a database session.
    
    Yields:
        AsyncSession instance
    """
    async with DatabaseManager.get_session() as session:
        yield session


async def verify_token(
    authorization: Optional[str] = Header(None),
) -> bool:
    """Verify dashboard API token from Authorization header.
    
    Args:
        authorization: Authorization header value
        
    Returns:
        True if token is valid
        
    Raises:
        HTTPException: If token is missing or invalid
    """
    settings = get_config()
    token = settings.dashboard_token
    if not token or token == "change_me":
        return True
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid format. Use: Bearer <token>")
    if parts[1] != token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")
    return True
