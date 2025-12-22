from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from open_webui.models.tags import (
    TagModel,
    AsyncTags,
)
from open_webui.constants import ERROR_MESSAGES
from open_webui.utils.auth import get_verified_user

router = APIRouter()

class TagForm(BaseModel):
    name: str

@router.get("/", response_model=list[TagModel])
async def get_tags(user=Depends(get_verified_user)):
    return await AsyncTags.get_tags_by_user_id(user.id)

@router.post("/add", response_model=Optional[TagModel])
async def add_tag(form_data: TagForm, user=Depends(get_verified_user)):
    tag = await AsyncTags.insert_new_tag(form_data.name, user.id)
    if tag:
        return tag
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error adding tag"),
    )

@router.post("/delete", response_model=bool)
async def delete_tag(form_data: TagForm, user=Depends(get_verified_user)):
    result = await AsyncTags.delete_tag_by_name_and_user_id(form_data.name, user.id)
    if result:
        return True
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error deleting tag"),
    )
