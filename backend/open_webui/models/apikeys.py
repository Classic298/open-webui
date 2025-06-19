import time
import uuid
from typing import Optional

from sqlalchemy import Column, String, BigInteger, ForeignKey
from sqlalchemy.orm import relationship
from pydantic import BaseModel, ConfigDict

from open_webui.internal.db import Base, JSONField

class ApiKey(Base):
    __tablename__ = "apikey"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    key_hash = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    role = Column(String, nullable=True)
    user_id = Column(String, ForeignKey('user.id'), nullable=True)
    created_at = Column(BigInteger, default=lambda: int(time.time()))
    last_used_at = Column(BigInteger, nullable=True)
    expires_at = Column(BigInteger, nullable=True)
    info = Column(JSONField, nullable=True)

    user = relationship("User")

class ApiKeyModel(BaseModel):
    id: str
    key_hash: str
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    user_id: Optional[str] = None
    created_at: int
    last_used_at: Optional[int] = None
    expires_at: Optional[int] = None
    info: Optional[dict] = None

    # Fields for response, not stored directly in ApiKey table (except user_id)
    key: Optional[str] = None  # Only for sending back on creation
    is_standalone: bool = False # Should be derived: True if user_id is None
    user_name: Optional[str] = None # Populated for user-associated keys
    user_email: Optional[str] = None # Populated for user-associated keys


    model_config = ConfigDict(from_attributes=True)
