Option Explicit

Dim shell, files, folder, powershell, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
powershell = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe")
command = """" & powershell & """ -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & files.BuildPath(folder, "sync-profile.ps1") & """"

If WScript.Arguments.Count > 0 Then
    If WScript.Arguments.Count <> 1 Then WScript.Quit 2
    If LCase(WScript.Arguments(0)) <> "-publish" Then WScript.Quit 2
    command = command & " -Publish"
End If

' Launch hidden from process creation, and preserve the job's exit status.
On Error Resume Next
result = shell.Run(command, 0, True)
If Err.Number <> 0 Then WScript.Quit 1
WScript.Quit result
