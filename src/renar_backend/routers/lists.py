#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 12:36:14.018888
Revised: 2026/09/03 08:33:31.134009

Custom lists: user-made collections of titles, independent of LibraryEntry's
own tracking status. See models.py's List/ListItem docstrings.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..catalog.titles import find_or_create_title, find_title
from ..database import get_db
from ..models import List, ListItem, User
from ..schemas import ListCreate, ListDetailOut, ListItemCreate, ListItemOut, ListItemReorder, ListOut, ListUpdate
from ..users.auth import get_current_user

router = APIRouter(prefix="/lists", tags=["lists"])
_log = logging.getLogger(__name__)


def _require_target(tmdb_id: int | None, title: str | None) -> None:
    if tmdb_id is None and not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide tmdb_id or title",
        )


def _item_out(item: ListItem) -> dict:
    t = item.title_ref
    return {
        "id": item.id,
        "title_id": t.id,
        "media_type": t.media_type,
        "tmdb_id": t.tmdb_id,
        "title": t.title,
        "poster_url": t.poster_url,
        "position": item.position,
    }


def _list_out(lst: List, with_items: bool = False) -> dict:
    out = {
        "id": lst.id,
        "name": lst.name,
        "item_count": len(lst.items),
        "created_at": lst.created_at,
        "updated_at": lst.updated_at,
    }
    if with_items:
        out["items"] = [_item_out(item) for item in sorted(lst.items, key=lambda i: i.position)]
    return out


def _get_owned_list(db: Session, list_id: int, me: User, *, with_items: bool = False) -> List:
    query = db.query(List)
    if with_items:
        query = query.options(selectinload(List.items).selectinload(ListItem.title_ref))
    lst = query.filter(List.id == list_id).first()
    if lst is None or lst.user_id != me.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return lst


@router.get("", response_model=list[ListOut])
def list_lists(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    lists = (
        db.query(List)
        .filter(List.user_id == me.id)
        .options(selectinload(List.items))
        .order_by(List.created_at.desc())
        .all()
    )
    return [_list_out(lst) for lst in lists]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ListOut)
def create_list(data: ListCreate, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    lst = List(user_id=me.id, name=data.name.strip())
    db.add(lst)
    db.commit()
    db.refresh(lst)
    return _list_out(lst)


@router.get("/{list_id}", response_model=ListDetailOut)
def get_list(list_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    lst = _get_owned_list(db, list_id, me, with_items=True)
    return _list_out(lst, with_items=True)


@router.patch("/{list_id}", response_model=ListOut)
def rename_list(list_id: int, data: ListUpdate, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    lst = _get_owned_list(db, list_id, me)
    lst.name = data.name.strip()
    db.commit()
    db.refresh(lst)
    return _list_out(lst)


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_list(list_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    lst = _get_owned_list(db, list_id, me)
    db.delete(lst)  # ORM delete cascades ListItem rows (cascade="all, delete-orphan")
    db.commit()


@router.post("/{list_id}/items", status_code=status.HTTP_201_CREATED, response_model=ListItemOut)
def add_list_item(
    list_id: int,
    data: ListItemCreate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    lst = _get_owned_list(db, list_id, me, with_items=True)
    _require_target(data.tmdb_id, data.title)
    if data.tmdb_id is not None and not data.title:
        # a Title row may not exist yet, and one cannot be created nameless
        target = find_title(db, data.media_type, data.tmdb_id, None)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Provide title for a tmdb_id not seen before",
            )
    else:
        target = find_or_create_title(db, data.media_type, data.tmdb_id, data.title)
    already = next((item for item in lst.items if item.title_id == target.id), None)
    if already is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Title already in this list")
    next_position = (max((item.position for item in lst.items), default=-1)) + 1
    item = ListItem(list_id=lst.id, title_id=target.id, position=next_position)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Title already in this list") from None
    db.refresh(item)
    return _item_out(item)


@router.delete("/{list_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_list_item(
    list_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    lst = _get_owned_list(db, list_id, me)
    item = db.get(ListItem, item_id)
    if item is None or item.list_id != lst.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.delete(item)
    db.commit()


@router.put("/{list_id}/items/reorder", response_model=ListDetailOut)
def reorder_list_items(
    list_id: int,
    data: ListItemReorder,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    lst = _get_owned_list(db, list_id, me, with_items=True)
    existing_ids = {item.id for item in lst.items}
    if set(data.item_ids) != existing_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="item_ids must contain every item in this list exactly once",
        )
    items_by_id = {item.id: item for item in lst.items}
    for position, item_id in enumerate(data.item_ids):
        items_by_id[item_id].position = position
    db.commit()
    return _list_out(lst, with_items=True)
