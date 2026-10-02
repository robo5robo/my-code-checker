@echo off
echo Restarting containers (no build)...
cd /d C:\proj_ise\my-code-checker
docker-compose --env-file .env.local restart
echo Restart complete.
