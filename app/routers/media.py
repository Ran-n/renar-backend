from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import MediaItem, MediaType, User, WatchStatus
from ..schemas import MediaItemCreate, MediaItemOut, MediaItemUpdate

router = APIRouter(prefix="/media", tags=["media"])


def _get_owned_item(item_id: int, user: User, db: Session) -> MediaItem:
    item = db.get(MediaItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return item


@router.get("", response_model=list[MediaItemOut])
def list_media(
    media_type: MediaType | None = None,
    status_filter: WatchStatus | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(MediaItem).filter(MediaItem.user_id == user.id)
    if media_type is not None:
        query = query.filter(MediaItem.media_type == media_type)
    if status_filter is not None:
        query = query.filter(MediaItem.status == status_filter)
    if search:
        query = query.filter(MediaItem.title.ilike(f"%{search}%"))
    return query.order_by(MediaItem.updated_at.desc()).all()


@router.post("", response_model=MediaItemOut, status_code=status.HTTP_201_CREATED)
def create_media(
    data: MediaItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    duplicate = db.query(MediaItem).filter(
        MediaItem.user_id == user.id,
        MediaItem.media_type == data.media_type,
        MediaItem.title == data.title,
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already saved this title",
        )
    item = MediaItem(user_id=user.id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=MediaItemOut)
def get_media(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _get_owned_item(item_id, user, db)


@router.patch("/{item_id}", response_model=MediaItemOut)
def update_media(
    item_id: int,
    data: MediaItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    db.delete(item)
    db.commit()
