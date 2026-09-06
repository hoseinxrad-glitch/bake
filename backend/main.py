import datetime
import os
import uuid
import asyncio
from typing import List, Optional, Dict

from fastapi import (
    FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect,
    Query, UploadFile, File, Form, Header,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from database import Base, engine, get_db, SessionLocal
import models
import auth
import ai_bot

Base.metadata.create_all(bind=engine)

BOT_USERNAME = "ai_assistant"


def get_or_create_bot(db: Session) -> models.User:
    bot = db.query(models.User).filter(models.User.username == BOT_USERNAME).first()
    if bot:
        return bot
    bot = models.User(
        username=BOT_USERNAME,
        display_name="دستیار هوشمند",
        hashed_password=auth.hash_password(os.urandom(16).hex()),
        is_bot=True,
        is_online=True,
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot


_startup_db = SessionLocal()
try:
    _bot_user = get_or_create_bot(_startup_db)
    BOT_USER_ID = _bot_user.id

    _saved_model = _startup_db.query(models.AppSetting).filter(models.AppSetting.key == "ai_model").first()
    if _saved_model and _saved_model.value:
        ai_bot.set_model(_saved_model.value)

    _saved_keys = _startup_db.query(models.AppSetting).filter(models.AppSetting.key == "ai_api_keys").first()
    if _saved_keys and _saved_keys.value:
        _keys_list = [k.strip() for k in _saved_keys.value.split(",") if k.strip()]
        if _keys_list:
            ai_bot.set_api_keys(_keys_list)

    _saved_stt = _startup_db.query(models.AppSetting).filter(models.AppSetting.key == "ai_stt_model").first()
    if _saved_stt and _saved_stt.value:
        ai_bot.set_stt_model(_saved_stt.value)

    _saved_tts = _startup_db.query(models.AppSetting).filter(models.AppSetting.key == "ai_tts_model").first()
    if _saved_tts and _saved_tts.value:
        ai_bot.set_tts_model(_saved_tts.value)

    _saved_voice = _startup_db.query(models.AppSetting).filter(models.AppSetting.key == "ai_tts_voice").first()
    if _saved_voice and _saved_voice.value:
        ai_bot.set_tts_voice(_saved_voice.value)
finally:
    _startup_db.close()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25MB
ALLOWED_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp"},
    "voice": {".webm", ".ogg", ".mp3", ".wav", ".m4a"},
    "file": None,  # any extension allowed for generic files
}

app = FastAPI(title="Chatyar API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "بک‌اند چت‌یار در حال اجراست. این آدرس فقط API میده — فرانت‌اند رو جدا از فولدر frontend سرو کن (مثلاً پورت 5500) و از اونجا وارد شو.",
        "docs": "/docs",
    }


# ---------- Schemas ----------

class RegisterIn(BaseModel):
    username: str
    display_name: str
    password: str


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    display_name: str
    is_admin: bool = False


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    is_online: bool
    is_admin: bool = False
    is_banned: bool = False
    is_bot: bool = False

    class Config:
        from_attributes = True


class AdminStatsOut(BaseModel):
    total_users: int
    online_users: int
    total_rooms: int
    total_messages: int
    banned_users: int


class AdminRoomOut(BaseModel):
    id: int
    name: Optional[str]
    is_group: bool
    member_count: int
    message_count: int
    created_at: datetime.datetime


class RoomCreateIn(BaseModel):
    is_group: bool
    name: Optional[str] = None
    member_ids: List[int]
    room_type: Optional[str] = None  # "group" یا "channel" (فقط وقتی is_group=true معنا دارد)


class RoomOut(BaseModel):
    id: int
    name: Optional[str]
    is_group: bool
    room_type: str = "direct"
    created_by: Optional[int] = None
    members: List[UserOut]

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    room_id: int
    sender_id: int
    sender_name: str
    content: Optional[str] = None
    message_type: str = "text"
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class UploadOut(BaseModel):
    file_url: str
    file_name: str
    file_size: int
    message_type: str


# ---------- Auth dependency ----------

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    if not token:
        raise HTTPException(status_code=401, detail="توکن ارسال نشده")
    payload = auth.decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="توکن نامعتبر است")
    user = db.query(models.User).filter(models.User.id == payload.get("sub")).first()
    if not user:
        raise HTTPException(status_code=401, detail="کاربر یافت نشد")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="حساب شما مسدود شده است")
    return user


