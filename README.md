<div align="center">

# ScriptMania

**A personal toolbox of scripts, command-line helpers, configuration snippets, and technical notes.**

Small utilities for downloads, files, media, networking, Linux system tasks, and Windows workflows.

</div>

---

## Getting started

There is no single application entry point or repository-wide installer. Each file is an independent helper, so start by opening the script you intend to use and checking its arguments and assumptions.

Some shell files are command snippets rather than fully featured CLIs. Check the file before running it; arguments and prompts are not standardized across the collection.

## Requirements

Install only the tools required by the script you plan to run. Depending on the task, this collection uses tools such as:

- **General:** Bash, Python 3, and common Linux command-line utilities.
- **Downloads and networking:** `aria2c`, `wget`, `curl`, `yt-dlp`, `rclone`, `nping`, `bmon`, Tailscale, and `iptables`.
- **Media:** FFmpeg/FFplay, MPV, ExifTool, ImageMagick, and Enfuse.
- **Files and encryption:** `zip`, `tar`, `gpg`, and 7-Zip.
- **Windows:** AutoHotkey v2, MPV, and `yt-dlp` for the relevant helpers.

A few scripts are hardware- or platform-specific. For example, some media scripts expect NVIDIA NVENC/CUDA or AMD AMF support, and several system/network scripts assume Linux utilities or system services.
