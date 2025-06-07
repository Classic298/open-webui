from typing import Optional

from open_webui.models.models import (
    ModelForm,
    ModelModel,
    ModelResponse,
    ModelUserResponse,
    Models,
    Model,
    ModelModel, # Ensure ModelModel is imported for conversion
)
from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import get_db # Import get_db for direct session
from fastapi import APIRouter, Depends, HTTPException, Request, status
import logging


from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.access_control import has_access, has_permission


router = APIRouter()
log = logging.getLogger(__name__)


###########################
# GetModels
###########################


@router.get("/", response_model=list[ModelUserResponse])
async def get_models(id: Optional[str] = None, user=Depends(get_verified_user)):
    if user.role == "admin":
        return Models.get_models()
    else:
        return Models.get_models_by_user_id(user.id)


###########################
# GetBaseModels
###########################


@router.get("/base", response_model=list[ModelResponse])
async def get_base_models(user=Depends(get_admin_user)):
    return Models.get_base_models()


###########################
# GetPinnedModels
###########################


@router.get("/pinned", response_model=list[ModelResponse])
async def get_pinned_models(user=Depends(get_verified_user)):
    log.info(f"[PinnedModels] Request from user ID: {user.id}, Role: {user.role}")

    db_pinned_models_sqla = []
    try:
        with get_db() as db:
            db_pinned_models_sqla = db.query(Model).filter(Model.pinned_to_sidebar == True).all()
            log.info(f"[PinnedModels] Raw DB query for 'Model.pinned_to_sidebar == True' found {len(db_pinned_models_sqla)} models.")
            if db_pinned_models_sqla:
                log.info(f"[PinnedModels] IDs from raw DB query: {[m.id for m in db_pinned_models_sqla]}")
    except Exception as e:
        log.error(f"[PinnedModels] Error during raw DB query for pinned models: {e}", exc_info=True)
        # db_pinned_models_sqla remains empty list, initialized above

    # Convert SQLAlchemy models to Pydantic ModelModel for consistent processing
    models_to_filter = [ModelModel.model_validate(m) for m in db_pinned_models_sqla]
    log.info(f"[PinnedModels] Found {len(models_to_filter)} models from direct DB query after Pydantic validation.")

    # Filter for active status
    active_models = [m for m in models_to_filter if m.is_active]
    log.info(f"[PinnedModels] Found {len(active_models)} active pinned models for user {user.id}.")

    # Filter for hidden status
    visible_models = []
    for m_model in active_models: # m_model is ModelModel instance
        hidden = False
        if m_model.meta: # m_model.meta is ModelMeta Pydantic model
            hidden = m_model.meta.model_dump().get("hidden", False)

        if not hidden:
            visible_models.append(m_model)
    log.info(f"[PinnedModels] Found {len(visible_models)} non-hidden, active, pinned models for user {user.id}.")

    # Filter for permission
    final_permitted_models = []
    for model_obj in visible_models: # model_obj is ModelModel instance
        if user.role == "admin":
            final_permitted_models.append(model_obj)
            log.info(f"[PinnedModels] Admin user {user.id} automatically granted access to model: {model_obj.id}")
        elif has_access(user.id, "read", model_obj.access_control):
            final_permitted_models.append(model_obj)
            log.info(f"[PinnedModels] User {user.id} granted access to model by has_access: {model_obj.id}")
        else:
            log.info(f"[PinnedModels] User {user.id} denied access to model by has_access: {model_obj.id}. Access control: {model_obj.access_control}")

    log.info(f"[PinnedModels] Found {len(final_permitted_models)} permitted, non-hidden, active, pinned models for user {user.id} (Role: {user.role}).")

    # Log the final list of models being returned
    returned_model_ids = [m.id for m in final_permitted_models]
    log.info(f"[PinnedModels] Returning {len(final_permitted_models)} models to user {user.id}: {returned_model_ids}")

    return final_permitted_models


############################
# CreateNewModel
############################


@router.post("/create", response_model=Optional[ModelModel])
async def create_new_model(
    request: Request,
    form_data: ModelForm,
    user=Depends(get_verified_user),
):
    if user.role != "admin" and not has_permission(
        user.id, "workspace.models", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    model = Models.get_model_by_id(form_data.id)
    if model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.MODEL_ID_TAKEN,
        )

    else:
        model = Models.insert_new_model(form_data, user.id)
        if model:
            return model
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.DEFAULT(),
            )


###########################
# GetModelById
###########################


# Note: We're not using the typical url path param here, but instead using a query parameter to allow '/' in the id
@router.get("/model", response_model=Optional[ModelResponse])
async def get_model_by_id(id: str, user=Depends(get_verified_user)):
    model = Models.get_model_by_id(id)
    if model:
        if (
            user.role == "admin"
            or model.user_id == user.id
            or has_access(user.id, "read", model.access_control)
        ):
            return model
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# ToggelModelById
############################


@router.post("/model/toggle", response_model=Optional[ModelResponse])
async def toggle_model_by_id(id: str, user=Depends(get_verified_user)):
    model = Models.get_model_by_id(id)
    if model:
        if (
            user.role == "admin"
            or model.user_id == user.id
            or has_access(user.id, "write", model.access_control)
        ):
            model = Models.toggle_model_by_id(id)

            if model:
                return model
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("Error updating function"),
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.UNAUTHORIZED,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# UpdateModelById
############################


@router.post("/model/update", response_model=Optional[ModelModel])
async def update_model_by_id(
    id: str,
    form_data: ModelForm,
    user=Depends(get_verified_user),
):
    model = Models.get_model_by_id(id)

    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        model.user_id != user.id
        and not has_access(user.id, "write", model.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    model = Models.update_model_by_id(id, form_data)
    return model


############################
# DeleteModelById
############################


@router.delete("/model/delete", response_model=bool)
async def delete_model_by_id(id: str, user=Depends(get_verified_user)):
    model = Models.get_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        user.role != "admin"
        and model.user_id != user.id
        and not has_access(user.id, "write", model.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    result = Models.delete_model_by_id(id)
    return result


@router.delete("/delete/all", response_model=bool)
async def delete_all_models(user=Depends(get_admin_user)):
    result = Models.delete_all_models()
    return result
