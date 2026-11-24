# SONAR

A simple all-in-one music player. Search, stream, download and organize music from one window.

SONAR was made for convenience. I use several different music players and got tired of switching between them, so I packed what I need into one small app. It is not trying to compete with anything.

---

## An honest note about how this was made

This project was **made with AI assistance**. Roughly **20% of the code is original and 80% is not**. It is a quick, practical tool for personal use, not a polished product.

You are free to edit it, change it, fork it, and make your own version. No permission needed.

---

## Features

- **Search** YouTube and SoundCloud, or paste any link that yt-dlp supports
- **Stream** results directly inside the app
- **Download** tracks as MP3 or FLAC into a folder you choose
- **Library** of everything you have saved, with filtering, shuffle, reveal in folder, and delete
- **Queue and playlists**, with shuffle, repeat (off / all / one), seek bar, and volume control
- **Download manager** with live progress and retry
- **Cover art and tags** embedded into saved files (optional)
- **Artist folders** for sorting downloads (optional)
- Space bar to play and pause

---

## Getting started

### Option 1: Use the exe

Download `Sonar.exe` from the [Releases](../../releases) page and run it. Nothing else needs to be installed. VLC and ffmpeg are bundled inside.

Settings, playlists, and the default `SONGS` folder are saved next to the exe, so keep it somewhere writable like your Desktop or Documents, not Program Files.

### Option 2: Build the exe yourself (Windows)

1. Put `sonar.py` and `build_sonar.bat` in one folder. Add `sonar_icon.ico` too if you want a custom exe icon.
2. Double-click `build_sonar.bat`.
3. Your exe will be at `dist\Sonar.exe`.

The batch file installs the required Python packages and downloads ffmpeg and the VLC files if they are missing. The first run downloads a few hundred MB.

### Option 3: Run from source

Requirements:

- Python 3.10 or newer
- [VLC media player](https://www.videolan.org) (64-bit) for playback
- [FFmpeg](https://ffmpeg.org) on your PATH for MP3 and FLAC conversion

```
pip install customtkinter yt-dlp pillow python-vlc mutagen
python sonar.py
```

If VLC or ffmpeg is missing, the Setup check in Settings will show what is not found. Search still works without VLC. Downloads need ffmpeg.

---

## Built with

| Project | Used for |
| --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Searching, streaming, and downloading |
| [VLC / python-vlc](https://www.videolan.org) | Audio playback |
| [FFmpeg](https://ffmpeg.org) | MP3 and FLAC conversion |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | The interface |
| [Pillow](https://python-pillow.org) | Images and the app icon |
| [mutagen](https://mutagen.readthedocs.io) | Reading tags from saved files |

---

## Please read

- Only download music you have the right to, and respect the terms of each service.
- This is a hobby tool provided as is, with no warranty and no promise of support.
- Streaming and downloading depend on yt-dlp, which sometimes breaks when sites change. If searches or downloads start failing, updating yt-dlp (`pip install -U yt-dlp`) or rebuilding the exe usually fixes it.
- The released exe includes VLC (LGPL) and FFmpeg (GPL). Their licenses apply to those parts. Links to their source are in the table above.

---

## License

The code in this repository is released under the [Unlicense](LICENSE). It is free to use, copy, modify, and distribute, for any purpose, with no conditions.
