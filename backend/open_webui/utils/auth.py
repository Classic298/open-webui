import logging
import uuid
import jwt
import base64
import hmac
import hashlib
import requests
import os


from datetime import datetime, timedelta
import pytz
from pytz import UTC
from typing import Optional, Union, List, Dict

from opentelemetry import trace

from open_webui.models.users import Users

from open_webui.constants import ERROR_MESSAGES
from open_webui.env import (
    WEBUI_SECRET_KEY,
    TRUSTED_SIGNATURE_KEY,
    STATIC_DIR,
    SRC_LOG_LEVELS,
    WEBUI_AUTH_TRUSTED_EMAIL_HEADER,
)

from fastapi import BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext


logging.getLogger("passlib").setLevel(logging.ERROR)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["OAUTH"])

SESSION_SECRET = WEBUI_SECRET_KEY
ALGORITHM = "HS256"

##############
# Auth Utils
##############


def verify_signature(payload: str, signature: str) -> bool:
    """
    Verifies the HMAC signature of the received payload.
    """
    try:
        expected_signature = base64.b64encode(
            hmac.new(TRUSTED_SIGNATURE_KEY, payload.encode(), hashlib.sha256).digest()
        ).decode()

        # Compare securely to prevent timing attacks
        return hmac.compare_digest(expected_signature, signature)

    except Exception:
        return False


def override_static(path: str, content: str):
    # Ensure path is safe
    if "/" in path or ".." in path:
        log.error(f"Invalid path: {path}")
        return

    file_path = os.path.join(STATIC_DIR, path)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, "wb") as f:
        f.write(base64.b64decode(content))  # Convert Base64 back to raw binary


def get_license_data(app, key):
    if key:
        try:
            res = requests.post(
                "https://api.openwebui.com/api/v1/license/",
                json={"key": key, "version": "1"},
                timeout=5,
            )

            if getattr(res, "ok", False):
                payload = getattr(res, "json", lambda: {})()
                for k, v in payload.items():
                    if k == "resources":
                        for p, c in v.items():
                            globals().get("override_static", lambda a, b: None)(p, c)
                    elif k == "count":
                        setattr(app.state, "USER_COUNT", v)
                    elif k == "name":
                        setattr(app.state, "WEBUI_NAME", v)
                    elif k == "metadata":
                        setattr(app.state, "LICENSE_METADATA", v)
                return True
            else:
                log.error(
                    f"License: retrieval issue: {getattr(res, 'text', 'unknown error')}"
                )
        except Exception as ex:
            log.exception(f"License: Uncaught Exception: {ex}")
    return False


bearer_security = HTTPBearer(auto_error=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password, hashed_password):
    return (
        pwd_context.verify(plain_password, hashed_password) if hashed_password else None
    )


def get_password_hash(password):
    return pwd_context.hash(password)