# رمز ورود به پنل ادمین — هر کاربر لاگین‌شده‌ای که این رمز را بدهد (حتی اگر ادمین نباشد)
# به پنل ادمین دسترسی پیدا می‌کند. برای امنیت بیشتر می‌توانی این را با متغیر محیطی
# ADMIN_PANEL_PASSWORD عوض کنی، در غیر این صورت مقدار پیش‌فرض زیر استفاده می‌شود.
ADMIN_PANEL_PASSWORD = os.environ.get("ADMIN_PANEL_PASSWORD", "132465798")


def get_current_admin(
    current_user: models.User = Depends(get_current_user),
    x_admin_password: Optional[str] = Header(default=None),
) -> models.User:
    if current_user.is_admin:
        return current_user
    if x_admin_password and x_admin_password == ADMIN_PANEL_PASSWORD:
        return current_user
    raise HTTPException(status_code=403, detail="رمز پنل ادمین اشتباه است")


# ---------- Auth endpoints ----------

@app.post("/register", response_model=TokenOut)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.username == data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="این نام کاربری قبلا ثبت شده")
    is_first_user = db.query(models.User).count() == 0
    user = models.User(
        username=data.username,
        display_name=data.display_name,
        hashed_password=auth.hash_password(data.password),
        is_admin=is_first_user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = auth.create_access_token({"sub": str(user.id)})
    return TokenOut(access_token=token, user_id=user.id, username=user.username,
                     display_name=user.display_name, is_admin=user.is_admin)


@app.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == data.username).first()
    if not user or not auth.verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز عبور اشتباه است")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="حساب شما مسدود شده است")
    token = auth.create_access_token({"sub": str(user.id)})
    return TokenOut(access_token=token, user_id=user.id, username=user.username,
                     display_name=user.display_name, is_admin=user.is_admin)


@app.get("/me", response_model=UserOut)
def me(current_user: models.User = Depends(get_current_user)):
    return current_user


# ---------- Users ----------

@app.get("/users", response_model=List[UserOut])
def list_users(q: Optional[str] = None, db: Session = Depends(get_db),
                current_user: models.User = Depends(get_current_user)):
    query = db.query(models.User).filter(
        models.User.id != current_user.id, models.User.is_bot == False
    )
    if q:
        query = query.filter(models.User.display_name.contains(q))
    return query.all()


