@echo off
echo إعادة تشغيل الحاويات (بدون بناء)...
cd /d C:\proj_ise\my-code-checker
docker-compose --env-file .env.local restart
echo تمت إعادة التشغيل.
