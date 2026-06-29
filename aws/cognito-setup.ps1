#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Attaches a Pre Sign-up Lambda to auto-confirm users in the existing Cognito pool.
    No verification code needed — signup goes straight to the app.
.PARAMETER Region
    AWS region (default: eu-north-1)
.PARAMETER PoolId
    Cognito User Pool ID (default: from .env or eu-north-1_z141VJjsi)
#>
param(
    [string]$Region = "eu-north-1",
    [string]$PoolId = ""
)

$ErrorActionPreference = "Stop"

if (-not $PoolId) {
    $envFile = Join-Path $PSScriptRoot ".." ".env"
    if (Test-Path $envFile) {
        $content = Get-Content $envFile -Raw
        $match = [regex]::Match($content, 'COGNITO_USER_POOL_ID=(\S+)')
        if ($match.Success) {
            $PoolId = $match.Groups[1].Value
        }
    }
}
if (-not $PoolId) {
    $PoolId = "eu-north-1_z141VJjsi"
}

Write-Host "Using Cognito Pool: $PoolId" -ForegroundColor Cyan

# ── Step 1: Create Lambda function ─────────────────────────────────────
$lambdaName = "AcronousAi-AutoConfirm"
Write-Host "`nCreating Lambda function: $lambdaName ..." -ForegroundColor Yellow

$zipPath = "$env:TEMP\acronous-auto-confirm.zip"
$codePath = "$env:TEMP\acronous-lambda-code.py"

@"
import json
def lambda_handler(event, context):
    event["response"]["autoConfirmUser"] = True
    event["response"]["autoVerifyEmail"] = True
    event["response"]["autoVerifyPhone"] = True
    return event
"@ | Set-Content -Path $codePath -Force

# Create ZIP
Compress-Archive -Path $codePath -DestinationPath $zipPath -Force

try {
    $existing = aws lambda get-function --function-name $lambdaName --region $Region 2>$null
    if ($existing) {
        Write-Host "Lambda already exists. Updating code..." -ForegroundColor Yellow
        aws lambda update-function-code --function-name $lambdaName --zip-file "fileb://$zipPath" --region $Region | Out-Null
    }
    else {
        # Get or create IAM role
        $roleName = "AcronousAi-Lambda-Cognito"
        $roleArn = aws iam get-role --role-name $roleName --query 'Role.Arn' --output text 2>$null
        if (-not $roleArn) {
            Write-Host "Creating IAM role..." -ForegroundColor Yellow
            $trustPolicy = @"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
"@
            $tmpTrust = "$env:TEMP\trust-policy.json"
            $trustPolicy | Set-Content -Path $tmpTrust -Force
            $roleArn = aws iam create-role --role-name $roleName --assume-role-policy-document "file://$tmpTrust" --query 'Role.Arn' --output text
            aws iam attach-role-policy --role-name $roleName --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
        }

        aws lambda create-function `
            --function-name $lambdaName `
            --runtime python3.11 `
            --handler lambda_handler `
            --role $roleArn `
            --zip-file "fileb://$zipPath" `
            --region $Region | Out-Null

        Write-Host "Lambda created." -ForegroundColor Green
    }

    # ── Step 2: Add invoke permission for Cognito ──────────────────────
    $poolArn = aws cognito-idp describe-user-pool --user-pool-id $PoolId --region $Region --query 'UserPool.Arn' --output text
    $lambdaArn = aws lambda get-function --function-name $lambdaName --region $Region --query 'Configuration.FunctionArn' --output text

    Write-Host "`nAdding Cognito invoke permission..." -ForegroundColor Yellow
    aws lambda add-permission `
        --function-name $lambdaName `
        --statement-id CognitoInvoke `
        --action lambda:InvokeFunction `
        --principal cognito-idp.amazonaws.com `
        --source-arn $poolArn `
        --region $Region 2>$null | Out-Null

    # ── Step 3: Attach to Cognito pool as Pre Sign-up trigger ──────────
    Write-Host "`nAttaching Lambda as Pre Sign-up trigger..." -ForegroundColor Yellow
    aws cognito-idp describe-user-pool --user-pool-id $PoolId --region $Region --query 'UserPool.LambdaConfig' | Out-Null

    $currentConfig = aws cognito-idp describe-user-pool --user-pool-id $PoolId --region $Region --query 'UserPool.LambdaConfig' --output json 2>$null
    if (-not $currentConfig -or $currentConfig -eq "null") {
        $currentConfig = "{}"
    }

    aws cognito-idp update-user-pool `
        --user-pool-id $PoolId `
        --lambda-config "{\"PreSignUp\":\"$lambdaArn\"}" `
        --region $Region

    Write-Host "`n=== Done ===" -ForegroundColor Green
    Write-Host "Lambda $lambdaName attached as Pre Sign-up trigger to pool $PoolId" -ForegroundColor Cyan
    Write-Host "New users will be auto-confirmed — no verification code needed." -ForegroundColor Green
}
finally {
    Remove-Item $zipPath -ErrorAction SilentlyContinue
    Remove-Item $codePath -ErrorAction SilentlyContinue
}
