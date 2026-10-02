@echo off
echo.
echo ====================================
echo    ISE Code Checker Platform
echo ====================================
echo.
echo Starting services...
cd /d C:\proj_ise\my-code-checker
docker-compose --env-file .env.local up -d
echo.
echo Waiting 40 seconds for Judge0 to be ready...
timeout /t 40 /nobreak
echo.
echo ====================================
echo  Site ready: http://localhost:5000
echo ====================================
start http://localhost:5000
