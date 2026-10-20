CREDIT CARD FRAUD DETECTION — LOCAL OPENCODE STARTER

WHAT'S INCLUDED
- reference/*.pdf: the two original assignment references
- reference/*.txt: searchable text extractions (PDF diagrams/figures remain in the PDFs)
- AGENTS.md: persistent scope, safety, engineering and syllabus requirements
- TASK_PROMPT.txt: prompt to submit to Qwen after opening OpenCode
- opencode.json: project-local model/context configuration and conservative permissions

SETUP (Windows PowerShell)
1. Extract this folder to:
   C:\AI\Projects\Fraud-Detection-SE-Lab
   (Create the parent path if needed. Don't launch OpenCode from your Desktop Projects parent folder.)
2. Make sure the existing llama-server.exe process is still running and Qwen is loaded on http://127.0.0.1:8080. Do NOT stop PID 23260 while coding; OpenCode needs that server.
3. Stop the old OpenCode web UI by going to the PowerShell window where `opencode web --hostname 127.0.0.1 --port 4096` was running and pressing Ctrl+C. This is optional, but matches the requested terminal-only workflow.
4. Open a NEW PowerShell window and run:
   Set-Location 'C:\AI\Projects\Fraud-Detection-SE-Lab'
   opencode
5. The terminal UI (TUI) should open. Model is configured in this folder as `llama.cpp/qwen-local`. If it doesn't select automatically, use `/models` and choose `llama.cpp/qwen-local`.
6. Open `TASK_PROMPT.txt`, copy the text into the OpenCode prompt, and press Enter. Keep the terminal open.

CONTEXT
- The local llama-server is currently configured for 32,768 context tokens. OpenCode is told context=32,768 and output limit=4,096. This is not infinite memory: long sessions may be summarised/compacted.
- Qwen has been measured at roughly 2.4 generated tokens/second on this laptop in the last test. In an hour, output throughput is limited; prioritise the runnable MVP rather than expect a giant production system to finish.

SCOPE / SAFETY
- Project-local `external_directory: deny` restricts OpenCode's file tools to the workspace; edits inside this workspace are allowed automatically.
- Shell commands default to ASK. A small allowlist covers common tests and read-only git checks. If it needs a command not on the allowlist, it may wait for approval while you are away. That's intentional: allowing arbitrary shell commands would not be a real sandbox because shell runs with your Windows account's authority.
- This is an application-level guardrail, NOT a hard OS sandbox against malicious shell/code. For a hard security boundary, use a separately isolated OS/VM with only this workspace shared. The task itself forbids outside-folder access and installs.
- Do not put real cardholder data, secrets, actual PANs or CVVs into this academic prototype.
