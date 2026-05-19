import base64
import io
import uuid
import os
from pathlib import Path
from typing import Optional, Dict, List, Any

import streamlit as st
from PIL import Image
from supabase import create_client

try:
    from apex_llm import ApexConfig, ApexNeuralEngine, ApexCoreEngine, ApexAgentEngine
except Exception:
    ApexConfig = ApexNeuralEngine = ApexCoreEngine = ApexAgentEngine = None

SUPABASE_URL = "https://srfmomqaizzxvaqahphy.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNyZm1vbXFhaXp6eHZhcWFocGh5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg1Nzg0NzgsImV4cCI6MjA5NDE1NDQ3OH0.h8zRvGxksgB6rPxpXIYhr3D_w3mYT9BYdrhBEpC7qa4"

_shared_supabase = None

def get_supabase():
    global _shared_supabase
    if _shared_supabase is None:
        _shared_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _shared_supabase

def load_logo_base64(path: Path):
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode("utf-8")

LOGO_PATH = Path("assets") / "logo.png"
LOGO_BASE64 = load_logo_base64(LOGO_PATH)

@st.cache_resource
def init_engines():
    if ApexConfig is None:
        return None, None, None, None
    try:
        cfg = ApexConfig()
        cfg.load_env_file()
        cfg.save()
        neural = ApexNeuralEngine(cfg)
        core = ApexCoreEngine(cfg)
        agent = ApexAgentEngine(neural, core)
        return cfg, neural, core, agent
    except Exception:
        return None, None, None, None

cfg, neural, core, agent = init_engines()

def fallback_process(prompt, conv_id):
    return {"content": f"(local) Echo: {prompt}", "type": "chat", "sources": [], "analysis": None}

def init_session_state():
    if "conversations" not in st.session_state:
        st.session_state.conversations = {"default": {"title": "Conversation 1", "messages": []}}
    if "current_conv" not in st.session_state:
        st.session_state.current_conv = "default"
    if "draft" not in st.session_state:
        st.session_state.draft = ""
    if "theme" not in st.session_state:
        st.session_state.theme = "dark"
    if "sidebar_open" not in st.session_state:
        st.session_state.sidebar_open = True
    if "voice_active" not in st.session_state:
        st.session_state.voice_active = None
    if "camera_active" not in st.session_state:
        st.session_state.camera_active = None
    if "camera_front" not in st.session_state:
        st.session_state.camera_front = True
    if "draft_counter" not in st.session_state:
        st.session_state.draft_counter = 0
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None
    if "auth_session" not in st.session_state:
        st.session_state.auth_session = None
    if "auth_email" not in st.session_state:
        st.session_state.auth_email = ""
    if "auth_password" not in st.session_state:
        st.session_state.auth_password = ""
    if "auth_mode" not in st.session_state:
        st.session_state.auth_mode = "signin"
    if "auth_loading" not in st.session_state:
        st.session_state.auth_loading = False

init_session_state()

def rerun():
    try:
        st.rerun()
    except Exception:
        pass

def toggle_theme():
    st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
    rerun()

def send_message(prompt):
    if not prompt.strip():
        return
    st.session_state.conversations[st.session_state.current_conv]["messages"].append(
        {"role": "user", "content": prompt.strip(), "label": "User"}
    )
    with st.spinner("Apex AI is composing a response..."):
        if agent is not None and hasattr(agent, "process"):
            messages = st.session_state.conversations[st.session_state.current_conv]["messages"]
            result = agent.process(prompt.strip(), st.session_state.current_conv, messages=messages)
        else:
            result = fallback_process(prompt.strip(), st.session_state.current_conv)
    st.session_state.conversations[st.session_state.current_conv]["messages"].append(
        {"role": "assistant", "content": result.get("content", ""), "label": result.get("type", "Assistant")}
    )

