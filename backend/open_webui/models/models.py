import asyncio
import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField, get_db

from open_webui.models.groups import Groups
from open_webui.models.users import User, UserModel, Users, UserResponse, Users


from pydantic import BaseModel, ConfigDict

from sqlalchemy import String, cast, or_, and_, func, select, delete
from sqlalchemy.dialects import postgresql, sqlite

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import BigInteger, Column, Text, JSON, Boolean


from open_webui.utils.access_control import has_access


log = logging.getLogger(__name__)


####################
# Models DB Schema
####################


# ModelParams is a model for the data stored in the params field of the Model table
class ModelParams(BaseModel):
    model_config = ConfigDict(extra="allow")
    pass


# ModelMeta is a model for the data stored in the meta field of the Model table
class ModelMeta(BaseModel):
    profile_image_url: Optional[str] = "/static/favicon.png"

    description: Optional[str] = None
    """
        User-facing description of the model.
    """

    capabilities: Optional[dict] = None

    model_config = ConfigDict(extra="allow")

    pass


class Model(Base):
    __tablename__ = "model"

    id = Column(Text, primary_key=True, unique=True)
    """
        The model's id as used in the API. If set to an existing model, it will override the model.
    """
    user_id = Column(Text)

    base_model_id = Column(Text, nullable=True)
    """
        An optional pointer to the actual model that should be used when proxying requests.
    """

    name = Column(Text)
    """
        The human-readable display name of the model.
    """

    params = Column(JSONField)
    """
        Holds a JSON encoded blob of parameters, see `ModelParams`.
    """

    meta = Column(JSONField)
    """
        Holds a JSON encoded blob of metadata, see `ModelMeta`.
    """

    access_control = Column(JSON, nullable=True)  # Controls data access levels.
    # Defines access control rules for this entry.
    # - `None`: Public access, available to all users with the "user" role.
    # - `{}`: Private access, restricted exclusively to the owner.
    # - Custom permissions: Specific access control for reading and writing;
    #   Can specify group or user-level restrictions:
    #   {
    #      "read": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      },
    #      "write": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      }
    #   }

    is_active = Column(Boolean, default=True)

    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)


class ModelModel(BaseModel):
    id: str
    user_id: str
    base_model_id: Optional[str] = None

    name: str
    params: ModelParams
    meta: ModelMeta

    access_control: Optional[dict] = None

    is_active: bool
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class ModelUserResponse(ModelModel):
    user: Optional[UserResponse] = None


class ModelResponse(ModelModel):
    pass


class ModelListResponse(BaseModel):
    items: list[ModelUserResponse]
    total: int


class ModelForm(BaseModel):
    id: str
    base_model_id: Optional[str] = None
    name: str
    meta: ModelMeta
    params: ModelParams
    access_control: Optional[dict] = None
    is_active: bool = True

