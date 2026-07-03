"""Comments on titles (global across users), with likes."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Comment, CommentLike, MediaType, User
from ..schemas import CommentCreate

router = APIRouter(prefix="/comments", tags=["comments"])


def _comment_out(c: Comment, me: User) -> dict:
    return {
        "id": c.id,
        "user_id": c.user_id,
        "username": c.author.username,
        "text": c.text,
        "created_at": c.created_at,
        "likes": len(c.likes),
        "liked_by_me": any(like.user_id == me.id for like in c.likes),
        "mine": c.user_id == me.id,
    }


def _target_filter(query, media_type: MediaType, tmdb_id: int | None, title: str | None):
    query = query.filter(Comment.media_type == media_type)
    if tmdb_id is not None:
        return query.filter(Comment.tmdb_id == tmdb_id)
    if title:
        return query.filter(Comment.tmdb_id.is_(None), Comment.title_key == title)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Provide tmdb_id or title",
    )


@router.get("")
def list_comments(
    media_type: MediaType,
    tmdb_id: int | None = Query(default=None, ge=1),
    title: str | None = Query(default=None, max_length=300),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    query = _target_filter(db.query(Comment), media_type, tmdb_id, title)
    comments = query.order_by(Comment.created_at.desc()).limit(100).all()
    return [_comment_out(c, me) for c in comments]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_comment(
    data: CommentCreate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if data.tmdb_id is None and not data.title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide tmdb_id or title",
        )
    comment = Comment(
        user_id=me.id,
        media_type=data.media_type,
        tmdb_id=data.tmdb_id,
        title_key=None if data.tmdb_id is not None else data.title,
        text=data.text.strip(),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return _comment_out(comment, me)


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    comment = db.get(Comment, comment_id)
    if comment is None or comment.user_id != me.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.delete(comment)
    db.commit()


@router.post("/{comment_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def like_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    already = (
        db.query(CommentLike)
        .filter(CommentLike.comment_id == comment_id, CommentLike.user_id == me.id)
        .first()
    )
    if not already:
        db.add(CommentLike(comment_id=comment_id, user_id=me.id))
        db.commit()


@router.delete("/{comment_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def unlike_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    like = (
        db.query(CommentLike)
        .filter(CommentLike.comment_id == comment_id, CommentLike.user_id == me.id)
        .first()
    )
    if like:
        db.delete(like)
        db.commit()
