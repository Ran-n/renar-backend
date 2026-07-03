import base64
import io

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from PIL import Image
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import create_access_token, get_current_user, hash_password, verify_password
from ..database import get_db
from ..models import Comment, CommentLike, Follow, Notification, User
from ..schemas import PasswordChange, ProfileUpdate, Token, UserCreate, UserOut

AVATAR_SIZE = 256


def _process_avatar(avatar_b64: str) -> str:
    """Decode, downscale to 256px JPEG, and re-encode as base64."""
    try:
        img = Image.open(io.BytesIO(base64.b64decode(avatar_b64)))
        img = img.convert("RGB")
        img.thumbnail((AVATAR_SIZE, AVATAR_SIZE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return base64.b64encode(out.getvalue()).decode()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not read that image file",
        )

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(
        or_(User.username == data.username, User.email == data.email)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        )
    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # form.username accepts either username or email
    user = db.query(User).filter(
        or_(User.username == form.username, User.email == form.username)
    ).first()
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/profile", response_model=UserOut)
def update_profile(
    data: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if data.username and data.username != user.username:
        if db.query(User).filter(User.username == data.username).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Username already taken")
        user.username = data.username
    if data.email and data.email != user.email:
        if db.query(User).filter(User.email == data.email).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Email already taken")
        user.email = data.email
    if data.avatar_b64 is not None:
        user.avatar = _process_avatar(data.avatar_b64) if data.avatar_b64 else None
    db.commit()
    db.refresh(user)
    return user


@router.post("/change_password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    data: PasswordChange,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    user.password_hash = hash_password(data.new_password)
    db.commit()


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # social artifacts don't cascade from User — clean them up explicitly
    my_comment_ids = [c.id for c in db.query(Comment.id).filter(Comment.user_id == user.id)]
    likes = db.query(CommentLike).filter(CommentLike.user_id == user.id)
    if my_comment_ids:
        likes = db.query(CommentLike).filter(
            or_(CommentLike.user_id == user.id,
                CommentLike.comment_id.in_(my_comment_ids))
        )
    likes.delete(synchronize_session=False)
    db.query(Comment).filter(Comment.user_id == user.id).delete(synchronize_session=False)
    db.query(Follow).filter(
        or_(Follow.follower_id == user.id, Follow.followed_id == user.id)
    ).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == user.id).delete(
        synchronize_session=False
    )
    db.delete(user)  # media items + episode watches cascade via the ORM relationship
    db.commit()
