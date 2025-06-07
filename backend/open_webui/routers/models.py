from typing import Optional

from open_webui.models.models import (
    ModelForm,
    ModelModel,
    ModelResponse,
    ModelUserResponse,
    Models,
    Model, # Added for direct DB query if needed, though Models.get_all_models() is used
)
from open_webui.constants import ERROR_MESSAGES
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
    log.info(f"User {user.id} attempting to fetch pinned models.")

    # Fetch all models from the database (as per existing logic)
    all_db_models = Models.get_all_models()
    log.info(f"Total models fetched from DB: {len(all_db_models)}")

    # Initial filter for models marked as pinned in DB
    # This is slightly different from direct DB query but achieves similar logging start point
    initially_pinned_models = [m for m in all_db_models if m.pinned_to_sidebar]
    log.info(f"Found {len(initially_pinned_models)} models initially marked as pinned in DB for user {user.id}.")
    # Detailed log for initial pinned models (optional, can be verbose)
    # for m in initially_pinned_models:
    #     log.info(f"Initial Pinned - ID: {m.id}, Pinned: {m.pinned_to_sidebar}, Active: {m.is_active}, Meta: {m.meta.model_dump()}, Access: {m.access_control}")

    # Filter for active status
    active_models = [m for m in initially_pinned_models if m.is_active]
    log.info(f"Found {len(active_models)} active pinned models for user {user.id}.")

    # Filter for hidden status
    visible_models = []
    for m in active_models:
        # Safely access model.meta which is a Pydantic model ModelMeta
        hidden = False
        if m.meta:
            # model_dump() converts Pydantic model to dict for .get()
            hidden = m.meta.model_dump().get("hidden", False)

        if not hidden:
            visible_models.append(m)
    log.info(f"Found {len(visible_models)} non-hidden, active, pinned models for user {user.id}.")

    # Filter for permission
    permitted_models_responses = []
    for model_obj in visible_models: # model_obj is ModelModel instance
        if has_access(user.id, "read", model_obj.access_control):
            # Convert ModelModel to ModelResponse if necessary, though ModelResponse inherits from ModelModel
            # Assuming ModelModel can be directly appended if it matches ModelResponse structure
            permitted_models_responses.append(model_obj)

    log.info(f"Found {len(permitted_models_responses)} permitted, non-hidden, active, pinned models for user {user.id}.")

    # Log the final list of models being returned
    returned_model_ids = [m.id for m in permitted_models_responses]
    log.info(f"Returning {len(permitted_models_responses)} models to user {user.id}: {returned_model_ids}")

    return permitted_models_responses


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
