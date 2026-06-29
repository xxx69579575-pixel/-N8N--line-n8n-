' watchdog_n8n_launch.vbs - launch watchdog_n8n_log.ps1 fully hidden (no console flash).
' Window style 0 = hidden; wscript itself is windowless. Path resolved at runtime
' from this script's own folder, so no non-ASCII literals live in this source.
Dim fso, shell, here, ps1, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = here & "\watchdog_n8n_log.ps1"
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """"
shell.Run cmd, 0, False
