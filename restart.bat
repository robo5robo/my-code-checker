@echo off
echo جاري إعادة تشغيل المنصة...
cd /d C:\proj_ise\my-code-checker
docker-compose down
docker-compose --env-file .env.local up -d
echo تمت إعادة التشغيل.