class ModelsTable:
    """Table class for database operations."""
    
    async def insert_new_model(
        self, form_data: ModelForm, user_id: str
    ) -> Optional[ModelModel]:
        model = ModelModel(
            **form_data.model_dump(),
            user_id=user_id,
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        try:
            async with get_db() as db:
                result = Model(**model.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return ModelModel.model_validate(result) if result else None
        except Exception as e:
            log.exception(f"Failed to insert a new model: {e}")
            return None

    async def get_all_models(self) -> list[ModelModel]:
        async with get_db() as db:
            result = await db.execute(select(Model))
            models = result.scalars().all()
            return [ModelModel.model_validate(m) for m in models]

    async def get_models(self) -> list[ModelUserResponse]:
        async with get_db() as db:
            result = await db.execute(
                select(Model).where(Model.base_model_id != None)
            )
            all_models = result.scalars().all()
            
            user_ids = list(set(model.user_id for model in all_models))
            users = await Users.get_users_by_user_ids(user_ids) if user_ids else []
            users_dict = {user.id: user for user in users}
            
            models = []
            for model in all_models:
                user = users_dict.get(model.user_id)
                models.append(
                    ModelUserResponse.model_validate({
                        **ModelModel.model_validate(model).model_dump(),
                        "user": user.model_dump() if user else None,
                    })
                )
            return models

    async def get_base_models(self) -> list[ModelModel]:
        async with get_db() as db:
            result = await db.execute(
                select(Model).where(Model.base_model_id == None)
            )
            models = result.scalars().all()
            return [ModelModel.model_validate(m) for m in models]

    async def get_models_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ModelUserResponse]:
        models = await self.get_models()
        groups = await Groups.get_groups_by_member_id(user_id)
        user_group_ids = {group.id for group in groups}
        
        return [
            model
            for model in models
            if model.user_id == user_id
            or has_access(user_id, permission, model.access_control, user_group_ids)
        ]

    def _has_permission(self, query, filter: dict, dialect_name: str, permission: str = "read"):
        group_ids = filter.get("group_ids", [])
        user_id = filter.get("user_id")

        # Public access
        conditions = []
        if group_ids or user_id:
            conditions.extend(
                [
                    Model.access_control.is_(None),
                    cast(Model.access_control, String) == "null",
                ]
            )

        # User-level permission
        if user_id:
            conditions.append(Model.user_id == user_id)

        # Group-level permission
        if group_ids:
            group_conditions = []
            for gid in group_ids:
                if dialect_name == "sqlite":
                    group_conditions.append(
                        Model.access_control[permission]["group_ids"].contains([gid])
                    )
                elif dialect_name == "postgresql":
                    group_conditions.append(
                        cast(
                            Model.access_control[permission]["group_ids"],
                            JSONB,
                        ).contains([gid])
                    )
            conditions.append(or_(*group_conditions))

        if conditions:
            query = query.filter(or_(*conditions))

        return query

    async def search_models(
        self, user_id: str, filter: dict = {}, skip: int = 0, limit: int = 30
    ) -> ModelListResponse:
        async with get_db() as db:
            dialect_name = db.bind.dialect.name
            query = select(Model, User).outerjoin(User, User.id == Model.user_id)
            query = query.where(Model.base_model_id != None)

            if filter:
                query_key = filter.get("query")
                if query_key:
                    query = query.where(
                        or_(
                            Model.name.ilike(f"%{query_key}%"),
                            Model.base_model_id.ilike(f"%{query_key}%"),
                        )
                    )

                view_option = filter.get("view_option")
                if view_option == "created":
                    query = query.where(Model.user_id == user_id)
                elif view_option == "shared":
                    query = query.where(Model.user_id != user_id)

                # Apply access control filtering
                query = self._has_permission(
                    query,
                    filter,
                    dialect_name,
                    permission="write",
                )

                tag = filter.get("tag")
                if tag:
                    like_pattern = f'%"{tag.lower()}"%'  # `"tag"` inside JSON array
                    meta_text = func.lower(cast(Model.meta, String))
                    query = query.where(meta_text.like(like_pattern))

                order_by = filter.get("order_by")
                direction = filter.get("direction")

                if order_by == "name":
                    sort_col = Model.name
                elif order_by == "created_at":
                    sort_col = Model.created_at
                elif order_by == "updated_at":
                    sort_col = Model.updated_at
                else:
                    sort_col = Model.updated_at
                
                if direction == "asc":
                    query = query.order_by(sort_col.asc())
                else:
                    query = query.order_by(sort_col.desc())
            else:
                query = query.order_by(Model.created_at.desc())

            # Count before pagination
            count_res = await db.execute(select(func.count()).select_from(query.subquery()))
            total = count_res.scalar() or 0

            if skip:
                query = query.offset(skip)
            if limit:
                query = query.limit(limit)

            result = await db.execute(query)
            items = result.all()

            models = []
            for model, user in items:
                models.append(
                    ModelUserResponse(
                        **ModelModel.model_validate(model).model_dump(),
                        user=(
                            UserResponse(**UserModel.model_validate(user).model_dump())
                            if user
                            else None
                        ),
                    )
                )

            return ModelListResponse(items=models, total=total)

    async def get_model_by_id(self, id: str) -> Optional[ModelModel]:
        try:
            async with get_db() as db:
                model = await db.get(Model, id)
                return ModelModel.model_validate(model) if model else None
        except Exception:
            return None

    async def get_models_by_ids(self, ids: list[str]) -> list[ModelModel]:
        try:
            async with get_db() as db:
                result = await db.execute(select(Model).where(Model.id.in_(ids)))
                models = result.scalars().all()
                return [ModelModel.model_validate(m) for m in models]
        except Exception:
            return []

    async def toggle_model_by_id(self, id: str) -> Optional[ModelModel]:
        async with get_db() as db:
            try:
                result = await db.execute(select(Model).where(Model.id == id))
                model = result.scalar_one_or_none()
                if not model:
                    return None
                
                from sqlalchemy import update
                await db.execute(
                    update(Model).where(Model.id == id).values(
                        is_active=not model.is_active,
                        updated_at=int(time.time())
                    )
                )
                await db.commit()
                return await self.get_model_by_id(id)
            except Exception:
                return None

    async def update_model_by_id(self, id: str, model_form: ModelForm) -> Optional[ModelModel]:
        try:
            async with get_db() as db:
                from sqlalchemy import update
                data = model_form.model_dump(exclude={"id"})
                await db.execute(
                    update(Model).where(Model.id == id).values(**data)
                )
                await db.commit()
                
                model = await db.get(Model, id)
                await db.refresh(model)
                return ModelModel.model_validate(model)
        except Exception as e:
            log.exception(f"Failed to update the model by id {id}: {e}")
            return None

    async def delete_model_by_id(self, id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Model).where(Model.id == id))
                await db.commit()
                return True
        except Exception:
            return False

    async def delete_all_models(self) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Model))
                await db.commit()
                return True
        except Exception:
            return False

    async def sync_models(self, user_id: str, models: list[ModelModel]) -> list[ModelModel]:
        try:
            async with get_db() as db:
                # Get existing models
                result = await db.execute(select(Model))
                existing_models = result.scalars().all()
                existing_ids = {model.id for model in existing_models}

                # Prepare a set of new model IDs
                new_model_ids = {model.id for model in models}

                # Update or insert models
                for model in models:
                    if model.id in existing_ids:
                        from sqlalchemy import update
                        await db.execute(
                            update(Model)
                            .where(Model.id == model.id)
                            .values(
                                **model.model_dump(),
                                user_id=user_id,
                                updated_at=int(time.time()),
                            )
                        )
                    else:
                        new_model = Model(
                            **{
                                **model.model_dump(),
                                "user_id": user_id,
                                "updated_at": int(time.time()),
                            }
                        )
                        db.add(new_model)

                # Remove models that are no longer present
                for model in existing_models:
                    if model.id not in new_model_ids:
                        await db.delete(model)

                await db.commit()

                result = await db.execute(select(Model))
                models = result.scalars().all()
                return [ModelModel.model_validate(model) for model in models]
        except Exception as e:
            log.exception(f"Error syncing models for user {user_id}: {e}")
            return []


# Module instance
Models = ModelsTable()


