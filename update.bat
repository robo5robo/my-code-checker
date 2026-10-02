@echo off
echo Updating the platform after git pull...
cd /d C:\proj_ise\my-code-checker
docker-compose --env-file .env.local up -d --build
echo Update complete.
