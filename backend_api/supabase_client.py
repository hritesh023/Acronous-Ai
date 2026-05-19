import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

_url = os.getenv("SUPABASE_URL")
_key = os.getenv("SUPABASE_ANON_KEY")

_supabase: Client | None = None

def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(_url, _key)
    return _supabase

def verify_token(token: str) -> dict | None:
    try:
        resp = get_supabase().auth.get_user(token)
        return resp.user.model_dump() if resp.user else None
    except Exception:
        return None

async def get_current_user_id(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ")
    user = verify_token(token)
    return user.get("id") if user else None