@app.get("/assistant/room", response_model=RoomOut)
def get_assistant_room(db: Session = Depends(get_db),
                        current_user: models.User = Depends(get_current_user)):
    bot = db.query(models.User).filter(models.User.id == BOT_USER_ID).first()
    existing_rooms = (
        db.query(models.Room)
        .filter(models.Room.is_group == False)
        .join(models.room_members)
        .filter(models.room_members.c.user_id == current_user.id)
        .all()
    )
    for room in existing_rooms:
        member_ids = {m.id for m in room.members}
        if member_ids == {current_user.id, bot.id}:
            return room

    room = models.Room(
        name=None, is_group=False, created_by=current_user.id,
        members=[current_user, bot],
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


# ---------- Rooms ----------

@app.get("/rooms", response_model=List[RoomOut])
def list_rooms(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return current_user.rooms


@app.post("/rooms", response_model=RoomOut)
def create_room(data: RoomCreateIn, db: Session = Depends(get_db),
                 current_user: models.User = Depends(get_current_user)):
    member_ids = set(data.member_ids) | {current_user.id}

    if not data.is_group and len(member_ids) == 2:
        other_id = (member_ids - {current_user.id}).pop()
        existing_rooms = (
            db.query(models.Room)
            .filter(models.Room.is_group == False)
            .join(models.room_members)
            .filter(models.room_members.c.user_id == current_user.id)
            .all()
        )
        for room in existing_rooms:
            room_member_ids = {m.id for m in room.members}
            if room_member_ids == member_ids:
                return room

    room_type = "direct"
    if data.is_group:
        room_type = data.room_type if data.room_type in ("group", "channel") else "group"

    members = db.query(models.User).filter(models.User.id.in_(member_ids)).all()
    room = models.Room(
        name=data.name if data.is_group else None,
        is_group=data.is_group,
        room_type=room_type,
        created_by=current_user.id,
        members=members,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


class AddMembersIn(BaseModel):
    member_ids: List[int]


@app.post("/rooms/{room_id}/members", response_model=RoomOut)
def add_room_members(room_id: int, data: AddMembersIn, db: Session = Depends(get_db),
                      current_user: models.User = Depends(get_current_user)):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room or current_user not in room.members:
        raise HTTPException(status_code=403, detail="دسترسی به این گفتگو مجاز نیست")
    if not room.is_group:
        raise HTTPException(status_code=400, detail="فقط گروه/کانال عضو جدید قبول می‌کند")
    if room.room_type == "channel" and room.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="فقط سازنده‌ی کانال می‌تواند عضو اضافه کند")

    new_members = db.query(models.User).filter(models.User.id.in_(data.member_ids)).all()
    for m in new_members:
        if m not in room.members:
            room.members.append(m)
    db.commit()
    db.refresh(room)
    return room


@app.get("/rooms/{room_id}/messages", response_model=List[MessageOut])
def get_messages(room_id: int, db: Session = Depends(get_db),
                  current_user: models.User = Depends(get_current_user)):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room or current_user not in room.members:
        raise HTTPException(status_code=403, detail="دسترسی به این گفتگو مجاز نیست")
    messages = (
        db.query(models.Message)
        .filter(models.Message.room_id == room_id)
        .order_by(models.Message.created_at.asc())
        .all()
    )
    return [
        MessageOut(
            id=m.id, room_id=m.room_id, sender_id=m.sender_id,
            sender_name=m.sender.display_name, content=m.content,
            message_type=m.message_type, file_url=m.file_url,
            file_name=m.file_name, file_size=m.file_size,
            created_at=m.created_at,
        )
        for m in messages
    ]


# ---------- Admin panel ----------

class AISettingsOut(BaseModel):
    model: str
    default_model: str
    stt_model: str
    tts_model: str
    tts_voice: str
    key_count: int
    masked_keys: List[str]


class AISettingsIn(BaseModel):
    model: Optional[str] = None
    api_keys: Optional[str] = None  # کلیدها با کاما جدا شده؛ اگر None باشد دست نمی‌خورد
    stt_model: Optional[str] = None
    tts_model: Optional[str] = None
    tts_voice: Optional[str] = None


def _mask_key(k: str) -> str:
    return k[:8] + "..." + k[-4:] if len(k) > 12 else "***"


def _ai_settings_snapshot() -> "AISettingsOut":
    keys = ai_bot.get_api_keys()
    return AISettingsOut(
        model=ai_bot.get_model(),
        default_model=ai_bot.DEFAULT_MODEL,
        stt_model=ai_bot.get_stt_model(),
        tts_model=ai_bot.get_tts_model(),
        tts_voice=ai_bot.get_tts_voice(),
        key_count=len(keys),
        masked_keys=[_mask_key(k) for k in keys],
    )


@app.get("/admin/ai-settings", response_model=AISettingsOut)
def admin_get_ai_settings(admin: models.User = Depends(get_current_admin)):
    return _ai_settings_snapshot()


def _save_setting(db: Session, key: str, value: str):
    setting = db.query(models.AppSetting).filter(models.AppSetting.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(models.AppSetting(key=key, value=value))


@app.post("/admin/ai-settings", response_model=AISettingsOut)
def admin_set_ai_settings(data: AISettingsIn, db: Session = Depends(get_db),
                           admin: models.User = Depends(get_current_admin)):
    if data.model is not None:
        new_model = data.model.strip()
        if not new_model:
            raise HTTPException(status_code=400, detail="اسم مدل نمی‌تواند خالی باشد")
        _save_setting(db, "ai_model", new_model)
        ai_bot.set_model(new_model)

    if data.api_keys is not None:
        keys_list = [k.strip() for k in data.api_keys.split(",") if k.strip()]
        if not keys_list:
            raise HTTPException(status_code=400, detail="حداقل یک کلید API لازم است")
        _save_setting(db, "ai_api_keys", ",".join(keys_list))
        ai_bot.set_api_keys(keys_list)

    if data.stt_model is not None and data.stt_model.strip():
        _save_setting(db, "ai_stt_model", data.stt_model.strip())
        ai_bot.set_stt_model(data.stt_model.strip())

    if data.tts_model is not None and data.tts_model.strip():
        _save_setting(db, "ai_tts_model", data.tts_model.strip())
        ai_bot.set_tts_model(data.tts_model.strip())

    if data.tts_voice is not None and data.tts_voice.strip():
        _save_setting(db, "ai_tts_voice", data.tts_voice.strip())
        ai_bot.set_tts_voice(data.tts_voice.strip())

    db.commit()

    return _ai_settings_snapshot()


# ---------- ظاهر/رنگ اپلیکیشن ----------

DEFAULT_ACCENT_COLOR = "#3FA9F5"


class ThemeOut(BaseModel):
    accent_color: str


class ThemeIn(BaseModel):
    accent_color: str


@app.get("/settings/theme", response_model=ThemeOut)
def get_theme(db: Session = Depends(get_db)):
    setting = db.query(models.AppSetting).filter(models.AppSetting.key == "accent_color").first()
    return ThemeOut(accent_color=(setting.value if setting and setting.value else DEFAULT_ACCENT_COLOR))


@app.post("/admin/theme", response_model=ThemeOut)
def set_theme(data: ThemeIn, db: Session = Depends(get_db),
              admin: models.User = Depends(get_current_admin)):
    color = data.accent_color.strip()
    if not color.startswith("#") or len(color) not in (4, 7):
        raise HTTPException(status_code=400, detail="فرمت رنگ باید مثل #3FA9F5 باشد")
    setting = db.query(models.AppSetting).filter(models.AppSetting.key == "accent_color").first()
    if setting:
        setting.value = color
    else:
        db.add(models.AppSetting(key="accent_color", value=color))
    db.commit()
    return ThemeOut(accent_color=color)


@app.get("/admin/stats", response_model=AdminStatsOut)
def admin_stats(db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    return AdminStatsOut(
        total_users=db.query(models.User).count(),
        online_users=db.query(models.User).filter(models.User.is_online == True).count(),
        total_rooms=db.query(models.Room).count(),
        total_messages=db.query(models.Message).count(),
        banned_users=db.query(models.User).filter(models.User.is_banned == True).count(),
    )


@app.get("/admin/users", response_model=List[UserOut])
def admin_list_users(q: Optional[str] = None, db: Session = Depends(get_db),
                      admin: models.User = Depends(get_current_admin)):
    query = db.query(models.User)
    if q:
        query = query.filter(
            or_(models.User.display_name.contains(q), models.User.username.contains(q))
        )
    return query.order_by(models.User.id.asc()).all()


@app.post("/admin/users/{user_id}/ban", response_model=UserOut)
def admin_ban_user(user_id: int, db: Session = Depends(get_db),
                    admin: models.User = Depends(get_current_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="نمی‌توانید خودتان را مسدود کنید")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")
    user.is_banned = True
    db.commit()
    db.refresh(user)
    return user


@app.post("/admin/users/{user_id}/unban", response_model=UserOut)
def admin_unban_user(user_id: int, db: Session = Depends(get_db),
                      admin: models.User = Depends(get_current_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")
    user.is_banned = False
    db.commit()
    db.refresh(user)
    return user


@app.post("/admin/users/{user_id}/make-admin", response_model=UserOut)
def admin_promote_user(user_id: int, db: Session = Depends(get_db),
                        admin: models.User = Depends(get_current_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")
    user.is_admin = True
    db.commit()
    db.refresh(user)
    return user


@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, db: Session = Depends(get_db),
                       admin: models.User = Depends(get_current_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="نمی‌توانید خودتان را حذف کنید")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")
    db.query(models.Message).filter(models.Message.sender_id == user_id).delete()
    db.delete(user)
    db.commit()
    return {"ok": True}


@app.get("/admin/rooms", response_model=List[AdminRoomOut])
def admin_list_rooms(db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    rooms = db.query(models.Room).order_by(models.Room.id.asc()).all()
    return [
        AdminRoomOut(
            id=r.id, name=r.name, is_group=r.is_group,
            member_count=len(r.members), message_count=len(r.messages),
            created_at=r.created_at,
        )
        for r in rooms
    ]


@app.delete("/admin/rooms/{room_id}")
def admin_delete_room(room_id: int, db: Session = Depends(get_db),
                       admin: models.User = Depends(get_current_admin)):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="گفتگو یافت نشد")
    db.delete(room)
    db.commit()
    return {"ok": True}


@app.delete("/admin/messages/{message_id}")
def admin_delete_message(message_id: int, db: Session = Depends(get_db),
                          admin: models.User = Depends(get_current_admin)):
    msg = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="پیام یافت نشد")
    db.delete(msg)
    db.commit()
    return {"ok": True}


# ---------- File upload ----------

def detect_message_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in ALLOWED_EXTENSIONS["image"]:
        return "image"
    if ext in ALLOWED_EXTENSIONS["voice"]:
        return "voice"
    return "file"


@app.post("/upload", response_model=UploadOut)
async def upload_file(
    room_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room or current_user not in room.members:
        raise HTTPException(status_code=403, detail="دسترسی به این گفتگو مجاز نیست")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="حجم فایل نباید بیشتر از ۲۵ مگابایت باشد")

    original_name = file.filename or "file"
    ext = os.path.splitext(original_name)[1]
    safe_name = f"{uuid.uuid4().hex}{ext}"
    room_dir = os.path.join(UPLOAD_DIR, str(room_id))
    os.makedirs(room_dir, exist_ok=True)
    disk_path = os.path.join(room_dir, safe_name)

    with open(disk_path, "wb") as f:
        f.write(contents)

    message_type = detect_message_type(original_name)
    file_url = f"/uploads/{room_id}/{safe_name}"

    return UploadOut(
        file_url=file_url,
        file_name=original_name,
        file_size=len(contents),
        message_type=message_type,
    )


# ---------- WebSocket real-time chat ----------

class ConnectionManager:
    def __init__(self):
        # room_id -> list of (user_id, websocket)
        self.active: Dict[int, List[tuple]] = {}

    async def connect(self, room_id: int, user_id: int, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(room_id, []).append((user_id, ws))

    def disconnect(self, room_id: int, ws: WebSocket):
        if room_id in self.active:
            self.active[room_id] = [(uid, w) for uid, w in self.active[room_id] if w != ws]

    async def broadcast(self, room_id: int, message: dict):
        for uid, ws in self.active.get(room_id, []):
            await ws.send_json(message)


manager = ConnectionManager()


@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: int, token: str = Query(...)):
    payload = auth.decode_access_token(token)
    if not payload:
        await websocket.close(code=4401)
        return

    db = next(get_db())
    user = db.query(models.User).filter(models.User.id == int(payload.get("sub"))).first()
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not user or not room or user not in room.members or user.is_banned:
        await websocket.close(code=4403)
        return

    user.is_online = True
    db.commit()

    await manager.connect(room_id, user.id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message_type = data.get("message_type", "text")
            content = (data.get("content") or "").strip()

            # محدودیت کانال: فقط سازنده‌ی کانال حق ارسال پیام دارد
            if room.room_type == "channel" and room.created_by != user.id:
                await websocket.send_json({
                    "type": "error",
                    "detail": "این یک کانال است — فقط سازنده‌ی کانال می‌تواند پیام ارسال کند.",
                })
                continue

            if message_type == "text":
                if not content:
                    continue
                msg = models.Message(
                    room_id=room_id, sender_id=user.id, content=content, message_type="text",
                )
            elif message_type in ("image", "file", "voice"):
                file_url = data.get("file_url")
                if not file_url:
                    continue
                msg = models.Message(
                    room_id=room_id, sender_id=user.id, content=content or None,
                    message_type=message_type, file_url=file_url,
                    file_name=data.get("file_name"), file_size=data.get("file_size"),
                )
            else:
                continue

            # اگر پیام صوتی است، قبل از ذخیره سعی کن متنش را (برای تاریخچه‌ی گفتگو با دستیار
            # هوشمند و نمایش زیرنویس) با تبدیل گفتار-به-متن به دست بیاوری
            transcribed_text = None
            if message_type == "voice" and msg.file_url:
                disk_path = os.path.join(UPLOAD_DIR, msg.file_url.replace("/uploads/", "", 1))
                if os.path.exists(disk_path):
                    transcribed_text = await ai_bot.transcribe_audio(disk_path)
                    if transcribed_text and not msg.content:
                        msg.content = transcribed_text

            db.add(msg)
            db.commit()
            db.refresh(msg)

            payload_out = {
                "type": "message",
                "id": msg.id,
                "room_id": room_id,
                "sender_id": user.id,
                "sender_name": user.display_name,
                "content": msg.content,
                "message_type": msg.message_type,
                "file_url": msg.file_url,
                "file_name": msg.file_name,
                "file_size": msg.file_size,
                "created_at": msg.created_at.isoformat(),
            }
            await manager.broadcast(room_id, payload_out)

            # اگر طرف گفتگو «دستیار هوشمند» باشد، پاسخ او را بگیر و بفرست
            room_member_ids = {m.id for m in room.members}
            is_bot_room = (not room.is_group) and (BOT_USER_ID in room_member_ids)
            should_reply = is_bot_room and message_type in ("text", "voice") and (content or transcribed_text)

            if should_reply:
                await manager.broadcast(room_id, {"type": "typing", "user_id": BOT_USER_ID})

                recent = (
                    db.query(models.Message)
                    .filter(models.Message.room_id == room_id)
                    .order_by(models.Message.created_at.desc())
                    .limit(20)
                    .all()
                )
                recent.reverse()
                history = [
                    {
                        "role": "assistant" if m.sender_id == BOT_USER_ID else "user",
                        "content": m.content or "",
                    }
                    for m in recent if m.content
                ]

                reply_text = await ai_bot.get_ai_reply(history)

                if message_type == "voice":
                    # پاسخ صوتی: متن پاسخ را به گفتار تبدیل کن و به‌صورت پیام صوتی بفرست
                    bot_room_dir = os.path.join(UPLOAD_DIR, str(room_id))
                    os.makedirs(bot_room_dir, exist_ok=True)
                    voice_filename = f"{uuid.uuid4().hex}.mp3"
                    voice_path = os.path.join(bot_room_dir, voice_filename)
                    ok = await ai_bot.synthesize_speech(reply_text, voice_path)

                    if ok:
                        bot_msg = models.Message(
                            room_id=room_id, sender_id=BOT_USER_ID, content=reply_text,
                            message_type="voice", file_url=f"/uploads/{room_id}/{voice_filename}",
                            file_name="voice-reply.mp3", file_size=os.path.getsize(voice_path),
                        )
                    else:
                        # اگر تبدیل متن به گفتار ممکن نشد، حداقل جواب متنی را بفرست
                        bot_msg = models.Message(
                            room_id=room_id, sender_id=BOT_USER_ID,
                            content=reply_text + "\n\n(تبدیل به صدا ممکن نشد — از پنل ادمین مدل TTS را چک کن)",
                            message_type="text",
                        )
                else:
                    bot_msg = models.Message(
                        room_id=room_id, sender_id=BOT_USER_ID, content=reply_text, message_type="text",
                    )

                db.add(bot_msg)
                db.commit()
                db.refresh(bot_msg)

                bot_payload = {
                    "type": "message",
                    "id": bot_msg.id,
                    "room_id": room_id,
                    "sender_id": BOT_USER_ID,
                    "sender_name": "دستیار هوشمند",
                    "content": bot_msg.content,
                    "message_type": bot_msg.message_type,
                    "file_url": bot_msg.file_url,
                    "file_name": bot_msg.file_name,
                    "file_size": bot_msg.file_size,
                    "created_at": bot_msg.created_at.isoformat(),
                }
                await manager.broadcast(room_id, bot_payload)
    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
        user.is_online = False
        user.last_seen = datetime.datetime.utcnow()
        db.commit()
