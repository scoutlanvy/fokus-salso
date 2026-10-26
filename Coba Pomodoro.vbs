Option Explicit

Dim shell, files, projectDirectory, pythonPath
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
projectDirectory = files.GetParentFolderName(WScript.ScriptFullName)
pythonPath = files.BuildPath(projectDirectory, ".venv\Scripts\pythonw.exe")

If Not files.FileExists(pythonPath) Then
    MsgBox "Python tidak ditemukan di .venv. Pastikan folder .venv tersedia di folder project.", vbExclamation, "Study Timer"
    WScript.Quit 1
End If

' Only this launcher and its child process inherit test mode.
shell.Environment("PROCESS")("STUDY_TIMER_PREVIEW") = "1"
shell.CurrentDirectory = projectDirectory
shell.Run Chr(34) & pythonPath & Chr(34) & " " & Chr(34) & files.BuildPath(projectDirectory, "main.py") & Chr(34), 0, False
