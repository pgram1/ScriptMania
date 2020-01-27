@echo off
:check
set /p Url=What is the address of the stream's file/playlist? Link/URL: 
echo Alright!
youtube-dl -F "%Url%"
set /p Qual=What quality?(video+audio or single stream): 
:replay
mpv --ytdl-format %Qual% "%Url%"
set /p Cond=Press e to play something else, r to replay the stream or any other key to terminate: 
IF "%Cond%"=="e" (goto :check)
IF "%Cond%"=="r" (goto :replay)
PAUSE
