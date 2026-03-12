@echo off
REM RDP oturumunu kilitlemeden bağlantıyı kes
REM Bu sayede Chrome arka planda düzgün çalışmaya devam eder
for /f "skip=1 tokens=3" %%s in ('query user %USERNAME%') do (
    %windir%\System32\tscon.exe %%s /dest:console
)
