# Apex AI Backend - Cloud Deployment Guide

## Deploy to Render (Recommended - Free Tier Available)

### Step 1: Push to GitHub
```bash
cd "C:\Users\Hritesh\Hritesh-apps\Apex Ai"
git init
git add .
git commit -m "Initial commit"
# Create a repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/apex-ai.git
git push -u origin main
```

### Step 2: Deploy on Render
1. Go to https://render.com and sign up
2. Click **New +** → **Web Service**
3. Connect your GitHub repo
4. Configure:
   - **Name:** apex-ai
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements-cloud.txt`
   - **Start Command:** `cd backend_api && uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** Free

### Step 3: Set Environment Variables (in Render dashboard)
| Variable | Value |
|----------|-------|
| `APEX_LLM_PROVIDER` | `openai` (or `groq` for free tier) |
| `APEX_LLM_API_KEY` | Your OpenAI/Groq API key |
| `APEX_LLM_MODEL` | `gpt-4o-mini` (or `llama-3.1-8b-instant` for Groq) |
| `SUPABASE_URL` | `https://srfmomqaizzxvaqahphy.supabase.co` |
| `SUPABASE_ANON_KEY` | Your Supabase anon key |
| `APEX_SEARCH` | `duckduckgo` |
| `APEX_ENABLE_WEB` | `true` |
| `APEX_ENABLE_VISION` | `true` |

### Step 4: Get Your Backend URL
After deployment, Render gives you a URL like:
`https://apex-ai-xxxx.onrender.com`

### Step 5: Update Mobile App
Update the default backend URL in the mobile app settings to your Render URL.

---

## Deploy to Railway (Alternative - $5/month credit free)

### Step 1: Connect GitHub to Railway
1. Go to https://railway.app
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your repo

### Step 2: Configure
Railway auto-detects Python. Set these variables in Railway dashboard:
- Same environment variables as Render above

### Step 3: Deploy
Railway will build and deploy automatically. You'll get a URL like:
`https://apex-ai-production-xxxx.up.railway.app`

---

## Deploy to Fly.io (Alternative - Free tier available)

### Step 1: Install flyctl
```bash
# Windows (with scoop)
scoop install flyctl

# Or download from https://fly.io/docs/hands-on/install-flyctl/
```

### Step 2: Login and Launch
```bash
fly auth login
fly launch --name apex-ai
```

### Step 3: Set Secrets
```bash
fly secrets set APEX_LLM_PROVIDER=openai
fly secrets set APEX_LLM_API_KEY=sk-your-key
fly secrets set SUPABASE_URL=https://srfmomqaizzxvaqahphy.supabase.co
fly secrets set SUPABASE_ANON_KEY=your-key
```

### Step 4: Deploy
```bash
fly deploy
```

---

## Free Tier Comparison

| Platform | Free Tier | Always On? | Notes |
|----------|-----------|------------|-------|
| **Render** | 750 hrs/month | Sleeps after 15min idle | First request takes 30s to wake |
| **Railway** | $5 credit/month | Yes | Best for always-on |
| **Fly.io** | 3 shared VMs free | Yes | Most complex setup |
| **PythonAnywhere** | Free | Yes | Limited to web apps |

**Recommendation:** Use **Railway** for always-on, or **Render** for free tier with sleep.

---

## Test Your Deployed Backend

Once deployed, test with:
```bash
curl https://your-backend-url.onrender.com/health
curl https://your-backend-url.onrender.com/api/config
```

You should see:
```json
{"status": "ok", "timestamp": "..."}
```

---

## Update Mobile App Backend URL

After deployment, update the mobile app to use your cloud URL:

1. Open the Apex AI app
2. Go to **Settings** (gear icon in header)
3. Under **Backend Server**, enter your cloud URL
4. Click **Save & Test**
5. Rebuild the APK with the new default URL

Or update the default URL in `frontend-web/src/pages/ChatPage.tsx`:
```typescript
const [backendUrlInput, setBackendUrlInput] = useState(getBackendURL() || 'https://your-backend-url.onrender.com')
```
