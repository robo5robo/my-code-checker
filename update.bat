@echo off
echo جاري تحديث المنصة بعد git pull...
cd /d C:\proj_ise\my-code-checker
docker-compose --env-file .env.local up -d --build
echo تم التحديث والتشغيل.
