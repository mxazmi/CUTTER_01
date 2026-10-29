# CUTTER_01

A desktop video downloader and batch cutter built with Python.

![CUTTER_01 application screenshot](https://github.com/user-attachments/assets/9c958bea-eb5c-4f00-a88e-5d1ac5fb8ae0)

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

## Support

If you find CUTTER_01 useful, you can optionally support its creator with a donation. Donations are completely voluntary. The app is free to use, and donations do not guarantee future updates or support.

[![Donate with PayPal](https://img.shields.io/badge/Donate-PayPal-blue?logo=paypal)](https://paypal.me/MixilAzmi)

Made by Mixil Mina Azmi.
