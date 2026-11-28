"""Sinh tài khoản / mật khẩu tạm và mã hoá mật khẩu tạm.

Vì sao mã hoá chứ không băm (hash)? PM cần XEM LẠI mật khẩu tạm trong bảng thành viên,
nên phải giải mã được. Mật khẩu đăng nhập thật vẫn được Django băm như bình thường;
bản mã hoá chỉ là bản sao để hiển thị và bị xoá khi người dùng tự đổi mật khẩu.

Khoá mã hoá suy ra từ DJANGO_SECRET_KEY → đổi SECRET_KEY thì mật khẩu tạm cũ không đọc lại
được nữa (PM bấm "Cấp lại mật khẩu").
"""

import base64
import hashlib
import re
import secrets
import string
import unicodedata

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

# Bỏ các ký tự dễ nhầm khi đọc / gõ lại: 0 O o 1 l I
_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0Oo1lI")


def _coerce_fernet(raw_key: str) -> Fernet:
    key_bytes = raw_key.strip().encode()
    try:
        return Fernet(key_bytes)
    except (ValueError, TypeError):
        digest = hashlib.sha256(f"vanohub:credential-key:{raw_key.strip()}".encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def _secret_key_fernet() -> Fernet:
    digest = hashlib.sha256(f"vanohub:initial-password:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _fernet() -> Fernet | MultiFernet:
    configured = [str(k).strip() for k in getattr(settings, "CREDENTIAL_ENCRYPTION_KEYS", ()) if str(k).strip()]
    if not configured:
        return _secret_key_fernet()
    fernets = [_coerce_fernet(k) for k in configured]
    if getattr(settings, "CREDENTIAL_LEGACY_SECRET_KEY_FALLBACK", True):
        fernets.append(_secret_key_fernet())
    return MultiFernet(fernets)


def encrypt(password):
    return _fernet().encrypt(password.encode()).decode()


def decrypt(token):
    """None nếu không giải mã được (vd. đã đổi khoá hoặc SECRET_KEY)."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return None


def generate_password(length=10):
    """Mật khẩu ngẫu nhiên có cả chữ hoa, chữ thường và số."""
    while True:
        password = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if (any(c.islower() for c in password) and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)):
            return password


def set_initial_password(user, password=None):
    """Đặt mật khẩu tạm (chưa save). Trả về mật khẩu dạng rõ để báo cho PM."""
    password = password or generate_password()
    user.set_password(password)
    user.initial_password_encrypted = encrypt(password)
    return password


def slugify_name(full_name):
    """'Nguyễn Văn Đức' → 'nguyenvanduc'."""
    text = full_name.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def unique_username(full_name, user_model):
    base = slugify_name(full_name)[:30] or "user"
    candidate, n = base, 1
    while user_model.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f"{base}{n}"
    return candidate
