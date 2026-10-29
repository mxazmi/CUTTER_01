@echo off
cd /d C:\YTcutter

REM File sumber: cutter_01.py dulu, lalu cutter01.py, terakhir downloader.py
set SRC=cutter_01.py
if not exist %SRC% set SRC=cutter01.py
if not exist %SRC% set SRC=downloader.py

echo [1/5] Mengecek file...
if not exist %SRC% (
    echo [ERROR] Tidak ada cutter_01.py, cutter01.py, atau downloader.py di C:\YTcutter!
    pause
    exit /b 1
)
if not exist icon.ico (
    echo [ERROR] File 'icon.ico' tidak ditemukan!
    pause
    exit /b 1
)
echo Membangun dari: %SRC%

echo [2/5] Memasang psutil untuk meter kecepatan jaringan...
python -m pip install psutil
if errorlevel 1 echo [PERINGATAN] psutil gagal dipasang. Aplikasi tetap jalan, tapi meter kecepatan tidak aktif.

echo [3/5] Menutup CUTTER_01 yang sedang berjalan dan membersihkan build...
REM exe yang sedang berjalan tidak bisa dihapus Windows ("Access is denied"), jadi tutup dulu
taskkill /f /im CUTTER_01.exe >nul 2>&1
taskkill /f /im downloader.exe >nul 2>&1
timeout /t 2 /nobreak >nul
if exist build rmdir /s /q build
if exist dist\CUTTER_01.exe del /f /q dist\CUTTER_01.exe
if exist dist\downloader.exe del /f /q dist\downloader.exe
del *.spec 2>nul
if exist dist\CUTTER_01.exe (
    echo [ERROR] dist\CUTTER_01.exe masih terkunci dan tidak bisa dihapus.
    echo Tutup jendela Explorer yang membuka folder dist, pratinjau file, atau antivirus yang memindai file itu, lalu jalankan lagi.
    pause
    exit /b 1
)

echo [4/5] Kompilasi ulang dengan PyInstaller...
python -m PyInstaller --noconfirm --onefile --noconsole --icon=icon.ico --add-data "icon.ico;." --name=CUTTER_01 %SRC%
if errorlevel 1 (
    echo [ERROR] Kompilasi gagal!
    pause
    exit /b 1
)

echo [5/5] Menyalin file pendukung dan ikon ke folder dist...
REM Cari deno.exe otomatis dari PATH kalau belum ada di C:\YTcutter
if not exist deno.exe (
    for /f "delims=" %%i in ('where deno 2^>nul') do if not exist deno.exe copy "%%i" deno.exe >nul
)
if not exist deno.exe echo [PERINGATAN] deno.exe tidak ditemukan. Aplikasi tetap jalan di PC ini kalau deno ada di PATH, tapi tidak ikut terbawa saat dibagikan.

REM File yang sudah ada di dist tidak ditimpa, jadi hasil UPDATES di dalam aplikasi tidak hilang
if not exist dist\ffmpeg.exe copy ffmpeg.exe dist\
if not exist dist\ffprobe.exe copy ffprobe.exe dist\
if not exist dist\yt-dlp.exe copy yt-dlp.exe dist\
if exist deno.exe if not exist dist\deno.exe copy deno.exe dist\
copy /y icon.ico dist\

echo.
echo Selesai! Aplikasi dan seluruh file pendukung sudah siap di folder dist.
echo Kalau ikon di Explorer masih lama, itu cache ikon Windows. Ganti nama exe sekali lalu kembalikan.
pause