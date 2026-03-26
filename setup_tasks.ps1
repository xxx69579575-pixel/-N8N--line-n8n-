$dir = "D:\n8n\CLAUDE 實做\本地AI企業問答助理"

# Task 1: Python API Server
$action1 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$dir\start_api_server_bg.bat`""
$trigger1 = New-ScheduledTaskTrigger -AtLogOn
$settings1 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "AI_ApiServer" -Action $action1 -Trigger $trigger1 -Settings $settings1 -RunLevel Highest -Force
Write-Host "AI_ApiServer task created"

# Task 2: ngrok tunnel
$action2 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$dir\start_ngrok_bg.bat`""
$trigger2 = New-ScheduledTaskTrigger -AtLogOn
$settings2 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "AI_Ngrok" -Action $action2 -Trigger $trigger2 -Settings $settings2 -RunLevel Highest -Force
Write-Host "AI_Ngrok task created"
