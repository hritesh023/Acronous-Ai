# Apex AI - Modern Cross-Platform Frontend

A professional, modern frontend for Apex AI that works seamlessly on web, iOS, and Android. This is a complete redesign from the original Streamlit UI with professional UI/UX, responsive design, and native mobile apps.

## 🎯 Architecture Overview

The project is organized into three main parts:

```
Apex AI/
├── backend_api/          # FastAPI REST API server
├── frontend-web/         # React web app (Vite)
├── frontend-mobile/      # React Native mobile app (Expo)
└── apex_llm/            # Original Python backend (unchanged)
```

## 🚀 Quick Start

### Prerequisites

- **Node.js** 18+ (for web and mobile frontends)
- **Python** 3.8+ (for backend)
- **npm** or **yarn** package manager
- **Ollama** (optional, for local LLM)

### 1. Setup Backend API

```bash
cd backend_api

# Install Python dependencies
pip install -r requirements.txt

# Add backend API deps to main requirements
cat requirements.txt >> ../requirements.txt

# Start the FastAPI server
python -m uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000` with interactive docs at `/docs`

### 2. Setup & Run React Web Frontend

```bash
cd frontend-web

# Install dependencies
npm install

# Start development server
npm run dev
```

Visit `http://localhost:5173` in your browser

### 3. Setup & Run React Native Mobile

```bash
cd frontend-mobile

# Install dependencies
npm install

# Start Expo
npm start

# For iOS (macOS only)
npm run ios

# For Android
npm run android

# For web version
npm run web
```

## 📱 Features

### Web App
- ✅ Modern, professional UI design
- ✅ Real-time chat streaming
- ✅ Image generation & analysis
- ✅ Voice input (audio transcription)
- ✅ Conversation management
- ✅ Light/Dark theme toggle
- ✅ Responsive design (works on tablets too)
- ✅ Accessibility features (ARIA labels, keyboard navigation)

### Mobile App
- ✅ Native feel with bottom tab navigation
- ✅ All web features adapted for mobile
- ✅ iOS and Android support via Expo
- ✅ Persistent storage (AsyncStorage)
- ✅ Safe area handling for notches
- ✅ Touch-optimized UI

## 🏗️ Tech Stack

### Backend
- **FastAPI** - Modern, fast Python web framework
- **Uvicorn** - ASGI server
- **Pydantic** - Data validation
- Same Python backend (apex_llm) from original app

### Frontend (Web)
- **React 18** - UI library
- **TypeScript** - Type safety
- **Vite** - Fast build tool
- **Axios** - HTTP client
- **CSS3** - Modern styling with CSS variables

### Frontend (Mobile)
- **React Native** - Cross-platform mobile framework
- **Expo** - Managed React Native platform
- **React Navigation** - Navigation library
- **AsyncStorage** - Local data persistence

## 📚 API Endpoints

### Chat
- `POST /api/chat` - Process chat query
- `POST /api/chat/stream` - Stream chat response (SSE)

### Images
- `POST /api/image/generate` - Generate image from prompt
- `POST /api/image/redesign` - Redesign uploaded image
- `POST /api/image/analyze` - Analyze uploaded image

### Voice
- `POST /api/voice/transcribe` - Transcribe audio file

### Models
- `GET /api/models/list` - List available models
- `GET /api/status` - Get backend status

### Health
- `GET /health` - Health check
- `GET /` - API info

## 🎨 Design System

### Colors (Dark Mode)
- Primary: `#8b7cf7` (Purple)
- Background: `#0a0a0f`
- Surface: `#14141e`
- Text Primary: `#e8e8f0`
- Text Secondary: `#c8c8d8`

### Light Mode (automatically switches)
Colors automatically adapt to a light theme when enabled.

### Spacing System (4px based)
- xs: 4px
- sm: 8px
- md: 12px
- lg: 16px
- xl: 24px
- 2xl: 32px

## 📁 Project Structure

