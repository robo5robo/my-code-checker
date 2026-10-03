FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# gcc/g++ لفحص صياغة C/C++ فقط (-fsyntax-only)، وcppcheck لفحص الجودة الساكن
# nodejs/npm لتحميل Monaco Editor وESLint أثناء بناء الصورة (ESLint يُستخدم وقت التشغيل لفحص JS فقط)
# لا شيء هنا يُشغّل كود الطالب فعلياً
# ملاحظة: لا نُثبّت JDK هنا عمداً — إضافته لهذا السطر سابقاً أبطلت كاش Docker
# لكل الحزم معاً وتسبّبت بإعادة تحميل ضخمة. فحص Java يعمل تلقائياً بفحص
# أساسي (توازن الأقواس) عبر analyze_generic_basic() في app.py عند غياب javac.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ cppcheck nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تحميل Monaco Editor من npm (الملفات تُنسخ إلى node_modules/monaco-editor/min)
COPY package.json .
RUN npm install --omit=dev --no-audit --no-fund

COPY . .

# تشغيل التطبيق بمستخدم غير root
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# Render يمرّر المنفذ عبر متغير البيئة PORT
EXPOSE 10000
CMD gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 60 app:app
