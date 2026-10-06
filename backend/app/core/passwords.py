from fastapi import HTTPException, status
from app.core.config import settings

# Small deny-list of the most common choices; length is the main control
_COMMON = {
    "password", "passw0rd", "123456789012", "qwertyuiop", "administrator", "letmein", "welcome",
    "changeme", "tukang", "cockpit", "cockpit-py", "iloveyou", "admin",
}

def enforce_password_policy(password: str, username: str = ""):
    problems = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"at least {settings.PASSWORD_MIN_LENGTH} characters")
    lowered = password.lower()
    if username and username.lower() in lowered:
        problems.append("must not contain the username")
    if lowered in _COMMON or lowered.rstrip("0123456789!") in _COMMON:
        problems.append("too common")
    if len(set(password)) < 5:
        problems.append("too repetitive")
    if problems:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Password policy: " + "; ".join(problems)
        )
