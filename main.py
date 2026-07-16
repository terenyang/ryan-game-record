from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

import bcrypt as _bcrypt
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from models import Game, Record, User, get_db, init_db, seed_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_admin()
    yield


app = FastAPI(title="游戏记录", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key="game-record-secret-key-change-in-prod")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Auth helpers ──────────────────────────────────────────────────────────────

class NotAuthenticated(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/login", status_code=303)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise NotAuthenticated()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        raise NotAuthenticated()
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ── Login / Logout ────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not _bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        return templates.TemplateResponse(
            request, "login.html", {"error": "用户名或密码错误"}, status_code=401
        )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = (
        db.query(Record)
        .filter(Record.user_id == user.id)
        .order_by(Record.date.desc())
        .limit(10)
        .all()
    )
    return templates.TemplateResponse(request, "index.html", {"user": user, "records": records})


# ── Records ───────────────────────────────────────────────────────────────────

@app.get("/records", response_class=HTMLResponse)
def list_records(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = (
        db.query(Record)
        .filter(Record.user_id == user.id)
        .order_by(Record.date.desc())
        .all()
    )
    return templates.TemplateResponse(request, "records/list.html", {"user": user, "records": records})


@app.get("/records/new", response_class=HTMLResponse)
def new_record_form(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    games = db.query(Game).order_by(Game.name).all()
    return templates.TemplateResponse(
        request,
        "records/form.html",
        {"user": user, "games": games, "record": None, "today": date.today().isoformat(), "error": None},
    )


@app.post("/records/new", response_class=HTMLResponse)
def create_record(
    request: Request,
    game_id: int = Form(...),
    record_date: str = Form(...),
    hours: float = Form(...),
    notes: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if hours <= 0 or hours > 24:
        games = db.query(Game).order_by(Game.name).all()
        return templates.TemplateResponse(
            request,
            "records/form.html",
            {"user": user, "games": games, "record": None, "today": record_date, "error": "游戏时长必须在 0 到 24 小时之间"},
            status_code=400,
        )
    db.add(Record(user_id=user.id, game_id=game_id, date=date.fromisoformat(record_date), hours=hours, notes=notes.strip()))
    db.commit()
    return RedirectResponse(url="/records", status_code=303)


@app.get("/records/{record_id}/edit", response_class=HTMLResponse)
def edit_record_form(
    record_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(Record).filter(Record.id == record_id, Record.user_id == user.id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    games = db.query(Game).order_by(Game.name).all()
    return templates.TemplateResponse(
        request,
        "records/form.html",
        {"user": user, "games": games, "record": record, "today": record.date.isoformat(), "error": None},
    )


@app.post("/records/{record_id}/edit", response_class=HTMLResponse)
def update_record(
    record_id: int,
    request: Request,
    game_id: int = Form(...),
    record_date: str = Form(...),
    hours: float = Form(...),
    notes: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(Record).filter(Record.id == record_id, Record.user_id == user.id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    if hours <= 0 or hours > 24:
        games = db.query(Game).order_by(Game.name).all()
        return templates.TemplateResponse(
            request,
            "records/form.html",
            {"user": user, "games": games, "record": record, "today": record_date, "error": "游戏时长必须在 0 到 24 小时之间"},
            status_code=400,
        )
    record.game_id = game_id
    record.date = date.fromisoformat(record_date)
    record.hours = hours
    record.notes = notes.strip()
    db.commit()
    return RedirectResponse(url="/records", status_code=303)


@app.post("/records/{record_id}/delete")
def delete_record(
    record_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(Record).filter(Record.id == record_id, Record.user_id == user.id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(record)
    db.commit()
    return RedirectResponse(url="/records", status_code=303)


# ── Admin: Users ──────────────────────────────────────────────────────────────

@app.get("/admin/users", response_class=HTMLResponse)
def admin_list_users(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.username).all()
    return templates.TemplateResponse(request, "admin/users.html", {"user": admin, "users": users, "error": None})


@app.get("/admin/users/new", response_class=HTMLResponse)
def admin_new_user_form(request: Request, admin: User = Depends(require_admin)):
    return templates.TemplateResponse(request, "admin/user_form.html", {"user": admin, "edit_user": None, "error": None})


@app.post("/admin/users/new", response_class=HTMLResponse)
def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    is_admin: Optional[str] = Form(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    username = username.strip()
    if not username:
        return templates.TemplateResponse(
            request, "admin/user_form.html", {"user": admin, "edit_user": None, "error": "用户名不能为空"}, status_code=400
        )
    if not password:
        return templates.TemplateResponse(
            request, "admin/user_form.html", {"user": admin, "edit_user": None, "error": "密码不能为空"}, status_code=400
        )
    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse(
            request, "admin/user_form.html", {"user": admin, "edit_user": None, "error": f"用户名 '{username}' 已存在"}, status_code=400
        )
    pw_hash = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    db.add(User(username=username, password_hash=pw_hash, is_admin=is_admin is not None))
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def admin_edit_user_form(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    edit_user = db.query(User).filter(User.id == user_id).first()
    if not edit_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return templates.TemplateResponse(request, "admin/user_form.html", {"user": admin, "edit_user": edit_user, "error": None})


@app.post("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def admin_update_user(
    user_id: int,
    request: Request,
    username: str = Form(...),
    password: str = Form(""),
    is_admin: Optional[str] = Form(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    edit_user = db.query(User).filter(User.id == user_id).first()
    if not edit_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    username = username.strip()
    if not username:
        return templates.TemplateResponse(
            request, "admin/user_form.html", {"user": admin, "edit_user": edit_user, "error": "用户名不能为空"}, status_code=400
        )
    if db.query(User).filter(User.username == username, User.id != user_id).first():
        return templates.TemplateResponse(
            request, "admin/user_form.html", {"user": admin, "edit_user": edit_user, "error": f"用户名 '{username}' 已存在"}, status_code=400
        )
    new_is_admin = is_admin is not None
    if edit_user.id == admin.id:
        new_is_admin = True  # can't revoke own admin
    edit_user.username = username
    if password:
        edit_user.password_hash = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    edit_user.is_admin = new_is_admin
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/delete")
def admin_delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账户")
    edit_user = db.query(User).filter(User.id == user_id).first()
    if not edit_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.delete(edit_user)
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


# ── Admin: Games ──────────────────────────────────────────────────────────────

@app.get("/admin/games", response_class=HTMLResponse)
def admin_list_games(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    games = db.query(Game).order_by(Game.name).all()
    return templates.TemplateResponse(request, "admin/games.html", {"user": admin, "games": games, "error": None})


@app.post("/admin/games/new", response_class=HTMLResponse)
def admin_create_game(
    request: Request,
    name: str = Form(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        games = db.query(Game).order_by(Game.name).all()
        return templates.TemplateResponse(
            request, "admin/games.html", {"user": admin, "games": games, "error": "游戏名称不能为空"}, status_code=400
        )
    if db.query(Game).filter(Game.name == name).first():
        games = db.query(Game).order_by(Game.name).all()
        return templates.TemplateResponse(
            request, "admin/games.html", {"user": admin, "games": games, "error": f"游戏 '{name}' 已存在"}, status_code=400
        )
    db.add(Game(name=name))
    db.commit()
    return RedirectResponse(url="/admin/games", status_code=303)


@app.post("/admin/games/{game_id}/delete", response_class=HTMLResponse)
def admin_delete_game(
    game_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="游戏不存在")
    if db.query(Record).filter(Record.game_id == game_id).first():
        games = db.query(Game).order_by(Game.name).all()
        return templates.TemplateResponse(
            request,
            "admin/games.html",
            {"user": admin, "games": games, "error": f"无法删除游戏 '{game.name}'，该游戏已有关联记录"},
            status_code=400,
        )
    db.delete(game)
    db.commit()
    return RedirectResponse(url="/admin/games", status_code=303)
