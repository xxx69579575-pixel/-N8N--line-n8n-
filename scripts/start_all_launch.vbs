' Run the consolidated startup hidden and return its exit code to Task Scheduler.
Option Explicit
Dim fso, shell, here, ps1, powershell, command, result
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = fso.BuildPath(here, "start_all.ps1")
powershell = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
command = """" & powershell & """ -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """"
result = shell.Run(command, 0, True)
WScript.Quit result
