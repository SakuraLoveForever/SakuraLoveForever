param(
    [switch]$Publish,
    [switch]$InstallTask,
    [switch]$RemoveTask
)

$ErrorActionPreference = 'Stop'
# Scheduled jobs must fail cleanly rather than open an authentication prompt.
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'Never'
$taskName = 'SakuraLoveForever-ProfileStats'
$repoRoot = Split-Path -Parent $PSScriptRoot
$stateRoot = Join-Path $env:LOCALAPPDATA 'SakuraLoveForever'
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null

if ($RemoveTask) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Removed $taskName"
    exit 0
}

if ($InstallTask) {
    $arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    if ($Publish) { $arguments += ' -Publish' }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $repoRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At '08:30'
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -Hidden `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Force | Out-Null
    Write-Output "Installed $taskName (daily at 08:30 local time while logged in; publish=$Publish)"
    exit 0
}

$logFile = Join-Path $stateRoot 'profile-sync.log'

function Invoke-NativeLogged {
    param([string]$Command, [string[]]$Arguments, [string]$Failure, [switch]$AllowFailure)
    # Windows PowerShell 5.1 turns native stderr progress into error records.
    # Capture it with Continue, then use the process exit code to detect failure.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Command @Arguments 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
        $nativeExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($nativeExit -ne 0 -and -not $AllowFailure) { throw $Failure }
}

$lock = $null
try {
    # This lock protects both manual and scheduled invocations on this PC.
    $lock = [System.IO.File]::Open((Join-Path $stateRoot 'profile-sync.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Set-Location -LiteralPath $repoRoot
    if ($Publish) {
        $branch = & git branch --show-current
        if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') { throw 'Publishing requires the main branch.' }
        # Avoid committing or rebasing work the user is editing in this checkout.
        $dirty = & git status --porcelain
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the Git working tree.' }
        if ($dirty) { throw 'Working tree is not clean; scheduled publication skipped.' }
        Invoke-NativeLogged 'git' @('pull', '--rebase', 'origin', 'main') 'Cannot update main; statistics were not changed.'
    }
    Invoke-NativeLogged 'python' @((Join-Path $PSScriptRoot 'profile_stats.py'), 'collect') 'Collection failed; inspect the local log.'
    if ($Publish) {
        & git add -- data/ai-usage.json data/badges assets/ai-usage.png
        if ($LASTEXITCODE -ne 0) { throw 'Cannot stage aggregate assets.' }
        & git diff --cached --quiet
        if ($LASTEXITCODE -eq 1) {
            Invoke-NativeLogged 'git' @('commit', '-m', 'chore: refresh local AI usage [skip ci]', '--',
                'data/ai-usage.json', 'data/badges', 'assets/ai-usage.png') 'Cannot commit aggregate assets.'
        } elseif ($LASTEXITCODE -ne 0) { throw 'Cannot inspect staged changes.' }
        # Existing cloud metrics jobs own different files, so their commits can be rebased.
        try {
            Invoke-NativeLogged 'git' @('pull', '--rebase', 'origin', 'main') 'Rebase failed.'
        } catch {
            Invoke-NativeLogged 'git' @('rebase', '--abort') '' -AllowFailure
            throw 'Rebase failed; retained the local aggregate commit for review.'
        }
        Invoke-NativeLogged 'git' @('push', 'origin', 'main') 'Push failed; retained the local aggregate commit for the next run.'
    }
    "$(Get-Date -Format o) Profile statistics refreshed (publish=$Publish)" |
        Out-File -FilePath $logFile -Append -Encoding utf8
    Write-Output "Profile statistics refreshed. Local log: $logFile"
} catch {
    "$(Get-Date -Format o) $($_.Exception.Message)" | Out-File -FilePath $logFile -Append -Encoding utf8
    Write-Error $_.Exception.Message
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
}
