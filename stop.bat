@echo off
echo Stopping the platform...
cd /d C:\proj_ise\my-code-checker
docker-compose down
echo All services stopped successfully.
