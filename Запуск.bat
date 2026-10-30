@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Микрофото

rem ============================================================
rem  Запуск программы «Микрофото».
rem  Работает из любой папки: переходит в папку, где лежит этот файл.
rem  При первом запуске сам создает виртуальное окружение .venv
rem  и устанавливает библиотеки из requirements.txt.
rem  Настройки и сохраненная работа хранятся в %LOCALAPPDATA%\MicroPhoto
rem  и этим файлом не затрагиваются.
rem ============================================================

cd /d "%~dp0"
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "MARK=%VENV%\requirements.installed"

if not exist "main.py" (
    echo Не найден файл main.py рядом с Запуск.bat.
    echo Запуск.bat должен лежать в папке программы.
    goto :fail
)

rem ---------- 1. Виртуальное окружение ----------
rem (без блоков в скобках: внутри них %PYEXE% подставилась бы раньше, чем ее найдет :find_python)
if not exist "%VPY%" goto :make_venv
"%VPY%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto :deps
echo Виртуальное окружение повреждено — создаю заново...
rmdir /s /q "%VENV%"

:make_venv
call :find_python
if errorlevel 1 goto :fail
echo Создаю виртуальное окружение — это нужно только один раз...
%PYEXE% -m venv "%VENV%"
if errorlevel 1 goto :venv_failed
if not exist "%VPY%" goto :venv_failed

:deps
rem ---------- 2. Библиотеки ----------
set "NEED_INSTALL="
if exist "%MARK%" (
    fc /b "requirements.txt" "%MARK%" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
) else (
    set "NEED_INSTALL=1"
)
if not defined NEED_INSTALL (
    "%VPY%" -c "import PySide6, cv2, PIL, numpy, openpyxl" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
)
if defined NEED_INSTALL (
    echo Устанавливаю необходимые библиотеки — при первом запуске это займет несколько минут.
    echo Нужно подключение к интернету.
    echo.
    "%VPY%" -m pip install --disable-pip-version-check --upgrade pip
    "%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Не удалось установить библиотеки. Проверьте подключение к интернету
        echo и запустите Запуск.bat еще раз.
        goto :fail
    )
    copy /y "requirements.txt" "%MARK%" >nul
    echo.
    echo Библиотеки установлены.
)

rem ---------- 3. Запуск ----------
echo Запускаю программу... Это окно можно не закрывать — оно закроется само.
"%VPY%" main.py
if errorlevel 1 goto :fail_run
exit /b 0


:find_python
set "PYEXE="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py -3"
    exit /b 0
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=python"
    exit /b 0
)
echo Не найден Python 3.10 или новее.
echo Установите Python с сайта https://www.python.org/downloads/
echo и при установке отметьте пункт «Add python.exe to PATH».
echo Затем запустите Запуск.bat еще раз.
exit /b 1


:venv_failed
echo Не удалось создать виртуальное окружение в папке:
echo %VENV%
goto :fail

:fail_run
echo.
echo Программа завершилась с ошибкой. Сообщение выше поможет понять причину.
echo Подробный журнал: %LOCALAPPDATA%\MicroPhoto\logs
goto :pause_exit

:fail
echo.
echo Программа не запущена.

:pause_exit
echo.
pause
exit /b 1
