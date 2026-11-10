' Starter SecretAI helt uden vindue. Fejl logges i secretai.log og bridge.log.
Set sh = CreateObject("WScript.Shell")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run "pythonw """ & dir & "\secretai.py""", 0, False