def create_token(data: dict, expires_delta: Union[timedelta, None] = None) -> str:
    payload = data.copy()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
        payload.update({"exp": expire})

    encoded_jwt = jwt.encode(payload, SESSION_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    try:
        decoded = jwt.decode(token, SESSION_SECRET, algorithms=[ALGORITHM])
        return decoded
    except Exception:
        return None


def extract_token_from_auth_header(auth_header: str):
    return auth_header[len("Bearer ") :]


def generate_api_key_string() -> str:
    # Formerly create_api_key()
    key = str(uuid.uuid4()).replace("-", "")
    return f"sk-{key}"


def hash_api_key(api_key: str) -> str:
    """Hashes the API key using SHA256."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(plain_key: str, hashed_key: str) -> bool:
    """Verifies a plain API key against a stored hashed key."""
    return hmac.compare_digest(hash_api_key(plain_key), hashed_key)


def get_http_authorization_cred(auth_header: Optional[str]):
    if not auth_header:
        return None
    try:
        scheme, credentials = auth_header.split(" ")
        return HTTPAuthorizationCredentials(scheme=scheme, credentials=credentials)
    except Exception:
        return None


def get_current_user(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    auth_token: HTTPAuthorizationCredentials = Depends(bearer_security),
):
    token = None

    if auth_token is not None:
        token = auth_token.credentials

    if token is None and "token" in request.cookies:
        token = request.cookies.get("token")

    if token is None:
        raise HTTPException(status_code=403, detail="Not authenticated")

    # auth by api key
    if token.startswith("sk-"):
        if not request.state.enable_api_key:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.API_KEY_NOT_ALLOWED
            )

        if request.app.state.config.ENABLE_API_KEY_ENDPOINT_RESTRICTIONS:
            allowed_paths = [
                path.strip()
                for path in str(
                    request.app.state.config.API_KEY_ALLOWED_ENDPOINTS
                ).split(",")
            ]

            # Check if the request path matches any allowed endpoint.
            if not any(
                request.url.path == allowed
                or request.url.path.startswith(allowed + "/")
                for allowed in allowed_paths
            ):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.API_KEY_NOT_ALLOWED
                )

        user = get_current_user_by_api_key(token)

        # Add user info to current span
        current_span = trace.get_current_span()
        if current_span:
            current_span.set_attribute("client.user.id", user.id)
            current_span.set_attribute("client.user.email", user.email)
            current_span.set_attribute("client.user.role", user.role)
            current_span.set_attribute("client.auth.type", "api_key")

        return user

    # auth by jwt token
    try:
        data = decode_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    if data is not None and "id" in data:
        user = Users.get_user_by_id(data["id"])
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.INVALID_TOKEN,
            )
        else:
            if WEBUI_AUTH_TRUSTED_EMAIL_HEADER:
                trusted_email = request.headers.get(
                    WEBUI_AUTH_TRUSTED_EMAIL_HEADER, ""
                ).lower()
                if trusted_email and user.email != trusted_email:
                    # Delete the token cookie
                    response.delete_cookie("token")
                    # Delete OAuth token if present
                    if request.cookies.get("oauth_id_token"):
                        response.delete_cookie("oauth_id_token")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="User mismatch. Please sign in again.",
                    )

            # Add user info to current span
            current_span = trace.get_current_span()
            if current_span:
                current_span.set_attribute("client.user.id", user.id)
                current_span.set_attribute("client.user.email", user.email)
                current_span.set_attribute("client.user.role", user.role)
                current_span.set_attribute("client.auth.type", "jwt")

            # Refresh the user's last active timestamp asynchronously
            # to prevent blocking the request
            if background_tasks:
                background_tasks.add_task(Users.update_user_last_active_by_id, user.id)
        return user
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )


def get_current_user_by_api_key(api_key: str):
    # This function needs to be updated to use the new ApiKey model
    # and compare hashed keys.
    # Placeholder logic:
    hashed_incoming_key = hash_api_key(api_key)

    # TODO: Query the ApiKey table for a key with key_hash == hashed_incoming_key
    # from open_webui.models.apikeys import ApiKey
    # from open_webui.internal.db import get_db
    # from sqlalchemy.orm import Session
    #
    # with get_db() as db:
    #   api_key_instance = db.query(ApiKey).filter_by(key_hash=hashed_incoming_key).first()
    #
    #   if not api_key_instance:
    #       raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.INVALID_TOKEN)
    #
    #   # Check expiry
    #   if api_key_instance.expires_at and datetime.now(UTC).timestamp() > api_key_instance.expires_at:
    #       raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key has expired")
    #
    #   # Update last_used_at
    #   api_key_instance.last_used_at = int(datetime.now(UTC).timestamp())
    #   db.commit()
    #
    #   if not api_key_instance.user_id:
    #       # This indicates a standalone key was used where a user-associated key was expected by this function's original design.
    #       # Depending on policy, could raise error or handle differently.
    #       # For now, if this function is *only* for user-associated keys, this is an error.
    #       # However, the new admin endpoints might use a similar auth check that allows standalone keys.
    #       # This function might need to be split or adapted based on where it's used.
    #       # For now, let's assume it's for finding a user.
    #       raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key not associated with a user for this endpoint")
    #
    #   user = Users.get_user_by_id(api_key_instance.user_id)
    #
    #   if user is None:
    #       raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.INVALID_TOKEN) # Should not happen if FK is maintained
    #
    #   # Add user info to current span
    #   current_span = trace.get_current_span()
    #   if current_span:
    #       current_span.set_attribute("client.user.id", user.id)
    #       current_span.set_attribute("client.user.email", user.email)
    #       current_span.set_attribute("client.user.role", user.role)
    #       current_span.set_attribute("client.auth.type", "api_key")
    #
    #   Users.update_user_last_active_by_id(user.id) # This updates the user's last active, not the key's
    #   return user

    # This function needs to be updated to use the new ApiKey model
    # and compare hashed keys.

    from open_webui.models.apikeys import ApiKey as DbApiKey
    from open_webui.internal.db import get_db
    # Session type hint for db, though get_db usually handles it.
    # from sqlalchemy.orm import Session

    hashed_incoming_key = hash_api_key(api_key)

    # In a real scenario, get_db() might need to be called if not already in context,
    # but Depends(get_db) is usually for endpoint functions.
    # For utility functions, explicit session management or passing session is needed.
    # Assuming get_current_user calls this, a db session might be available via request state or passed.
    # For now, let's simulate getting a session. This part is tricky as utils don't use Depends().
    # This function is called by get_current_user, which *does* have `db` via `request.state.db`
    # or should be refactored to pass `db` session if `get_current_user` is to use it.
    # For now, we assume a session can be acquired.

    # Simplified: This function is called within get_current_user, which has access to request.
    # It should ideally take `db: Session` as an argument.
    # Let's assume for now that `get_current_user` will pass the db session.
    # The call would be: user = get_current_user_by_api_key(token, db)
    # So, we modify the signature here for now. This will require change in get_current_user.

    # Re-thinking: get_current_user_by_api_key is called by get_current_user.
    # get_current_user itself doesn't have a db session via Depends.
    # The db session is typically injected into route handlers.
    # This utility function, if it needs DB access, must be passed a session.
    # The current structure of get_current_user doesn't easily allow passing db.
    # A common pattern is to attach db to request.state if middleware adds it.
    # Or, functions like Users.get_user_by_id() internally call get_db().
    # Let's follow that pattern: use with get_db()
    from open_webui.models.users import UserModel # Import UserModel for constructing standalone key "user"

    with get_db() as db:
        api_key_instance = db.query(DbApiKey).filter(DbApiKey.key_hash == hashed_incoming_key).first()

        if not api_key_instance:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.INVALID_TOKEN)

        if api_key_instance.expires_at and datetime.now(UTC).timestamp() > api_key_instance.expires_at:
            # Clean up expired key? Or leave it for a batch job? For now, just deny access.
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key has expired")

        # Update last_used_at for the key, regardless of type
        api_key_instance.last_used_at = int(datetime.now(UTC).timestamp())
        db.commit() # Commit this change

        user_to_return = None

        if api_key_instance.user_id:
            # User-associated key
            user = Users.get_user_by_id(api_key_instance.user_id)
            if user is None:
                # Should not happen if DB integrity is maintained (FK constraint)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User associated with API Key not found.")

            # Update user's last_active_at
            # Users.update_user_last_active_by_id(user.id) # This is a direct DB call, UserModel doesn't have it.
            # The UsersTable instance has this method.
            users_table = Users()
            users_table.update_user_last_active_by_id(user.id)
            user_to_return = user
        else:
            # Standalone key, construct a UserModel-like object
            if not api_key_instance.name or not api_key_instance.email or not api_key_instance.role:
                # Standalone keys used for authentication must have name, email, and role.
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Standalone API Key is missing required metadata (name, email, role) for authentication.")

            user_to_return = UserModel(
                id=f"apikey:{api_key_instance.id}",
                name=api_key_instance.name,
                email=api_key_instance.email, # Assuming this is populated for auth-intended standalone keys
                role=api_key_instance.role,   # Role from the API key itself
                profile_image_url="/user.png", # Default profile image
                last_active_at=api_key_instance.last_used_at if api_key_instance.last_used_at else int(datetime.now(UTC).timestamp()),
                                              # Using key's last_used_at for last_active_at
                updated_at=api_key_instance.created_at, # Or some other meaningful timestamp; using created_at for now
                created_at=api_key_instance.created_at,
                settings=None,
                info={"source": "api_key", "key_name": api_key_instance.name}, # Add some context
                oauth_sub=None
            )

        # Add user info to current span
        current_span = trace.get_current_span()
        if current_span and user_to_return:
            current_span.set_attribute("client.user.id", user_to_return.id)
            current_span.set_attribute("client.user.email", user_to_return.email)
            current_span.set_attribute("client.user.role", user_to_return.role)
            current_span.set_attribute("client.auth.type", "api_key")
            current_span.set_attribute("client.auth.key_id", api_key_instance.id)

        return user_to_return


def get_verified_user(user=Depends(get_current_user)):
    if user.role not in {"user", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return user


def get_admin_user(user=Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return user
