Option Explicit

Dim shell, files, folder, powershell, command, result, argument, publish, codexActivity
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
powershell = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe")
command = """" & powershell & """ -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & files.BuildPath(folder, "sync-profile.ps1") & """"

For Each argument In WScript.Arguments
    Select Case LCase(argument)
        Case "-publish"
            If publish Then WScript.Quit 2
            publish = True
            command = command & " -Publish"
        Case "-codexactivity"
            If codexActivity Then WScript.Quit 2
            codexActivity = True
            command = command & " -CodexActivity"
        Case Else
            WScript.Quit 2
    End Select
Next

' Launch hidden from process creation, and preserve the job's exit status.
On Error Resume Next
result = shell.Run(command, 0, True)
If Err.Number <> 0 Then WScript.Quit 1
WScript.Quit result