### Web Frontend
```
frontend-web/src/
├── components/          # Reusable React components
│   ├── ChatMessage.tsx
│   ├── ChatInput.tsx
│   ├── Sidebar.tsx
│   └── ActionBar.tsx
├── pages/              # Page components
│   └── ChatPage.tsx
├── context/            # React context for state management
│   └── ChatContext.tsx
├── api/               # API client
│   └── client.ts
├── styles/            # CSS files
└── types/             # TypeScript types
```

### Mobile Frontend
```
frontend-mobile/app/
├── screens/           # Screen components
│   ├── ChatScreen.tsx
│   └── SettingsScreen.tsx
├── components/        # Reusable components
├── context/          # State management
├── api/             # API client (shared)
├── theme/           # Design tokens
├── types/           # TypeScript types
└── navigation/      # Navigation setup
```

## 🔧 Configuration

### Backend API Configuration
Environment variables in `.env`:
```env
APEX_LLM_MODEL=llama3.2:1b
APEX_API_PORT=8000
OLLAMA_HOST=http://localhost:11434
```

### Mobile App (frontend-mobile)
Update API endpoint in `app/api/client.ts`:
```typescript
const baseURL = 'http://your-backend-server:8000/api'
```

## 🧪 Testing

### Test API endpoints
```bash
# Using curl
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"Hello","session_id":"default"}'

# Using Python
python -m pytest tests/
```

### Test Web Frontend
```bash
cd frontend-web
npm run dev
# Open browser and test all features
```

### Test Mobile App
```bash
cd frontend-mobile
npm run ios  # or npm run android
# Test on simulator or device
```

## 🚢 Deployment

### Deploy Backend API
```bash
# Using Heroku
heroku create apex-ai-api
heroku buildpacks:add heroku/python
git push heroku main

# Using Docker
docker build -t apex-ai-api .
docker run -p 8000:8000 apex-ai-api
```

### Deploy Web Frontend
```bash
cd frontend-web
npm run build

# Deploy to Vercel
npm install -g vercel
vercel deploy

# Deploy to Netlify
netlify deploy --prod --dir=dist
```

### Deploy Mobile App
```bash
cd frontend-mobile

# Build and submit to App Store (iOS)
eas build --platform ios
eas submit --platform ios

# Build and submit to Google Play (Android)
eas build --platform android
eas submit --platform android
```

## 📋 Checklist Before Production

- [ ] API server is running and accessible
- [ ] Frontend env variables are configured
- [ ] SSL/TLS certificates are set up
- [ ] CORS is properly configured
- [ ] Rate limiting is enabled
- [ ] Error logging is set up
- [ ] Database backups are scheduled
- [ ] Mobile app is tested on real devices
- [ ] Web app is tested on multiple browsers
- [ ] Performance is optimized (< 3s load time)

## 🐛 Troubleshooting

### API Connection Issues
```
Q: "Cannot connect to localhost:8000"
A: Ensure backend API is running: python -m uvicorn backend_api.main:app --reload
```

### Mobile App CORS Errors
```
Q: "Cross-Origin Request Blocked"
A: Update CORS settings in backend_api/main.py with your frontend URLs
```

### Expo App Won't Start
```
Q: "Error: Cannot find module"
A: Run `npm install` in frontend-mobile directory
```

## 📖 Documentation

- [React Documentation](https://react.dev)
- [FastAPI Docs](https://fastapi.tiangolo.com)
- [React Native Docs](https://reactnative.dev)
- [Expo Docs](https://docs.expo.dev)

## 📝 License

Same as original Apex AI project

## 🤝 Contributing

1. Create a feature branch
2. Make your changes
3. Test thoroughly
4. Create a pull request

## 💡 Tips & Tricks

### Hot Reloading
Both web and mobile apps support hot reloading during development.

### Debugging
- Web: Use browser DevTools (F12)
- Mobile: Use Expo DevTools or React Native Debugger

### Performance
- Web: Use Chrome DevTools Performance tab
- Mobile: Use Expo's built-in performance profiler

## 📞 Support

If you encounter issues:
1. Check the troubleshooting section
2. Review API documentation at http://localhost:8000/docs
3. Check browser console for errors
4. Enable debug logging in API

---

**Built with ❤️ for Apex AI**
