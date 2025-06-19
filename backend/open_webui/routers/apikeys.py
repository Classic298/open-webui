from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import time

from open_webui.utils.auth import get_admin_user, generate_api_key_string, hash_api_key
from open_webui.utils.audit import log_application_event # Import audit logging function
from open_webui.models.users import UserModel
from open_webui.models.apikeys import ApiKeyModel, ApiKey
from open_webui.internal.db import get_db
from sqlalchemy.orm import Session

router = APIRouter(
    prefix="/apikeys",
    tags=["apikeys"],
)

# from fastapi_limiter.depends import RateLimiter # Would be imported if package was usable
# from open_webui.env import RATE_LIMIT_ADMIN_CREATE_API_KEY # Would be imported

# Pydantic Models for API Key Management

class CreateStandaloneApiKeyForm(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None # For informational purposes for standalone keys
    role: Optional[str] = Field(None, description="Role associated with the standalone key, e.g., 'sdk-user'")
    expires_at: Optional[int] = Field(None, description="Unix timestamp for key expiry")

class UpdateStandaloneApiKeyForm(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    expires_at: Optional[int] = Field(None, description="Unix timestamp for key expiry. Set to null to remove expiry.")

# ApiKeyModel from models.apikeys will serve as the base for responses.
# We might create a more specific ApiKeyResponse if needed, e.g., for masking.

# Example of a response model if we need to transform data from ApiKeyModel
class ApiKeyResponse(ApiKeyModel):
    key_display: Optional[str] = None # e.g., sk-...XXXX

    class Config:
        orm_mode = True

class PaginatedApiKeysResponse(BaseModel):
    keys: List[ApiKeyResponse]
    total: int
    page: int
    page_size: int

# Placeholder for CRUD operations

@router.post("/admin/api_keys", response_model=ApiKeyResponse)
async def create_standalone_api_key(
    form_data: CreateStandaloneApiKeyForm,
    request_obj: Request, # Added Request for audit logging
    form_data: CreateStandaloneApiKeyForm,
    admin: UserModel = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    plain_api_key = generate_api_key_string()
    hashed_key = hash_api_key(plain_api_key)

    db_apikey = ApiKey(
        key_hash=hashed_key,
        name=form_data.name,
        email=form_data.email, # For standalone keys, email is informational
        role=form_data.role,   # Specific role for this standalone key
        user_id=None,          # Standalone key
        created_at=int(time.time()),
        expires_at=form_data.expires_at,
        # info can be used for other metadata if needed
    )

    db.add(db_apikey)
    db.commit()
    db.refresh(db_apikey)

    # Audit Log
    log_application_event(
        user=admin,
        action="standalone_api_key_created",
        target_type="apikey",
        target_id=db_apikey.id,
        details={
            "name": db_apikey.name,
            "email": db_apikey.email,
            "role": db_apikey.role,
            "expires_at": db_apikey.expires_at,
        },
        request=request_obj
    )

    # For the response, include the plain_api_key and derive is_standalone
    # ApiKeyModel is already designed to hold these response-specific fields

    key_display_prefix = plain_api_key[:5]  # "sk-..." + first char
    key_display_suffix = plain_api_key[-4:] # Last 4 chars
    key_display = f"{key_display_prefix}...{key_display_suffix}"

    return ApiKeyResponse(
        id=db_apikey.id,
        key_hash=None,  # Do not send hash back
        name=db_apikey.name,
        email=db_apikey.email,
        role=db_apikey.role,
        user_id=db_apikey.user_id,
        created_at=db_apikey.created_at,
        last_used_at=db_apikey.last_used_at,
        expires_at=db_apikey.expires_at,
        info=db_apikey.info,
        key=plain_api_key, # Send the plain key back ONLY on creation
        is_standalone=True, # This is a standalone key
        key_display=key_display
    )


@router.get("/admin/api_keys", response_model=PaginatedApiKeysResponse)
async def get_all_api_keys(
    request: Request,
    admin: UserModel = Depends(get_admin_user),
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 10,
    sort_by: Optional[str] = "created_at", # Default sort
    sort_order: Optional[str] = "desc",    # Default order
    q: Optional[str] = None, # General query for name/email/role
    user_id_filter: Optional[str] = None, # Specific filter for user_id
    role_filter: Optional[str] = None, # Specific filter for role
):
    from open_webui.models.users import User  # Import User for joining

    query = db.query(ApiKey).outerjoin(User, ApiKey.user_id == User.id)

    if q:
        search_filter = f"%{q}%"
        query = query.filter(
            (ApiKey.name.ilike(search_filter)) |
            (ApiKey.email.ilike(search_filter)) | # For standalone keys
            (ApiKey.role.ilike(search_filter)) | # For standalone keys
            (User.name.ilike(search_filter)) |    # For user-associated keys
            (User.email.ilike(search_filter))     # For user-associated keys
        )

    if user_id_filter:
        query = query.filter(ApiKey.user_id == user_id_filter)

    if role_filter: # This would primarily apply to standalone key roles
        query = query.filter(ApiKey.role == role_filter)

    if sort_by:
        sort_column = getattr(ApiKey, sort_by, None)
        if sort_column is None and hasattr(User, sort_by): # Allow sorting by user fields if joined
            sort_column = getattr(User, sort_by)

        if sort_column:
            if sort_order.lower() == "desc":
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        else: # Default sort if sort_by is invalid
            query = query.order_by(ApiKey.created_at.desc())
    else: # Default sort
        query = query.order_by(ApiKey.created_at.desc())


    total_count = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    keys_with_users = query.limit(page_size).offset(offset).all()

    response_keys: List[ApiKeyResponse] = []
    for db_apikey in keys_with_users:
        user_name = db_apikey.user.name if db_apikey.user else None
        user_email = db_apikey.user.email if db_apikey.user else None

        # Construct key_display using the key's ID, as plain key isn't available
        # Example: "sk-aid1...XXXX" where aid1 are first 4 chars of apikey.id
        key_display_prefix = db_apikey.id[:4]
        key_display = f"sk-{key_display_prefix}...XXXX"


        response_keys.append(
            ApiKeyResponse(
                id=db_apikey.id,
                key_hash=None, # Never send hash
                name=db_apikey.name,
                email=db_apikey.email if db_apikey.user_id is None else user_email, # Show key's email for standalone, user's for user key
                role=db_apikey.role if db_apikey.user_id is None else db_apikey.user.role, # Key's role for standalone, user's for user key
                user_id=db_apikey.user_id,
                created_at=db_apikey.created_at,
                last_used_at=db_apikey.last_used_at,
                expires_at=db_apikey.expires_at,
                info=db_apikey.info,
                key=None, # Never send plain key when listing
                is_standalone=(db_apikey.user_id is None),
                user_name=user_name,
                user_email=user_email, # This is already set based on standalone/user key logic above
                key_display=key_display,
            )
        )

    return PaginatedApiKeysResponse(
        keys=response_keys,
        total=total_count,
        page=page,
        page_size=page_size,
    )


@router.get("/admin/api_keys/{key_id}", response_model=ApiKeyResponse)
async def get_api_key_by_id(
    key_id: str,
    request_obj: Request, # Added Request for audit logging
    key_id: str,
    form_data: UpdateStandaloneApiKeyForm,
    admin: UserModel = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from open_webui.models.users import User  # Import User for joining

    # Query for the ApiKey and join with User table to get user details if available
    db_apikey_data = db.query(ApiKey, User.name.label("user_name"), User.email.label("user_email_from_user"), User.role.label("user_role_from_user")) \
        .outerjoin(User, ApiKey.user_id == User.id) \
        .filter(ApiKey.id == key_id) \
        .first()

    if not db_apikey_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found")

    db_apikey, user_name, user_email_from_user, user_role_from_user = db_apikey_data

    key_display_prefix = db_apikey.id[:4]
    key_display = f"sk-{key_display_prefix}...XXXX"

    # Determine email and role based on whether it's a standalone or user-associated key
    resolved_email = db_apikey.email if db_apikey.user_id is None else user_email_from_user
    resolved_role = db_apikey.role if db_apikey.user_id is None else user_role_from_user

    return ApiKeyResponse(
        id=db_apikey.id,
        key_hash=None,  # Never send hash
        name=db_apikey.name,
        email=resolved_email,
        role=resolved_role,
        user_id=db_apikey.user_id,
        created_at=db_apikey.created_at,
        last_used_at=db_apikey.last_used_at,
        expires_at=db_apikey.expires_at,
        info=db_apikey.info,
        key=None,  # Never send plain key
        is_standalone=(db_apikey.user_id is None),
        user_name=user_name if db_apikey.user_id else None, # Only set if it's a user key
        user_email=user_email_from_user if db_apikey.user_id else None, # Redundant due to resolved_email, but explicit for clarity
        key_display=key_display,
    )


@router.put("/admin/api_keys/{key_id}", response_model=ApiKeyResponse)
async def update_standalone_api_key_by_id(
    key_id: str,
    form_data: UpdateStandaloneApiKeyForm,
    admin: UserModel = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    db_apikey = db.query(ApiKey).filter(ApiKey.id == key_id).first()

    if not db_apikey:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found")

    if db_apikey.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint can only update standalone API keys. User-associated keys are managed by the user.",
        )

    update_data = form_data.model_dump(exclude_unset=True)
    original_data_for_log: Dict[str, Any] = {}
    changed_data_for_log: Dict[str, Any] = {}

    for field, value in update_data.items():
        if hasattr(db_apikey, field) and getattr(db_apikey, field) != value:
            original_data_for_log[field] = getattr(db_apikey, field)
            changed_data_for_log[field] = value
        setattr(db_apikey, field, value)

    # Explicitly handle removal of expiry if expires_at is None in the form
    if form_data.expires_at is None and "expires_at" in update_data:
        if db_apikey.expires_at is not None: # Check if it actually changed
             original_data_for_log["expires_at"] = db_apikey.expires_at
             changed_data_for_log["expires_at"] = None
        setattr(db_apikey, "expires_at", None)


    db.commit()
    db.refresh(db_apikey)

    # Audit Log
    if changed_data_for_log: # Log only if something actually changed
        log_application_event(
            user=admin,
            action="standalone_api_key_updated",
            target_type="apikey",
            target_id=db_apikey.id,
            details={
                "original_values": original_data_for_log,
                "updated_values": changed_data_for_log
            },
            request=request_obj
        )

    key_display_prefix = db_apikey.id[:4]
    key_display = f"sk-{key_display_prefix}...XXXX"

    return ApiKeyResponse(
        id=db_apikey.id,
        key_hash=None, # Never send hash
        name=db_apikey.name,
        email=db_apikey.email,
        role=db_apikey.role,
        user_id=db_apikey.user_id, # Will be None for standalone keys
        created_at=db_apikey.created_at,
        last_used_at=db_apikey.last_used_at,
        expires_at=db_apikey.expires_at,
        info=db_apikey.info,
        key=None, # Never send plain key
        is_standalone=True, # Since we checked user_id is None
        user_name=None, # Standalone keys don't have associated user names directly on them
        user_email=None,
        key_display=key_display,
    )


@router.delete("/admin/api_keys/{key_id}")
async def delete_api_key_by_id(
    key_id: str,
    request_obj: Request, # Added Request for audit logging
    key_id: str,
    admin: UserModel = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    db_apikey = db.query(ApiKey).filter(ApiKey.id == key_id).first()

    if not db_apikey:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found")

    # Log before deleting to capture key details
    log_application_event(
        user=admin,
        action="api_key_revoked_by_admin",
        target_type="apikey",
        target_id=db_apikey.id,
        details={
            "name": db_apikey.name,
            "user_id": db_apikey.user_id,
            "role": db_apikey.role,
            "email": db_apikey.email,
            "is_standalone": db_apikey.user_id is None,
        },
        request=request_obj
    )

    db.delete(db_apikey)
    db.commit()

    return {"detail": "API Key deleted successfully"}
