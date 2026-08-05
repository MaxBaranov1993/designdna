@echo off
rem Setup-скрипт для новых worktree Orca (desingaiweb). Идемпотентный, быстрый.
rem .venv и data — junction из главного worktree (не плодим копии), .env — hardlink
rem (секреты остаются в одном месте). Ничего не копируем и не ставим заново.
setlocal
set "MAIN=C:\Users\iamma\Documents\desingaiweb"
cd /d "%~dp0"

if not exist ".venv" (
  if exist "%MAIN%\.venv" ( mklink /J ".venv" "%MAIN%\.venv" >nul && echo [setup] .venv -^> junction )
)
if not exist ".env" (
  if exist "%MAIN%\.env" ( mklink /H ".env" "%MAIN%\.env" >nul && echo [setup] .env -^> hardlink )
)
if not exist "data" (
  if exist "%MAIN%\data" ( mklink /J "data" "%MAIN%\data" >nul && echo [setup] data -^> junction (общий кэш) )
)
echo [setup] готово: %cd%
endlocal
