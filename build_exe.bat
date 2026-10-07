@echo off
rem Сборка MicroPhoto.exe (папка dist\MicroPhoto). Запускать из активированного venv.
pip install pyinstaller
pyinstaller --noconfirm --windowed --name MicroPhoto ^
  --add-data "microphoto\resources;microphoto\resources" ^
  --collect-all pillow_heif ^
  main.py
echo.
echo Готово: dist\MicroPhoto\MicroPhoto.exe
