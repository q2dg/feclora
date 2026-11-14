"""Loopback-only multilingual first-boot administrator password setup."""
from __future__ import annotations

import grp
import html
import http.cookies
import os
import pwd
import secrets
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

HOST = "127.0.0.1"
PORT = 8765
COMPLETE = Path("/var/lib/feclora/kiosk-setup-complete")
ADMIN = "feclora"
ORIGIN = f"http://{HOST}:{PORT}"
COCKPIT_APP = "https://localhost:9090/cockpit/@localhost/feclora/index.html"

LANGUAGES = (
    ("en", "English"), ("es", "Español"), ("ca", "Català"), ("gl", "Galego"),
    ("eu", "Euskara"), ("pt", "Português"), ("fr", "Français"), ("de", "Deutsch"),
    ("it", "Italiano"), ("zh", "中文"), ("ja", "日本語"), ("ru", "Русский"),
    ("ar", "العربية"), ("tr", "Türkçe"),
)
SUPPORTED_LANGUAGES = {code for code, _label in LANGUAGES}

# Keep this first-boot surface self-contained: it runs before the Cockpit
# application and must not load remote scripts, stylesheets or translation files.
FIRST_BOOT_TEXT = {
    "en": ("Welcome to Feclora", "Create the local administrator password to continue to Cockpit. Use at least 14 characters.", "This password is not stored in the browser by Feclora.", "Administrator password", "Confirm password", "Set password and open Cockpit", "Interface language", "Use a password between 14 and 128 characters.", "The passwords do not match.", "The password contains unsupported characters."),
    "es": ("Bienvenido a Feclora", "Crea la contraseña del administrador local para continuar a Cockpit. Utiliza al menos 14 caracteres.", "Feclora no almacena esta contraseña en el navegador.", "Contraseña del administrador", "Confirmar contraseña", "Establecer contraseña y abrir Cockpit", "Idioma de la interfaz", "Utiliza una contraseña de entre 14 y 128 caracteres.", "Las contraseñas no coinciden.", "La contraseña contiene caracteres no admitidos."),
    "ca": ("Us donem la benvinguda a Feclora", "Crea la contrasenya de l'administrador local per continuar a Cockpit. Fes servir almenys 14 caràcters.", "Feclora no desa aquesta contrasenya al navegador.", "Contrasenya de l'administrador", "Confirma la contrasenya", "Estableix la contrasenya i obre Cockpit", "Idioma de la interfície", "Fes servir una contrasenya d'entre 14 i 128 caràcters.", "Les contrasenyes no coincideixen.", "La contrasenya conté caràcters no admesos."),
    "gl": ("Benvido a Feclora", "Crea o contrasinal do administrador local para continuar a Cockpit. Usa polo menos 14 caracteres.", "Feclora non almacena este contrasinal no navegador.", "Contrasinal do administrador", "Confirmar contrasinal", "Establecer o contrasinal e abrir Cockpit", "Idioma da interface", "Usa un contrasinal de entre 14 e 128 caracteres.", "Os contrasinais non coinciden.", "O contrasinal contén caracteres non admitidos."),
    "eu": ("Ongi etorri Feclora-ra", "Sortu administratzaile lokalaren pasahitza Cockpit-era jarraitzeko. Erabili gutxienez 14 karaktere.", "Feclora-k ez du pasahitz hau nabigatzailean gordetzen.", "Administratzailearen pasahitza", "Berretsi pasahitza", "Ezarri pasahitza eta ireki Cockpit", "Interfazearen hizkuntza", "Erabili 14 eta 128 karaktere arteko pasahitza.", "Pasahitzak ez datoz bat.", "Pasahitzak onartzen ez diren karaktereak ditu."),
    "pt": ("Bem-vindo ao Feclora", "Crie a palavra-passe do administrador local para continuar para o Cockpit. Utilize pelo menos 14 caracteres.", "O Feclora não guarda esta palavra-passe no navegador.", "Palavra-passe do administrador", "Confirmar palavra-passe", "Definir palavra-passe e abrir o Cockpit", "Idioma da interface", "Utilize uma palavra-passe entre 14 e 128 caracteres.", "As palavras-passe não coincidem.", "A palavra-passe contém caracteres não suportados."),
    "fr": ("Bienvenue dans Feclora", "Créez le mot de passe de l’administrateur local pour accéder à Cockpit. Utilisez au moins 14 caractères.", "Feclora ne stocke pas ce mot de passe dans le navigateur.", "Mot de passe administrateur", "Confirmer le mot de passe", "Définir le mot de passe et ouvrir Cockpit", "Langue de l’interface", "Utilisez un mot de passe de 14 à 128 caractères.", "Les mots de passe ne correspondent pas.", "Le mot de passe contient des caractères non pris en charge."),
    "de": ("Willkommen bei Feclora", "Erstellen Sie das lokale Administratorpasswort, um mit Cockpit fortzufahren. Verwenden Sie mindestens 14 Zeichen.", "Feclora speichert dieses Passwort nicht im Browser.", "Administratorpasswort", "Passwort bestätigen", "Passwort festlegen und Cockpit öffnen", "Oberflächensprache", "Verwenden Sie ein Passwort mit 14 bis 128 Zeichen.", "Die Passwörter stimmen nicht überein.", "Das Passwort enthält nicht unterstützte Zeichen."),
    "it": ("Benvenuto in Feclora", "Crea la password dell’amministratore locale per continuare in Cockpit. Usa almeno 14 caratteri.", "Feclora non memorizza questa password nel browser.", "Password amministratore", "Conferma password", "Imposta la password e apri Cockpit", "Lingua dell’interfaccia", "Usa una password da 14 a 128 caratteri.", "Le password non corrispondono.", "La password contiene caratteri non supportati."),
    "zh": ("欢迎使用 Feclora", "创建本地管理员密码以继续进入 Cockpit。密码至少需要 14 个字符。", "Feclora 不会在浏览器中存储此密码。", "管理员密码", "确认密码", "设置密码并打开 Cockpit", "界面语言", "密码长度必须为 14 至 128 个字符。", "两次输入的密码不一致。", "密码包含不支持的字符。"),
    "ja": ("Feclora へようこそ", "Cockpit に進むにはローカル管理者パスワードを作成してください。14 文字以上を使用してください。", "Feclora はこのパスワードをブラウザーに保存しません。", "管理者パスワード", "パスワードの確認", "パスワードを設定して Cockpit を開く", "インターフェース言語", "14～128 文字のパスワードを使用してください。", "パスワードが一致しません。", "パスワードに使用できない文字が含まれています。"),
    "ru": ("Добро пожаловать в Feclora", "Создайте пароль локального администратора, чтобы перейти в Cockpit. Используйте не менее 14 символов.", "Feclora не сохраняет этот пароль в браузере.", "Пароль администратора", "Подтвердите пароль", "Задать пароль и открыть Cockpit", "Язык интерфейса", "Используйте пароль длиной от 14 до 128 символов.", "Пароли не совпадают.", "Пароль содержит недопустимые символы."),
    "ar": ("مرحباً بك في Feclora", "أنشئ كلمة مرور المسؤول المحلي للمتابعة إلى Cockpit. استخدم 14 حرفاً على الأقل.", "لا يخزّن Feclora كلمة المرور هذه في المتصفح.", "كلمة مرور المسؤول", "تأكيد كلمة المرور", "تعيين كلمة المرور وفتح Cockpit", "لغة الواجهة", "استخدم كلمة مرور من 14 إلى 128 حرفاً.", "كلمتا المرور غير متطابقتين.", "تحتوي كلمة المرور على أحرف غير مدعومة."),
    "tr": ("Feclora'ya hoş geldiniz", "Cockpit'e devam etmek için yerel yönetici parolasını oluşturun. En az 14 karakter kullanın.", "Feclora bu parolayı tarayıcıda saklamaz.", "Yönetici parolası", "Parolayı onayla", "Parolayı ayarla ve Cockpit'i aç", "Arayüz dili", "14 ile 128 karakter arasında bir parola kullanın.", "Parolalar eşleşmiyor.", "Parola desteklenmeyen karakterler içeriyor."),
}