def theme_css():
    theme = st.session_state.theme
    if theme == "dark":
        return """
        <style>
        :root { --bg: #0b1020; --text: #e6eef8; --card-bg: #111827; --card-border: #374151; }
        body { background: #0b1020; color: #e6eef8; }
        .card { background: #111827; border: 1px solid #374151; border-radius: 12px; padding: 1rem; margin-bottom: 1rem; }
        .auth-card { max-width: 400px; margin: 80px auto; padding: 2rem; background: #111827; border: 1px solid #374151; border-radius: 16px; text-align: center; }
        .auth-card input { width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: 1px solid #374151; background: #1a1a2e; color: #e6eef8; }
        .auth-card button { width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: none; background: #6366f1; color: white; font-weight: 600; cursor: pointer; }
        .auth-card button:hover { background: #5558e6; }
        .auth-error { color: #ef4444; font-size: 0.875rem; margin: 8px 0; }
        .auth-toggle { color: #6366f1; cursor: pointer; font-size: 0.875rem; }
        .user-badge { font-size: 0.75rem; color: #9ca3af; margin-top: 8px; }
        </style>
        """
    else:
        return """
        <style>
        :root { --bg: #f9fafb; --text: #111827; --card-bg: #ffffff; --card-border: #d1d5db; }
        body { background: #f9fafb; color: #111827; }
        .card { background: #ffffff; border: 1px solid #d1d5db; border-radius: 12px; padding: 1rem; margin-bottom: 1rem; }
        .auth-card { max-width: 400px; margin: 80px auto; padding: 2rem; background: #ffffff; border: 1px solid #d1d5db; border-radius: 16px; text-align: center; }
        .auth-card input { width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: 1px solid #d1d5db; background: #f9fafb; color: #111827; }
        .auth-card button { width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: none; background: #6366f1; color: white; font-weight: 600; cursor: pointer; }
        .auth-card button:hover { background: #5558e6; }
        .auth-error { color: #ef4444; font-size: 0.875rem; margin: 8px 0; }
        .auth-toggle { color: #6366f1; cursor: pointer; font-size: 0.875rem; }
        .user-badge { font-size: 0.75rem; color: #6b7280; margin-top: 8px; }
        </style>
        """

def render_auth_page():
    st.markdown(theme_css(), unsafe_allow_html=True)
    mode = st.session_state.auth_mode
    title = "Sign In" if mode == "signin" else "Create Account"
    st.markdown(f"""
    <div class="auth-card">
        <h2>Apex AI</h2>
        <p style="color: #9ca3af; margin-bottom: 1.5rem;">{title}</p>
    </div>
    """, unsafe_allow_html=True)

    email = st.text_input("Email", key="auth_email_input", placeholder="you@example.com")
    password = st.text_input("Password", type="password", key="auth_password_input", placeholder="••••••••")

    if st.button(title, key="auth_submit", disabled=st.session_state.auth_loading):
        if not email or not password:
            st.error("Please fill in all fields")
        else:
            st.session_state.auth_loading = True
            try:
                sb = get_supabase()
                if mode == "signin":
                    resp = sb.auth.sign_in_with_password({"email": email, "password": password})
                else:
                    resp = sb.auth.sign_up({"email": email, "password": password})
                if resp and resp.user:
                    st.session_state.auth_user = resp.user
                    st.session_state.auth_session = resp.session
                    rerun()
                else:
                    st.error("Authentication failed")
            except Exception as e:
                st.error(str(e))
            finally:
                st.session_state.auth_loading = False

    if st.button("Send Magic Link", key="auth_magic"):
        if email:
            try:
                sb = get_supabase()
                sb.auth.sign_in_with_otp({"email": email})
                st.success("Magic link sent! Check your email.")
            except Exception as e:
                st.error(str(e))
        else:
            st.error("Please enter your email first")

    toggle_label = "Don't have an account? Sign Up" if mode == "signin" else "Already have an account? Sign In"
    if st.button(toggle_label, key="auth_toggle"):
        st.session_state.auth_mode = "signup" if mode == "signin" else "signin"
        rerun()


# -------------------- UI START --------------------
st.set_page_config(page_title="Apex AI", layout="wide")

if st.session_state.auth_user is None:
    render_auth_page()
    st.stop()

# ====== Main Chat UI ======
st.markdown(theme_css(), unsafe_allow_html=True)

with st.sidebar:
    st.markdown(f"<h2 style='color:#6366f1'>Apex AI</h2>", unsafe_allow_html=True)
    user_email = getattr(st.session_state.auth_user, 'email', 'User')
    st.markdown(f"<p class='user-badge'>Signed in as {user_email}</p>", unsafe_allow_html=True)

    if st.button("Sign Out", key="signout_btn"):
        st.session_state.auth_user = None
        st.session_state.auth_session = None
        rerun()

    if st.session_state.sidebar_open:
        st.markdown("---")
        for conv_id, conv in st.session_state.conversations.items():
            active = conv_id == st.session_state.current_conv
            style = "font-weight: bold; color: #6366f1;" if active else ""
            if st.button(f"{'* ' if active else '  '}{conv['title']}", key=f"conv_{conv_id}"):
                st.session_state.current_conv = conv_id
                st.session_state.draft = ""
                rerun()
        st.markdown("---")
        st.markdown("<small>Quick prompts</small>", unsafe_allow_html=True)
        for p in ["Summarize the latest AI research", "Write a Python sorting function", "Give 3 healthcare startup ideas"]:
            if st.button(p, key=f"quick_{p[:12]}"):
                send_message(p)
                rerun()

col1, col2 = st.columns([1, 3], gap="small")

