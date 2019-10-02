@echo off
:check
set /p Url=What is the address of the video file/playlist you want me to play? Link: 
echo Alright!
youtube-dl -F "%Url%"
set /p Qual=What quality? : 
:replay
mpv --ytdl-format %Qual% "%Url%"
set /p Cond=Press e to play something else, r to replay the song or any other key to terminate: 
IF "%Cond%"=="e" (goto :check)
IF "%Cond%"=="r" (goto :replay)
PAUSE