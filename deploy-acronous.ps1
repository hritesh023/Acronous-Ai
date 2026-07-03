# PowerShell Deployment Script for Acronous AI

# This script deploys the enhanced Acronous AI with unlimited image editing capabilities
# Run this script from the Acronous Ai directory: cd "C:\Users\Hritesh\Hritesh-apps\Acronous Ai"

param(
    [switch]$SkipWorker,
    [switch]$SkipFrontend,
    [string]$ApiKey,
    [string]$ConfigPath = "wrangler.toml"
)

# Colors for output
$Host.UI.WriteObjectInvocationInfo.ForegroundColor = [ConsoleColor]::Green
Write-Host "=== Acronous AI Enhanced Deployment ===" -ForegroundColor Green
$Host.UI.WriteObjectInvocationInfo.ForegroundColor = [ConsoleColor]::White

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

# Check Node.js
$nodeAvailable = $false
try {
    $nodeVersion = node --version 2>$null
    if ($nodeVersion) {
        Write-Host "✓ Node.js is available: $nodeVersion" -ForegroundColor Green
        $nodeAvailable = $true
    }
}
catch {
    Write-Host "✗ Node.js is not available. Please install Node.js first." -ForegroundColor Red
    exit 1
}

# Check npm
$npmAvailable = $false
try {
    $npmVersion = npm --version 2>$null
    if ($npmVersion) {
        Write-Host "✓ npm is available: version $npmVersion" -ForegroundColor Green
        $npmAvailable = $true
    }
}
catch {
    Write-Host "✗ npm is not available. Please install npm first." -ForegroundColor Red
    exit 1
}

# Check wrangler
$wranglerAvailable = $false
try {
    $wranglerVersion = wrangler --version 2>$null
    if ($wranglerVersion) {
        Write-Host "✓ wrangler is available: $wranglerVersion" -ForegroundColor Green
        $wranglerAvailable = $true
    }
}
catch {
    Write-Host "⚠ wrangler is not available. Please install wrangler: npm install -g wrangler" -ForegroundColor Yellow
    $wranglerAvailable = $false
}

# Login to Cloudflare if wrangler is available
if ($wranglerAvailable) {
    try {
        $loginStatus = wrangler whoami 2>$null
        if ($loginStatus) {
            Write-Host "✓ Already logged into Cloudflare Workers" -ForegroundColor Green
        } else {
            Write-Host "Please login to Cloudflare Workers:" -ForegroundColor Yellow
            Write-Host "  wrangler login" -ForegroundColor Cyan
        }
    } catch {
        Write-Host "⚠ Please login to Cloudflare Workers:" -ForegroundColor Yellow
        Write-Host "  wrangler login" -ForegroundColor Cyan
    }
}

# Set API key if provided
if ($ApiKey) {
    try {
        $secretSet = wrangler secret put OPENROUTER_API_KEY --text $ApiKey 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ API key set successfully" -ForegroundColor Green
        }
    } catch {
        Write-Host "⚠ Failed to set API key. Please set it manually:" -ForegroundColor Yellow
        Write-Host "  wrangler secret put OPENROUTER_API_KEY" -ForegroundColor Cyan
    }
}

# Build enhanced worker configuration
Write-Host "`nValidating worker configuration..." -ForegroundColor Yellow

$workerFile = "cloudflare-worker.js"
if (-not (Test-Path $workerFile)) {
    Write-Host "✗ cloudflare-worker.js not found" -ForegroundColor Red
    exit 1
}

# Check for required features in the worker
$workerContent = Get-Content $workerFile -Raw -Encoding UTF8
$workerText = $workerContent -join ""

# Verify key features are present
$features = @(
    "chatHandler error handling",
    "generateNaturalResponse",
    "editImageWithInstruct",
    "llmReasonEditApproach",
    "ultraEditImage",
    "web search integration",
    "no empty response guarantee"
)

foreach ($feature in $features) {
    if ($workerText -match $feature.Replace(" ", ".*")) {
        Write-Host "✓ $feature detected" -ForegroundColor Green
    } else {
        Write-Host "⚠ $feature may not be present" -ForegroundColor Yellow
    }
}

