# CUTTER_01

A desktop video downloader and batch cutter built with Python and Tkinter.

## Features

- Batch video downloads using yt-dlp
- Video cutting with FFmpeg
- Download quality and format settings
- Queue and progress monitoring
- Configurable download and cutting options

## Requirements

- Windows
- Python 3
- yt-dlp
- FFmpeg, including ffmpeg and ffprobe
- Deno may be needed for some yt-dlp extraction features

## Setup

1. Install Python 3.
2. Install the Python packages:

   `python -m pip install -r requirements.txt`

3. Obtain yt-dlp and FFmpeg from their official project websites.
4. Follow the build configuration and `build.bat` instructions to place the required tools where the application expects them.
5. Run `python downloader.py` to launch the application.

## Building

Review `build.bat` and `CUTTER_01.spec` before building. The required external tools must be available at the paths expected by the build configuration.

## License

See `LICENSE`.
