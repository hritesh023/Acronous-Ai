#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Tags existing Acronous AI AWS resources with the awsApplication tag
    so they are associated with the AWS Resource Groups application.
#>

$ErrorActionPreference = "Stop"
$Region = "eu-north-1"
$TagKey = "awsApplication"
$TagValue = "arn:aws:resource-groups:eu-north-1:365528424228:group/Acronous_ai/0dvgasm7yvgstcm59pokw3cc0x"

# ── Cognito User Pool ─────────────────────────────────────────────────
try {
    $poolId = "eu-north-1_z141VJjsi"
    Write-Host "Tagging Cognito User Pool: $poolId ..." -ForegroundColor Yellow
    aws cognito-idp tag-resource `
        --resource-arn "arn:aws:cognito-idp:eu-north-1:365528424228:userpool/$poolId" `
        --tags "$TagKey=$TagValue" `
        --region $Region
    Write-Host "  ✓ Tagged" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Failed: $_" -ForegroundColor Red
}

# ── Cognito User Pool Client ──────────────────────────────────────────
try {
    $clientId = "77vr92sf6e3ubrqamamrubt25b"
    Write-Host "Tagging Cognito User Pool Client: $clientId ..." -ForegroundColor Yellow
    aws cognito-idp tag-resource `
        --resource-arn "arn:aws:cognito-idp:eu-north-1:365528424228:userpool/$poolId/client/$clientId" `
        --tags "$TagKey=$TagValue" `
        --region $Region
    Write-Host "  ✓ Tagged" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Failed: $_" -ForegroundColor Red
}

# ── Lambda Function ───────────────────────────────────────────────────
$functions = @("AcronousAi-AutoConfirm")
foreach ($fn in $functions) {
    try {
        Write-Host "Tagging Lambda: $fn ..." -ForegroundColor Yellow
        aws lambda tag-resource `
            --resource "arn:aws:lambda:eu-north-1:365528424228:function:$fn" `
            --tags "$TagKey=$TagValue" `
            --region $Region
        Write-Host "  ✓ Tagged" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Failed: $_" -ForegroundColor Red
    }
}

# ── IAM Role ──────────────────────────────────────────────────────────
$roles = @("AcronousAi-Lambda-Cognito", "AcronousAi-AutoConfirm-Role")
foreach ($role in $roles) {
    try {
        Write-Host "Tagging IAM Role: $role ..." -ForegroundColor Yellow
        aws iam tag-role `
            --role-name $role `
            --tags "Key=$TagKey,Value=$TagValue"
        Write-Host "  ✓ Tagged" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Not found or failed: $_" -ForegroundColor Red
    }
}

Write-Host "`n=== Done ===" -ForegroundColor Green
Write-Host "All taggable resources should now be associated with the Acronous AI application." -ForegroundColor Cyan
