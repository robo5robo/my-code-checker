@echo off
echo.
echo ====================================
echo    منصة فحص الأكواد - ISE
echo ====================================
echo.
echo جاري تشغيل الخدمات...
cd /d C:\proj_ise\my-code-checker
docker-compose --env-file .env.local up -d
echo.
echo انتظر 40 ثانية حتى تجهز Judge0...
timeout /t 40 /nobreak
echo.
echo ====================================
echo  الموقع جاهز: http://localhost:5000
echo ====================================
start http://localhost:5000
