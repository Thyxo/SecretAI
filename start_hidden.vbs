' Starter SecretAI uden konsolvindue. Fejl logges i secretai.log og bridge.log.
' Vinduesstil 1 (ikke 0): pythonw har ingen konsol, og 0 ville skjule SecretAI-vinduet ved start.
Set sh = CreateObject("WScript.Shell")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run "pythonw """ & dir & "\secretai.py""", 1, False
