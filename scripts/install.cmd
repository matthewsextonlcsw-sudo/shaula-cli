@echo off
REM ===========================================================================
REM shaula installer bootstrap for Windows cmd.exe
REM   Downloads and runs install.ps1 (the real installer).
REM Usage:  curl -L https://raw.githubusercontent.com/matthewsextonlcsw-sudo/shaula-cli/main/scripts/install.cmd -o install.cmd && install.cmd
REM ===========================================================================
setlocal
set "SHAULA_PS1=https://raw.githubusercontent.com/matthewsextonlcsw-sudo/shaula-cli/main/scripts/install.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "irm '%SHAULA_PS1%' | iex"
endlocal
