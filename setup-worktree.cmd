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
rem app/static/flow (Vite-сборка /flow) в .gitignore: копия из главного worktree,
rem чтобы /flow не давал 500 в новых worktree (наблюдение воркера W5, 2026-08-05)
if not exist "app\static\flow\index.html" (
  if exist "%MAIN%\app\static\flow\index.html" (
    xcopy /E /I /Q "%MAIN%\app\static\flow" "app\static\flow" >nul && echo [setup] /flow -^> копия Vite-сборки
  )
)
echo [setup] готово: %cd%
endlocal
