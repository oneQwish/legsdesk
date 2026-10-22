from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..logic import log
from ..models import User
from ..schemas import LoginIn, UserOut
from ..security import (COOKIE, AuthError, Principal, authenticate, current_principal, make_session_token,
                        normalize_login, throttle)

router = APIRouter(prefix="/api/v1/auth", tags=["Вход"])


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key, ip = normalize_login(body.login), request.client.host if request.client else ""
    minutes = throttle.blocked_for(key, ip)
    if minutes:
        raise HTTPException(429, f"Слишком много неудачных попыток. Попробуйте через {minutes} мин.")
    try:
        user = authenticate(db, body.login, body.password)
    except AuthError as e:
        if e.unavailable:
            raise HTTPException(503, str(e)) from None
        throttle.failed(key, ip)
        raise HTTPException(401, str(e)) from None
    throttle.succeeded(key, ip)
    s = get_settings()
    response.set_cookie(COOKIE, make_session_token(user), httponly=True, samesite="strict",
                        secure=s.cookie_secure, max_age=s.session_hours * 3600)
    log(db, Principal("user", user.login), "login", "user", user.id)
    db.commit()
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE)


@router.get("/me")
def me(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    if p.kind == "service":
        return {"kind": "service", "name": p.name, "scopes": sorted(p.scopes)}
    u = db.get(User, p.user_id)
    return {"kind": "user", **UserOut.model_validate(u).model_dump(mode="json"), "auth_mode": get_settings().auth_mode}
