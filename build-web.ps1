#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Builds the Acronous AI Flutter web app.
    Run this before deploying to Cloudflare Pages.
#>

$ErrorActionPreference = "Stop"

$apiBaseUrl = $env:API_BASE_URL
if (-not $apiBaseUrl) { $apiBaseUrl = "https://acronous-ai-api.httpsacronous-landinghriteshkumarpatroworkersdev.workers.dev" }

Write-Host "Building Acronous AI Flutter Web..." -ForegroundColor Cyan
Write-Host "  API Base URL: $apiBaseUrl" -ForegroundColor Gray

flutter build web `
    --dart-define="API_BASE_URL=$apiBaseUrl"

if ($LASTEXITCODE -eq 0) {
    # Copy the Pages _worker.js into the build output for auth + SPA routing
    Copy-Item -LiteralPath "web/_worker.js" -Destination "build/web/_worker.js" -Force

    Write-Host "`n✓ Build successful!" -ForegroundColor Green
    Write-Host "  ✓ Copied web/_worker.js to build/web/_worker.js" -ForegroundColor Gray
    Write-Host ""
    Write-Host "To deploy Flutter app to Cloudflare Pages:" -ForegroundColor Cyan
    Write-Host "  npx wrangler pages deploy build/web --project-name=acronous-ai" -ForegroundColor White
    Write-Host ""
    Write-Host "To deploy API worker:" -ForegroundColor Cyan
    Write-Host "  npx wrangler deploy cloudflare-worker.js --name acronous-ai-api" -ForegroundColor White
    Write-Host ""
    Write-Host "The subdomain ai.acronous.com is proxied via the landing page worker." -ForegroundColor Gray
}
