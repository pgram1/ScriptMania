@echo off
:check
set /p Url=What is the address of the video file/playlist you want me to play? Link: 
echo Alright!
:replay
mpv "%Url%"
set /p Cond=Press e to play something else, r to replay the song or any other key to terminate: 
IF "%Cond%"=="e" (goto :check)
IF "%Cond%"=="r" (goto :replay)
PAUSE