class BootstrapError(RuntimeError):
    """Safe first-boot setup failure."""


def normalize_language(value: str | None) -> str:
    if not isinstance(value, str):
        return "en"
    candidate = value.strip().replace("_", "-").split("-", 1)[0].lower()
    return candidate if candidate in SUPPORTED_LANGUAGES else "en"


def preferred_language(accept_language: str | None) -> str:
    for item in (accept_language or "").split(","):
        candidate = item.split(";", 1)[0].strip()
        normalized = normalize_language(candidate)
        if normalized != "en" or candidate.lower().startswith("en"):
            return normalized
    return "en"


def validate_password(password: str, confirmation: str) -> None:
    if not isinstance(password, str) or not isinstance(confirmation, str):
        raise BootstrapError("Enter the password twice.")
    if password != confirmation:
        raise BootstrapError("The passwords do not match.")
    if not 14 <= len(password) <= 128:
        raise BootstrapError("Use a password between 14 and 128 characters.")
    if password.strip() != password or any(ch in password for ch in ("\n", "\r", "\x00", ":")):
        raise BootstrapError("The password contains unsupported characters.")


def set_admin_password(password: str, *, runner=subprocess.run) -> None:
    if os.geteuid() != 0:
        raise BootstrapError("First-boot setup must run with system privileges.")
    try:
        account = pwd.getpwnam(ADMIN)
        wheel = grp.getgrnam("wheel")
    except KeyError as exc:
        raise BootstrapError("The administrator account is not provisioned.") from exc
    if account.pw_uid == 0 or account.pw_gid != wheel.gr_gid and ADMIN not in wheel.gr_mem:
        raise BootstrapError("The administrator account does not have the expected role.")
    try:
        result = runner(
            ["/usr/sbin/chpasswd"], input=f"{ADMIN}:{password}\n",
            text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BootstrapError("Could not set the administrator password.") from exc
    if result.returncode != 0:
        raise BootstrapError("Could not set the administrator password.")


def mark_complete(path: Path = COMPLETE) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = path.parent.lstat()
    if not path.parent.is_dir() or path.parent.is_symlink() or parent.st_uid != 0:
        raise BootstrapError("First-boot state directory is not trusted.")
    if path.exists() or path.is_symlink():
        raise BootstrapError("First-boot setup has already been completed.")
    fd, temporary = tempfile.mkstemp(prefix=".kiosk-setup-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write("complete\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def render_setup_page(token: str, language: str = "en") -> bytes:
    language = normalize_language(language)
    welcome, intro, privacy, password_label, confirm_label, submit, language_label, _length, _mismatch, _unsupported = FIRST_BOOT_TEXT[language]
    options = "".join(
        f'<option value="{code}"{" selected" if code == language else ""}>{html.escape(label)}</option>'
        for code, label in LANGUAGES
    )
    direction = "rtl" if language == "ar" else "ltr"
    safe_token = html.escape(token, quote=True)
    page = f"""<!doctype html><html lang="{language}" dir="{direction}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>{html.escape(welcome)}</title><style>body{{font:16px system-ui,sans-serif;max-width:38rem;margin:8vh auto;padding:0 1.2rem;color:#20242a}}label{{display:block;margin:1.2rem 0 .4rem}}input,select{{box-sizing:border-box;width:100%;padding:.8rem;font:inherit}}button{{margin-top:1.4rem;padding:.8rem 1.2rem;font:inherit}}p{{line-height:1.5}}form{{margin-top:1rem}}</style></head><body><h1>{html.escape(welcome)}</h1><p>{html.escape(intro)}</p><p>{html.escape(privacy)}</p><form method="get" action="/"><label for="language">{html.escape(language_label)}</label><select id="language" name="lang">{options}</select><button type="submit">Apply</button></form><form method="post" action="/setup"><input type="hidden" name="token" value="{safe_token}"><input type="hidden" name="language" value="{language}"><label for="password">{html.escape(password_label)}</label><input id="password" name="password" type="password" minlength="14" maxlength="128" autocomplete="new-password" required><label for="confirmation">{html.escape(confirm_label)}</label><input id="confirmation" name="confirmation" type="password" minlength="14" maxlength="128" autocomplete="new-password" required><button type="submit">{html.escape(submit)}</button></form></body></html>"""
    return page.encode("utf-8")


def build_handler(complete_path: Path = COMPLETE, password_runner=subprocess.run):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FecloraBootstrap/1"

        def _headers(self, status: int, *, content_type: str = "text/html; charset=utf-8", cookie: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()

        def _valid_local_request(self, *, require_origin: bool) -> bool:
            if self.headers.get("Host") != f"{HOST}:{PORT}":
                return False
            if require_origin and self.headers.get("Origin") != ORIGIN:
                return False
            return True

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path != "/" or not self._valid_local_request(require_origin=False):
                self._headers(403)
                self.wfile.write(b"Forbidden")
                return
            if complete_path.exists():
                self.send_response(303)
                self.send_header("Location", COCKPIT_APP)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            fields = parse_qs(parsed.query, keep_blank_values=True)
            requested = fields.get("lang", [""])[0]
            language = normalize_language(requested) if requested else preferred_language(self.headers.get("Accept-Language"))
            token = secrets.token_urlsafe(32)
            self._headers(200, cookie=f"feclora_setup={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=300")
            self.wfile.write(render_setup_page(token, language))

        def do_POST(self) -> None:
            if complete_path.exists():
                self._headers(409)
                self.wfile.write(b"First-boot setup is already complete")
                return
            if not self._valid_local_request(require_origin=True) or urlsplit(self.path).path != "/setup":
                self._headers(403)
                self.wfile.write(b"Forbidden")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 1 <= length <= 4096:
                self._headers(400)
                self.wfile.write(b"Invalid request")
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
                self._headers(415)
                self.wfile.write(b"Unsupported content type")
                return
            cookie = http.cookies.SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                token_cookie = cookie["feclora_setup"].value
            except (KeyError, http.cookies.CookieError):
                token_cookie = ""
            try:
                fields = parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True, max_num_fields=5)
            except ValueError:
                self._headers(400)
                self.wfile.write(b"Invalid form")
                return
            if set(fields) != {"token", "password", "confirmation", "language"} or any(len(values) != 1 for values in fields.values()):
                self._headers(400)
                self.wfile.write(b"Invalid form")
                return
            token = fields.get("token", [""])[0]
            password = fields.get("password", [""])[0]
            confirmation = fields.get("confirmation", [""])[0]
            language_value = fields.get("language", [""])[0]
            if language_value not in SUPPORTED_LANGUAGES:
                self._headers(400)
                self.wfile.write(b"Invalid language")
                return
            language = language_value
            if not token_cookie or not secrets.compare_digest(token_cookie, token):
                self._headers(403)
                self.wfile.write(b"Setup session expired. Reload this page.")
                return
            try:
                validate_password(password, confirmation)
                set_admin_password(password, runner=password_runner)
                mark_complete(complete_path)
            except BootstrapError as exc:
                message = str(exc)
                translations = {
                    "The passwords do not match.": FIRST_BOOT_TEXT[language][8],
                    "Use a password between 14 and 128 characters.": FIRST_BOOT_TEXT[language][7],
                    "The password contains unsupported characters.": FIRST_BOOT_TEXT[language][9],
                }
                self._headers(400)
                self.wfile.write(html.escape(translations.get(message, message)).encode("utf-8"))
                return
            except OSError:
                self._headers(500)
                self.wfile.write(b"Could not finalize first-boot setup.")
                return
            self.send_response(303)
            self.send_header("Location", COCKPIT_APP + "?" + urlencode({"feclora_language": language}))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie", "feclora_setup=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
            self.end_headers()

        def log_message(self, fmt: str, *args) -> None:
            # Never log request bodies or credentials.
            return

    return Handler


def serve(*, complete_path: Path = COMPLETE, password_runner=subprocess.run) -> int:
    server = HTTPServer((HOST, PORT), build_handler(complete_path, password_runner))
    server.timeout = 1
    try:
        while True:
            server.handle_request()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
