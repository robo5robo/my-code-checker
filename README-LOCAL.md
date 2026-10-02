# التشغيل المحلي على Windows — منصة فحص الأكواد ISE

## المتطلبات

- **Docker Desktop** مثبَّت وشغّال على Windows
- **Git** لتحميل المشروع

---

## خطوات التشغيل لأول مرة

### 1. حمّل المشروع

```bat
git clone https://github.com/robo5robo/my-code-checker.git C:\proj_ise\my-code-checker
cd C:\proj_ise\my-code-checker
```

### 2. أضف مفاتيح الذكاء الاصطناعي

افتح ملف `.env.local` وضع مفاتيحك (مفتاح Groq كافٍ للبدء):

```
GROQ_API_KEY=gsk_...مفتاحك_من_console.groq.com
CEREBRAS_API_KEY=          # اختياري
GEMINI_API_KEY=            # اختياري
```

> إذا تركت الكل فارغاً تعمل المنصة بدون التحليل بالذكاء الاصطناعي فقط.

### 3. شغّل المنصة

```bat
start.bat
```

ينتظر السكريبت 40 ثانية تلقائياً حتى تجهز Judge0، ثم يفتح المتصفح.

---

## الاستخدام اليومي

| الأمر | متى تستخدمه | يبني الصورة؟ |
|---|---|---|
| `start.bat` | التشغيل الأول أو التشغيل العادي | لا (يبني تلقائياً إن لم تكن الصورة موجودة) |
| `restart.bat` | بعد `git pull` أو أي تعديل على `app.py`/`index.html` | لا (يقرأ الملفات مباشرة) |
| `update.bat` | عند تغيير `requirements.txt` أو `Dockerfile` أو إضافة مكتبة جديدة | **نعم** |
| `stop.bat` | إيقاف كل الخدمات | — |

> **القاعدة الجديدة:** بعد أي `git pull` → `restart.bat` يكفي. فقط عند تغيير المكتبات أو Dockerfile → `update.bat`.

---

## البنية التقنية

```
http://localhost:5000        ← منصة الطالب (Flask)
http://localhost:2358        ← Judge0 API (داخلي)
```

| الخدمة | الصورة | الغرض |
|---|---|---|
| `my-code-checker` | بناء محلي | خادم Flask + الواجهة |
| `judge0-server` | judge0/judge0:1.13.1 | تنفيذ الأكواد بأمان |
| `judge0-workers` | judge0/judge0:1.13.1 | معالجة طوابير التشغيل |
| `ise-redis` | redis:7-alpine | طابور المهام |
| `ise-postgres` | postgres:16-alpine | قاعدة بيانات Judge0 |

---

## اللغات المدعومة

| اللغة | يحتاج Judge0؟ |
|---|---|
| Python | لا (يعمل في المتصفح عبر Pyodide) |
| JavaScript | لا (Web Worker معزول) |
| C / C++ | نعم (Judge0 محلي — تلقائي) |
| HTML / JSON | لا (فحص فقط) |
| Java, Go, Rust, PHP, Ruby | نعم (Judge0 محلي — تلقائي) |
| C#, Kotlin, Swift, TypeScript, Bash | نعم (Judge0 محلي — تلقائي) |

> في الوضع المحلي **لا تحتاج مفتاح RapidAPI**؛ كل اللغات تعمل تلقائياً.

---

## استكشاف الأخطاء

**المنصة لا تفتح؟**
```bat
docker-compose logs my-code-checker
```

**Judge0 لا يعمل؟**
```bat
docker-compose logs judge0-server
```

**تطبيق تحديثات الكود بعد git pull:**
```bat
update.bat
```

**حذف كل البيانات والبدء من جديد:**
```bat
docker-compose down -v
start.bat
```
