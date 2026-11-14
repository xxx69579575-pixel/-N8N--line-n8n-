#requires -Version 5.1
# Install the consolidated startup task and retire legacy startup entries.
# Existing startup/watchdog task configuration is preserved.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$taskName = 'AI-QA-Assistant-Startup'
$launcher = Join-Path $projectRoot 'scripts\start_all_launch.vbs'
$startupScript = Join-Path $projectRoot 'scripts\start_all.ps1'

foreach ($path in @($launcher, $startupScript)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Startup file not found: $path"
    }
}

$existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.State -eq 'Disabled') {
        throw "$taskName is disabled. Review its configuration before enabling startup."
    }
    $actionText = ($existing.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join ' '
    if ($actionText.IndexOf($projectRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "$taskName points to another location. Review the task before replacing startup entries."
    }
    Write-Host "$taskName already exists; keeping its configuration."
} else {
    $userId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wscript.exe" `
        -Argument "//nologo `"$launcher`"" -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
        -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal | Out-Null
    Write-Host "$taskName created (hidden startup at logon)."
}

# These obsolete tasks refer to deleted *_bg.bat files. Never recreate them.
foreach ($legacyName in @('AI_ApiServer', 'AI_Ngrok')) {
    $legacyTask = Get-ScheduledTask -TaskName $legacyName -TaskPath '\' -ErrorAction SilentlyContinue
    if ($legacyTask -and $legacyTask.State -ne 'Disabled') {
        Disable-ScheduledTask -TaskName $legacyName -TaskPath '\' | Out-Null
        Write-Host "Disabled legacy task: $legacyName"
    }
}

# Startup-folder shortcuts are independent of Task Scheduler. Archive them too.
$startupDir = [Environment]::GetFolderPath('Startup')
$backupDir = Join-Path $env:LOCALAPPDATA ('ai-qa-startup\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$shell = New-Object -ComObject WScript.Shell
foreach ($name in @('N8N_API_Server.lnk', 'N8N_Ngrok.lnk')) {
    $shortcutPath = Join-Path $startupDir $name
    if (-not (Test-Path -LiteralPath $shortcutPath)) { continue }
    $shortcut = $shell.CreateShortcut($shortcutPath)
    if ($shortcut.Arguments.IndexOf($projectRoot + '\start_', [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Write-Warning "Keeping unrelated shortcut: $shortcutPath"
        continue
    }
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $backupPath = Join-Path $backupDir $name
    Copy-Item -LiteralPath $shortcutPath -Destination $backupPath
    if ((Get-FileHash -LiteralPath $shortcutPath).Hash -ne (Get-FileHash -LiteralPath $backupPath).Hash) {
        throw "Shortcut backup verification failed: $shortcutPath"
    }
    Remove-Item -LiteralPath $shortcutPath
    Write-Host "Archived legacy shortcut: $backupPath"
}

Write-Host 'Startup setup complete. Existing services were not restarted.'
