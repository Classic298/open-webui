import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
import mimetypes


from open_webui.models.folders import (
    FolderForm,
    FolderUpdateForm,
    FolderModel,
    FolderNameIdResponse,
    Folders,
    AsyncFolders,
)
from open_webui.models.chats import Chats, AsyncChats
from open_webui.models.files import Files, AsyncFiles
from open_webui.models.knowledge import Knowledges, AsyncKnowledges


from open_webui.config import UPLOAD_DIR
from open_webui.constants import ERROR_MESSAGES


from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status, Request
from fastapi.responses import FileResponse, StreamingResponse


from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.access_control import has_permission


log = logging.getLogger(__name__)


router = APIRouter()


############################
# Get Folders
############################


@router.get("/", response_model=list[FolderNameIdResponse])
async def get_folders(request: Request, user=Depends(get_verified_user)):
    if request.app.state.config.ENABLE_FOLDERS is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if user.role != "admin" and not has_permission(
        user.id,
        "features.folders",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    folders = await AsyncFolders.get_folders_by_user_id(user.id)

    # Verify folder data integrity
    folder_list = []
    for folder in folders:
        if folder.parent_id and not await AsyncFolders.get_folder_by_id_and_user_id(
            folder.parent_id, user.id
        ):
            folder = await AsyncFolders.update_folder_parent_id_by_id_and_user_id(
                folder.id, user.id, None
            )

        if folder.data:
            if "files" in folder.data:
                valid_files = []
                for file in folder.data["files"]:

                    if file.get("type") == "file":
                        if await AsyncFiles.check_access_by_user_id(
                            file.get("id"), user.id, "read"
                        ):
                            valid_files.append(file)
                    elif file.get("type") == "collection":
                        if await AsyncKnowledges.check_access_by_user_id(
                            file.get("id"), user.id, "read"
                        ):
                            valid_files.append(file)
                    else:
                        valid_files.append(file)

                folder.data["files"] = valid_files
                await AsyncFolders.update_folder_by_id_and_user_id(
                    folder.id, user.id, FolderUpdateForm(data=folder.data)
                )

        folder_list.append(FolderNameIdResponse(**folder.model_dump()))

    return folder_list


############################
# Create Folder
############################


@router.post("/")
async def create_folder(form_data: FolderForm, user=Depends(get_verified_user)):
    folder = await AsyncFolders.get_folder_by_parent_id_and_user_id_and_name(
        None, user.id, form_data.name
    )

    if folder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Folder already exists"),
        )

    try:
        folder = await AsyncFolders.insert_new_folder(user.id, form_data)
        return folder
    except Exception as e:
        log.exception(e)
        log.error("Error creating folder")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating folder"),
        )


############################
# Get Folders By Id
############################


@router.get("/{id}", response_model=Optional[FolderModel])
async def get_folder_by_id(id: str, user=Depends(get_verified_user)):
    folder = await AsyncFolders.get_folder_by_id_and_user_id(id, user.id)
    if folder:
        return folder
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Update Folder Name By Id
############################


@router.post("/{id}/update")
async def update_folder_name_by_id(
    id: str, form_data: FolderUpdateForm, user=Depends(get_verified_user)
):
    folder = await AsyncFolders.get_folder_by_id_and_user_id(id, user.id)
    if folder:

        if form_data.name is not None:
            # Check if folder with same name exists
            existing_folder = await AsyncFolders.get_folder_by_parent_id_and_user_id_and_name(
                folder.parent_id, user.id, form_data.name
            )
            if existing_folder and existing_folder.id != id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("Folder already exists"),
                )

        try:
            folder = await AsyncFolders.update_folder_by_id_and_user_id(id, user.id, form_data)
            return folder
        except Exception as e:
            log.exception(e)
            log.error(f"Error updating folder: {id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating folder"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Update Folder Parent Id By Id
############################


class FolderParentIdForm(BaseModel):
    parent_id: Optional[str] = None


@router.post("/{id}/update/parent")
async def update_folder_parent_id_by_id(
    id: str, form_data: FolderParentIdForm, user=Depends(get_verified_user)
):
    folder = await AsyncFolders.get_folder_by_id_and_user_id(id, user.id)
    if folder:
        existing_folder = await AsyncFolders.get_folder_by_parent_id_and_user_id_and_name(
            form_data.parent_id, user.id, folder.name
        )

        if existing_folder:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Folder already exists"),
            )

        try:
            folder = await AsyncFolders.update_folder_parent_id_by_id_and_user_id(
                id, user.id, form_data.parent_id
            )
            return folder
        except Exception as e:
            log.exception(e)
            log.error(f"Error updating folder: {id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating folder"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Update Folder Is Expanded By Id
############################


class FolderIsExpandedForm(BaseModel):
    is_expanded: bool


@router.post("/{id}/update/expanded")
async def update_folder_is_expanded_by_id(
    id: str, form_data: FolderIsExpandedForm, user=Depends(get_verified_user)
):
    folder = await AsyncFolders.get_folder_by_id_and_user_id(id, user.id)
    if folder:
        try:
            folder = await AsyncFolders.update_folder_is_expanded_by_id_and_user_id(
                id, user.id, form_data.is_expanded
            )
            return folder
        except Exception as e:
            log.exception(e)
            log.error(f"Error updating folder: {id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating folder"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Delete Folder By Id
############################


@router.delete("/{id}")
async def delete_folder_by_id(
    request: Request,
    id: str,
    delete_contents: Optional[bool] = True,
    user=Depends(get_verified_user),
):
    if await AsyncChats.count_chats_by_folder_id_and_user_id(id, user.id):
        chat_delete_permission = has_permission(
            user.id, "chat.delete", request.app.state.config.USER_PERMISSIONS
        )
        if user.role != "admin" and not chat_delete_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    folders = []
    folders.append(await AsyncFolders.get_folder_by_id_and_user_id(id, user.id))
    while folders:
        folder = folders.pop()
        if folder:
            try:
                folder_ids = await AsyncFolders.delete_folder_by_id_and_user_id(id, user.id)

                for folder_id in folder_ids:
                    if delete_contents:
                        await AsyncChats.delete_chats_by_user_id_and_folder_id(user.id, folder_id)
                    else:
                        await AsyncChats.move_chats_by_user_id_and_folder_id(
                            user.id, folder_id, None
                        )

                return True
            except Exception as e:
                log.exception(e)
                log.error(f"Error deleting folder: {id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("Error deleting folder"),
                )
            finally:
                # Get all subfolders
                subfolders = await AsyncFolders.get_folders_by_parent_id_and_user_id(
                    folder.id, user.id
                )
                folders.extend(subfolders)

    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
