---
name: termux-admin
description: Termux and Android system administration
requires.bins: termux-info
---

When managing the Termux environment:
- Use `pkg` instead of `apt` for package management (pkg install, pkg update)
- Storage is at /storage/emulated/0/ (requires termux-setup-storage)
- Use termux-* commands for device APIs (termux-battery-status, termux-wifi-connectioninfo, etc.)
- For background tasks: use termux-job-scheduler or nohup
- Common paths: $HOME (~), $PREFIX (/data/data/com.termux/files/usr)
- If permission denied: suggest `termux-setup-storage` for storage access
- Monitor resources with `top`, `free -h`, `df -h`
- For networking: `termux-wifi-connectioninfo`, `curl`, `wget`