with col1:
    if LOGO_BASE64:
        st.markdown(f"<img src='data:image/png;base64,{LOGO_BASE64}' class='logo-img'/>", unsafe_allow_html=True)
    st.title("Apex AI")
    if st.button("New conversation", use_container_width=True):
        conv_id = str(uuid.uuid4())[:8]
        st.session_state.conversations[conv_id] = {"title": f"Conversation {len(st.session_state.conversations)+1}", "messages": []}
        st.session_state.current_conv = conv_id
        st.session_state.draft = ""
        rerun()
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.conversations[st.session_state.current_conv]["messages"] = []
        st.session_state.draft = ""
        rerun()

with col2:
    conv = st.session_state.conversations[st.session_state.current_conv]
    st.markdown(f"## {conv['title']}")
    messages = conv.get("messages", [])

    for i, msg in enumerate(messages):
        role = msg.get("role", "assistant")
        label = msg.get("label", "Assistant") if role != "user" else "You"
        content = msg.get("content", "")
        if role == "user":
            st.markdown(f"<div class='card'><strong>{label}</strong><br>{content}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='card' style='border-left:4px solid #6366f1;'><strong>{label}</strong><br>{content}</div>", unsafe_allow_html=True)

        cols = st.columns([0.12, 0.12, 0.12, 1])
        with cols[0]:
            if st.button("Voice", key=f"voice_{i}"):
                st.session_state.camera_active = None
                rerun()
        with cols[1]:
            if st.button("Analyze", key=f"analyze_{i}"):
                cam_key = "analyze_cam_" + str(i)
                captured = st.camera_input("Capture image", key=cam_key)
                if captured:
                    try:
                        img = Image.open(captured)
                        if agent is not None and hasattr(agent, "process_with_image"):
                            result = agent.process_with_image("Describe this image in detail.", img, st.session_state.current_conv)
                        elif core is not None and hasattr(core, "vision"):
                            result = {"content": core.vision.describe_image(img), "sources": []}
                        else:
                            result = {"content": "[image analysis unavailable]", "sources": []}
                        st.session_state.conversations[st.session_state.current_conv]["messages"].append({
                            "role": "assistant", "content": result.get("content", ""), "label": "Vision",
                        })
                    except Exception as e:
                        st.error(f"Image processing error: {e}")
                    rerun()
        with cols[2]:
            if st.button("Cam", key=f"cam_{i}") or st.session_state.camera_active == i:
                cam_key = "camera_input_" + str(i)
                captured = st.camera_input("Capture image", key=cam_key, disabled=st.session_state.camera_active != i)
                if captured:
                    st.session_state.camera_active = i
                    st.session_state.camera_front = True
                    try:
                        img = Image.open(captured)
                        if agent is not None and hasattr(agent, "process_with_image"):
                            result = agent.process_with_image("Describe this image in detail.", img, st.session_state.current_conv)
                        elif core is not None and hasattr(core, "vision"):
                            result = {"content": core.vision.describe_image(img), "sources": []}
                        else:
                            result = {"content": "[image analysis unavailable]", "sources": []}
                        st.session_state.conversations[st.session_state.current_conv]["messages"].append({
                            "role": "assistant", "content": result.get("content", ""), "label": "Vision",
                        })
                    except Exception as e:
                        st.error(f"Image processing error: {e}")
                    rerun()
                colA, colB = st.columns(2)
                with colA:
                    if st.button("Front", key=f"rot_{i}_front"):
                        st.session_state.camera_front = True
                        rerun()
                with colB:
                    if st.button("Back", key=f"rot_{i}_back"):
                        st.session_state.camera_front = False
                        rerun()

        if st.session_state.voice_active == i:
            st.info("Recording... (click 'Send' to simulate.)")
            st.session_state.draft = st.text_area("Your voice draft", key=f"voice_draft_{i}", placeholder="Speak and we will transcribe...", height=3)
            if st.button("Stop Recording", key=f"stop_voice_{i}"):
                st.session_state.draft = "[Transcribed text will appear here]"
                st.session_state.voice_active = None
                rerun()

    st.markdown("---")
    draft = st.text_area("Message", key=f"draft_input_{st.session_state.draft_counter}", placeholder="Type your message here...", height=120)
    if st.button("Send", use_container_width=True):
        prompt = draft.strip()
        if prompt:
            st.session_state.conversations[st.session_state.current_conv]["messages"].append(
                {"role": "user", "content": prompt, "label": "User"}
            )
            st.session_state.draft_counter += 1
            with st.spinner("Apex AI is composing a response..."):
                if agent is not None and hasattr(agent, "process"):
                    messages = st.session_state.conversations[st.session_state.current_conv]["messages"]
                    result = agent.process(prompt, st.session_state.current_conv, messages=messages)
                else:
                    result = fallback_process(prompt, st.session_state.current_conv)
            st.session_state.conversations[st.session_state.current_conv]["messages"].append(
                {"role": "assistant", "content": result.get("content", ""), "label": result.get("type", "Assistant")}
            )
            rerun()