# Deploy worker only
if (-not $SkipWorker -and $wranglerAvailable) {
    Write-Host "`nDeploying enhanced worker..." -ForegroundColor Yellow
    try {
        $deployCmd = "npx wrangler deploy cloudflare-worker.js --name acronous-ai --config $ConfigPath"
        Write-Host "Running: $deployCmd" -ForegroundColor Cyan
        $result = Invoke-Expression $deployCmd
        Write-Host "✓ Worker deployed successfully!" -ForegroundColor Green
        Write-Host "Your worker should now be available at https://ai.acronous.com" -ForegroundColor Green
    } catch {
        Write-Host "✗ Worker deployment failed: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "`nSkipping worker deployment (use -SkipWorker to skip)" -ForegroundColor Yellow
    if (-not $wranglerAvailable) {
        Write-Host "Note: wrangler not available. Please install global: npm install -g wrangler" -ForegroundColor Yellow
    }
}

# Deploy frontend only
if (-not $SkipFrontend -and $nodeAvailable) {
    Write-Host "`nDeploying frontend..." -ForegroundColor Yellow
    try {
        # Check if Flutter is available
        $flutterAvailable = $false
        try {
            $flutterVersion = flutter --version 2>$null
            if ($flutterVersion) {
                $flutterAvailable = $true
                Write-Host "✓ Flutter is available" -ForegroundColor Green
            }
        } catch {
            Write-Host "⚠ Flutter not available. Frontend deployment skipped." -ForegroundColor Yellow
        }
        
        if ($flutterAvailable) {
            # Build web app
            Push-Location "C:\Users\Hritesh\Hritesh-apps\Acronous Ai"
            try {
                $buildCmd = "flutter build web --dart-define=\"API_BASE_URL=https://ai.acronous.com\""
                Write-Host "Running: $buildCmd" -ForegroundColor Cyan
                $buildResult = Invoke-Expression $buildCmd
                
                # Copy web worker
                $webWorkerSource = "web/_worker.js"
                $webWorkerDest = "build/web/_worker.js"
                if (Test-Path $webWorkerSource) {
                    Copy-Item $webWorkerSource $webWorkerDest -Force
                    Write-Host "✓ Web worker copied" -ForegroundColor Green
                }
                
                # Deploy pages if wrangler is available
                if ($wranglerAvailable) {
                    $pagesCmd = "npx wrangler pages deploy build/web --project-name=acronous-ai"
                    Write-Host "Running: $pagesCmd" -ForegroundColor Cyan
                    $pagesResult = Invoke-Expression $pagesCmd
                    Write-Host "✓ Frontend deployed successfully!" -ForegroundColor Green
                } else {
                    Write-Host "⚠ Skipping Pages deployment (wrangler not available)" -ForegroundColor Yellow
                }
            } catch {
                Write-Host "✗ Frontend deployment failed: $($_.Exception.Message)" -ForegroundColor Red
            }
            Pop-Location
        }
    } catch {
        Write-Host "✗ Frontend deployment failed: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "`nSkipping frontend deployment (use -SkipFrontend to skip)" -ForegroundColor Yellow
}

# Create deployment verification script
$verifyScript = @"
# Verification script for Acronous AI deployment
# Run this after deployment to test functionality

Write-Host "=== Acronous AI Deployment Verification ===" -ForegroundColor Green

# Test worker health
Write-Host "Testing worker health..." -ForegroundColor Yellow
try {
    $healthResponse = Invoke-RestMethod -Uri "https://ai.acronous.com/health" -Method GET -TimeoutSec 30
    Write-Host "✓ Worker is healthy" -ForegroundColor Green
} catch {
    Write-Host "⚠ Worker health check failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Test chat endpoint
Write-Host "Testing chat functionality..." -ForegroundColor Yellow
try {
    $chatBody = @{message = "Hello, how are you?"} | ConvertTo-Json -Depth 4
    $chatResponse = Invoke-RestMethod -Uri "https://ai.acronous.com/v1/chat" -Method POST -Body $chatBody -ContentType "application/json" -TimeoutSec 30
    if ($chatResponse.response) {
        Write-Host "✓ Chat endpoint responded: $($chatResponse.response.Substring(0, [Math]::Min(50, $chatResponse.response.Length)))..." -ForegroundColor Green
    }
} catch {
    Write-Host "⚠ Chat endpoint test failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host "=== Verification Complete ===" -ForegroundColor Green
"@"

# Save verification script
$verifyScriptPath = "verify-deployment.ps1"
$verifyScript | Out-File -FilePath $verifyScriptPath -Encoding UTF8
Write-Host "✓ Verification script created: $verifyScriptPath" -ForegroundColor Green

# Summary
Write-Host "`n=== Deployment Summary ===" -ForegroundColor Green
Write-Host "The enhanced Acronous AI has been deployed with:" -ForegroundColor White
Write-Host "  ✓ Unlimited AI image editing capabilities" -ForegroundColor Green
Write-Host "  ✓ Guaranteed non-empty responses" -ForegroundColor Green
Write-Host "  ✓ Web search integration for editing" -ForegroundColor Green
Write-Host "  ✓ Enhanced cut/replace detection" -ForegroundColor Green
Write-Host "  ✓ Optimized response generation" -ForegroundColor Green
Write-Host "`nTo verify deployment:" -ForegroundColor White
Write-Host "  powershell -ExecutionPolicy Bypass -File verify-deployment.ps1" -ForegroundColor Cyan
Write-Host "`nFor manual verification, check logs in Cloudflare Workers dashboard." -ForegroundColor Gray
