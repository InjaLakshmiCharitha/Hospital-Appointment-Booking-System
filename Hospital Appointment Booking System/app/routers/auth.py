import os
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User, UserRole, RefreshToken
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    UserResponse,
    TokenResponse,
    RefreshRequest,
    MessageResponse,
    AdminCreateUserRequest,
    InitialAdminRequest
)
from app.auth.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_refresh_token,
)
from app.auth.dependencies import get_current_user, require_roles


router = APIRouter(prefix="/auth", tags=["Authentication"])


def invalid_refresh_token():
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid, expired, or revoked refresh token",
    )


def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post(
    "/setup-initial-admin",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def setup_initial_admin(
    data: InitialAdminRequest,
    db: Session = Depends(get_db),
):
    setup_key = os.getenv("INITIAL_ADMIN_SETUP_KEY")

    if not setup_key or data.setup_key != setup_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid initial admin setup key",
        )

    existing_admin = db.query(User).filter(
        User.role == UserRole.ADMIN
    ).first()

    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An administrator already exists",
        )

    existing_user = db.query(User).filter(
        User.email == str(data.email)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    admin = User(
        full_name=data.full_name,
        email=str(data.email),
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role=UserRole.ADMIN,
        is_active=True,
    )

    db.add(admin)
    db.commit()
    db.refresh(admin)

    return admin


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_patient(
    data: RegisterRequest,
    db: Session = Depends(get_db),
):
    existing_user = db.query(User).filter(
        User.email == str(data.email)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    patient = User(
        full_name=data.full_name,
        email=str(data.email),
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role=UserRole.PATIENT,
        is_active=True,
    )

    db.add(patient)
    db.commit()
    db.refresh(patient)

    return patient


@router.post(
    "/admin/create-user",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_user(
    data: AdminCreateUserRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_roles("admin")),
):
    role_value = data.role.strip().lower()

    if role_value not in ("doctor", "admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only doctor or admin roles can be created here",
        )

    existing_user = db.query(User).filter(
        User.email == str(data.email)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    new_user = User(
        full_name=data.full_name,
        email=str(data.email),
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role=UserRole(role_value),
        is_active=True,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.email == str(data.email)
    ).first()

    if user is None or not verify_password(
        data.password,
        user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is inactive",
        )

    access_token = create_access_token(
        user_id=user.id,
        role=user.role.value,
    )

    refresh_token = create_refresh_token(user.id)

    refresh_payload = decode_token(refresh_token)
    expires_at = datetime.fromtimestamp(
        refresh_payload["exp"],
        tz=timezone.utc,
    ).replace(tzinfo=None)

    stored_token = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        expires_at=expires_at,
        revoked=False,
    )

    db.add(stored_token)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_access_token(
    data: RefreshRequest,
    db: Session = Depends(get_db),
):
    try:
        payload = decode_token(data.refresh_token)

        if payload.get("type") != "refresh":
            raise invalid_refresh_token()

        user_id = int(payload["sub"])

    except (
        jwt.InvalidTokenError,
        KeyError,
        TypeError,
        ValueError,
    ):
        raise invalid_refresh_token()

    supplied_hash = hash_refresh_token(data.refresh_token)

    stored_token = db.query(RefreshToken).filter(
        RefreshToken.token_hash == supplied_hash,
        RefreshToken.user_id == user_id,
        RefreshToken.revoked.is_(False),
        RefreshToken.expires_at > utc_now_naive(),
    ).first()

    if stored_token is None:
        raise invalid_refresh_token()

    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if user is None:
        raise invalid_refresh_token()

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is inactive",
        )

    stored_token.revoked = True

    new_access_token = create_access_token(
        user_id=user.id,
        role=user.role.value,
    )

    new_refresh_token = create_refresh_token(user.id)

    new_payload = decode_token(new_refresh_token)
    new_expires_at = datetime.fromtimestamp(
        new_payload["exp"],
        tz=timezone.utc,
    ).replace(tzinfo=None)

    new_stored_token = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(new_refresh_token),
        expires_at=new_expires_at,
        revoked=False,
    )

    db.add(new_stored_token)
    db.commit()

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    data: RefreshRequest,
    db: Session = Depends(get_db),
):
    supplied_hash = hash_refresh_token(data.refresh_token)

    stored_token = db.query(RefreshToken).filter(
        RefreshToken.token_hash == supplied_hash,
        RefreshToken.revoked.is_(False),
    ).first()

    if stored_token is None:
        raise invalid_refresh_token()

    stored_token.revoked = True
    db.commit()

    return MessageResponse(
        message="Logged out successfully"
    )


@router.get("/me", response_model=UserResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return current_user

