# Push this project to GitHub (run on your PC where Git is installed)
#
# Repo: https://github.com/sixtyfourbitsquad/message-scheduler
#
# Prerequisites:
#   - Git for Windows: https://git-scm.com/download/win
#   - GitHub account with push access to sixtyfourbitsquad/message-scheduler
#   - HTTPS: Personal Access Token (classic) with `repo` scope when Git asks for a password
#
# Usage (PowerShell), from anywhere:
#   & "f:\Telegram Bots\Message-shedular\scripts\initial-push.ps1"

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "Git is not in PATH. Install from https://git-scm.com/download/win then re-open PowerShell."
}

$remoteUrl = "https://github.com/sixtyfourbitsquad/message-scheduler.git"

if (-not (Test-Path ".git")) {
    git init -b main
}

$null = git remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0) {
    git remote add origin $remoteUrl
} else {
    git remote set-url origin $remoteUrl
}

git add -A
git status

$status = git status --porcelain
if ($status) {
    git commit -m "Initial commit: Telegram channel automation bot (webhook, PostgreSQL, APScheduler)"
}

Write-Host ""
Write-Host "Pushing to origin main..."
Write-Host "If prompted: GitHub username + PAT (not your GitHub password)."
git push -u origin main

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Push failed. If you use SSH instead:"
    Write-Host "  git remote set-url origin git@github.com:sixtyfourbitsquad/message-scheduler.git"
    Write-Host "  git push -u origin main"
}
