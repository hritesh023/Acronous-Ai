#!/bin/bash

# Apex AI - Quick Setup Script
# This script installs all dependencies for the backend API, web frontend, and mobile frontend

set -e

echo "🚀 Apex AI Setup Script"
echo "======================="
echo ""

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+."
    exit 1
fi
echo "✅ Node.js $(node -v) found"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed."
    exit 1
fi
echo "✅ Python $(python3 --version) found"

echo ""
echo "Installing dependencies..."
echo ""

# Backend API
echo "📦 Setting up Backend API..."
cd backend_api
pip install -r requirements.txt
echo "✅ Backend API dependencies installed"
cd ..

echo ""

# Web Frontend
echo "📦 Setting up React Web Frontend..."
cd frontend-web
npm install
echo "✅ Web Frontend dependencies installed"
cd ..

echo ""

# Mobile Frontend
echo "📦 Setting up React Native Mobile Frontend..."
cd frontend-mobile
npm install
echo "✅ Mobile Frontend dependencies installed"
cd ..

echo ""
echo "✨ Setup Complete!"
echo ""
echo "📚 Next Steps:"
echo ""
echo "1. Start Backend API:"
echo "   cd backend_api"
echo "   python -m uvicorn main:app --reload --port 8000"
echo ""
echo "2. Start Web Frontend (in new terminal):"
echo "   cd frontend-web"
echo "   npm run dev"
echo ""
echo "3. Start Mobile Frontend (in new terminal):"
echo "   cd frontend-mobile"
echo "   npm start"
echo ""
echo "🌐 Web: http://localhost:5173"
echo "📱 Mobile: http://localhost:8081"
echo "⚙️  API Docs: http://localhost:8000/docs"
echo ""
