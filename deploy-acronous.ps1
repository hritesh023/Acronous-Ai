# Deploy Acronous AI Worker + Frontend
Write-Host "=== Deploying Acronous AI ===" -ForegroundColor Cyan

# 1. Deploy Worker
Write-Host "`n[1/3] Deploying Cloudflare Worker..." -ForegroundColor Yellow
npx wrangler deploy cloudflare-worker.js --name acronous-ai
if ($LASTEXITCODE -ne 0) {
    Write-Host "Worker deploy failed!" -ForegroundColor Red
    exit 1
}
Write-Host "Worker deployed successfully!" -ForegroundColor Green

# 2. Build Frontend
Write-Host "`n[2/3] Building Flutter frontend..." -ForegroundColor Yellow
flutter build web --dart-define="API_BASE_URL=https://ai.acronous.com"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Flutter build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "Flutter build complete!" -ForegroundColor Green

# 3. Deploy Frontend
Write-Host "`n[3/3] Deploying frontend to Cloudflare Pages..." -ForegroundColor Yellow
Copy-Item -LiteralPath "web/_worker.js" -Destination "build/web/_worker.js" -Force
npx wrangler pages deploy build/web --project-name=acronous-ai
if ($LASTEXITCODE -ne 0) {
    Write-Host "Pages deploy failed!" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Deployment Complete! ===" -ForegroundColor Cyan
Write-Host "Worker: https://api.acronous.com"
Write-Host "Frontend: https://ai.acronous.com"
