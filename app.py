import os
import re
import ast
import uuid
import shutil
import subprocess
import json
import urllib.request
import urllib.error
from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
import google.generativeai as genai
import lizard
from radon.complexity import cc_visit, cc_rank

app = Flask(__name__)
CORS(app)

# إعداد مفتاح الذكاء الاصطناعي — من متغير البيئة GEMINI_API_KEY فقط
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Judge0: URL المحلي (فارغ = استخدام RapidAPI) والمفتاح — من متغيرات البيئة فقط
JUDGE0_API_URL = os.environ.get('JUDGE0_API_URL', '')  # مثال: http://judge0-server:2358
JUDGE0_API_KEY = os.environ.get('JUDGE0_API_KEY', '')  # مفتاح Judge0 من جانب الخادم

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_files")
os.makedirs(TEMP_DIR, exist_ok=True)

MONACO_DIR = os.path.join(BASE_DIR, 'node_modules', 'monaco-editor', 'min')
ECHARTS_DIR = os.path.join(BASE_DIR, 'node_modules', 'echarts', 'dist')
FONTS_DIR = os.path.join(BASE_DIR, 'node_modules', '@fontsource', 'ibm-plex-sans-arabic', 'files')

@app.route('/', methods=['GET'])
def home():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/health')
def health():
    return {
        "status": "ok",
        "gemini": "configured" if os.environ.get('GEMINI_API_KEY') else "missing",
        "key_preview": os.environ.get('GEMINI_API_KEY', '')[:8] + "..."
                       if os.environ.get('GEMINI_API_KEY') else "none"
    }

@app.route('/monaco/<path:filename>')
def serve_monaco(filename):
    """تقديم ملفات Monaco من المجلد المحلي، أو redirect للـ CDN إن لم تكن موجودة (fallback لـ Render)."""
    local_path = os.path.join(MONACO_DIR, filename)
    if os.path.exists(local_path):
        return send_from_directory(MONACO_DIR, filename)
    cdn = f'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/{filename}'
    return redirect(cdn, code=302)

@app.route('/echarts/<path:filename>')
def serve_echarts(filename):
    """تقديم ملف ECharts من المجلد المحلي (node_modules، بدون أي CDN خارجي)."""
    return send_from_directory(ECHARTS_DIR, filename)

@app.route('/fonts/<path:filename>')
def serve_fonts(filename):
    """تقديم ملفات خط IBM Plex Sans Arabic من المجلد المحلي (node_modules، بدون Google Fonts CDN)."""
    return send_from_directory(FONTS_DIR, filename)

# ============================================================
#  المرحلة 3 و4: فحص الجودة والتعقيد والديون التقنية (POST /analyze)
#  ملاحظة: كل هذه الأدوات فحص ساكن فقط، لا شيء هنا يُشغّل كود الطالب.
# ============================================================

ANALYZE_EXTENSIONS = {
    "python": ".py", "javascript": ".js",
    "c": ".c", "cpp": ".cpp",
    "html": ".html", "json": ".json",
    "java": ".java", "go": ".go", "rust": ".rs", "php": ".php", "ruby": ".rb",
    "csharp": ".cs", "kotlin": ".kt", "swift": ".swift", "typescript": ".ts", "bash": ".sh",
}

# فحص أمان نصي عام (regex) يُطبَّق على كل اللغات بالإضافة لأدوات الفحص الساكن الخاصة بكل لغة
SECURITY_PATTERNS = [
    (r'(api[_-]?key|secret|password|passwd|token)\s*[=:]\s*["\'][A-Za-z0-9_\-]{8,}["\']',
     "مفتاح أو كلمة مرور مكتوبة مباشرة في الكود (hardcoded secret) — استخدم متغيرات البيئة بدلاً من ذلك"),
    (r'\beval\s*\(', "استخدام eval() خطر — يُنفّذ أي نص كأنه كود برمجي"),
    (r'\bexec\s*\(', "استخدام exec() خطر — يُنفّذ أي نص كأنه كود برمجي"),
    (r'os\.system\s*\(', "استخدام os.system() قد يسمح بحقن أوامر (command injection) إن جاء الدخل من المستخدم"),
    (r'subprocess\.\w+\([^)]*shell\s*=\s*True', "استخدام subprocess مع shell=True قد يسمح بحقن أوامر"),
    (r'(SELECT|INSERT|UPDATE|DELETE)\b.{0,40}["\']?\s*\+\s*\w+', "احتمال دمج نصي لاستعلام قاعدة بيانات (SQL Injection) بدل الاستعلامات المُعامَلة (parameterized)"),
]


def scan_security_patterns(code):
    findings = []
    for pattern, message in SECURITY_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            findings.append(message)
    return findings


# مكتبات تحتاج وصولاً لجهاز فعلي (كاميرا/حساس/منفذ تسلسلي) لا تتوفر في أي بيئة تشغيل سحابية
# ملاحظة: الكود لا يُشغَّل على الخادم أصلاً (Pyodide في متصفح الطالب فقط) — هذا الفحص يمنع
# محاولة تشغيل فاشلة في المتصفح أيضاً، لأن هذه المكتبات غير متاحة في Pyodide كذلك.
# ميزة مستقبلية: دعم WebSerial/WebUSB للتواصل مع Arduino/micro:bit من المتصفح مباشرة،
# بدون تشغيل الكود الخاص بالجهاز على الخادم. تُضاف في مرحلة لاحقة عند الحاجة الفعلية من الطلاب.
HARDWARE_IMPORT_NAMES = {"cv2", "picamera", "RPi.GPIO", "RPi", "pyaudio", "serial"}


def detect_hardware_imports(code):
    """يُعيد اسم أول مكتبة جهاز حقيقي مكتشفة في الاستيرادات، أو None إن لم توجد."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in HARDWARE_IMPORT_NAMES or alias.name.split(".")[0] in HARDWARE_IMPORT_NAMES:
                    return alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module in HARDWARE_IMPORT_NAMES or node.module.split(".")[0] in HARDWARE_IMPORT_NAMES):
                return node.module
    return None


NETWORK_CALL_NAMES = {"requests.get", "requests.post", "requests.put", "requests.delete", "requests.request", "urlopen"}


def analyze_performance_python(code):
    """فئة اختيارية خامسة (أداء وكفاءة) — ملاحظات تعليمية وليست أخطاء. تظهر فقط إن انطبقت فعلاً.
    TODO: لم تُنفَّذ بعد لبقية اللغات (Go, Rust, PHP, Ruby, C#, Kotlin, Swift, TypeScript, Bash, C/C++, Java) —
    تحتاج محلل بنية مخصص لكل لغة، أو الانتقال لأداة عامة متعددة اللغات (مثل tree-sitter) لاحقاً."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    notes = []
    parent_map = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[child] = node

    def is_nested_in_loop(node):
        p = parent_map.get(node)
        while p is not None:
            if isinstance(p, (ast.For, ast.While)):
                return True
            p = parent_map.get(p)
        return False

    def loop_depth(node, depth):
        max_d = depth
        for child in ast.iter_child_nodes(node):
            d = depth + 1 if isinstance(child, (ast.For, ast.While)) else depth
            max_d = max(max_d, loop_depth(child, d))
        return max_d

    def call_name(call_node):
        f = call_node.func
        if isinstance(f, ast.Attribute):
            base = f.value.id if isinstance(f.value, ast.Name) else None
            return f"{base}.{f.attr}" if base else f.attr
        if isinstance(f, ast.Name):
            return f.id
        return None

    # 1) حلقات متداخلة بعمق 3+ (فقط عند أعلى حلقة في السلسلة، تفادياً للتكرار)
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)) and not is_nested_in_loop(node):
            depth = loop_depth(node, 1)
            if depth >= 3:
                notes.append({
                    "line": node.lineno,
                    "message": f"حلقات متداخلة بعمق {depth} مستويات — قد يبطئ الكود كثيراً مع زيادة حجم البيانات، فكّر في تحسين الخوارزمية (هيكل بيانات أنسب أو تقليل التكرار).",
                })

    # 2) استدعاء شبكة (requests/urlopen) داخل حلقة
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)) and not is_nested_in_loop(node):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    name = call_name(child)
                    if name in NETWORK_CALL_NAMES:
                        notes.append({
                            "line": child.lineno,
                            "message": "استدعاء شبكة (requests) داخل حلقة يُبطئ التنفيذ لأن كل طلب ينتظر انتهاء السابق؛ مفهوم asyncio/aiohttp يسمح بإرسال عدة طلبات بالتوازي (موضوع متقدم يستحق الاستكشاف لاحقاً).",
                        })
                        break

    # 3) دالة مستقلة تُستدعى بالتسلسل أكثر من 5 مرات متتالية
    def check_sequential(body):
        count, last_name = 1, None
        for stmt in body:
            call = None
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
            elif isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                call = stmt.value
            name = call_name(call) if call else None
            if name and name == last_name:
                count += 1
                if count == 6:
                    notes.append({
                        "line": stmt.lineno,
                        "message": f"الدالة '{name}' استُدعيت أكثر من 5 مرات متتالية — إن كانت الاستدعاءات مستقلة عن بعضها، يمكن تسريعها بـ concurrent.futures أو multiprocessing لتشغيلها بالتوازي بدل التسلسل.",
                    })
            else:
                count, last_name = 1, name

    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            check_sequential(body)

    return notes


def analyze_generic_basic(code):
    """فحص نصي أساسي للغات التي لا تملك أداة فحص مثبّتة بعد (Go, Rust, PHP, Ruby, C#, Kotlin, Swift, TypeScript, Bash).
    يتحقق فقط من توازن الأقواس. TODO: استبداله لاحقاً بأداة فحص مخصصة لكل لغة (مثل golangci-lint، clippy، phpstan...)."""
    errors = []
    pairs = {')': '(', ']': '[', '}': '{'}
    stack = []
    for i, ch in enumerate(code):
        if ch in "([{":
            stack.append((ch, code.count('\n', 0, i) + 1))
        elif ch in ")]}":
            line = code.count('\n', 0, i) + 1
            if stack and stack[-1][0] == pairs[ch]:
                stack.pop()
            else:
                errors.append({"line": line, "message": f"قوس غير متطابق: '{ch}'", "severity": "error"})
    for ch, line in stack:
        errors.append({"line": line, "message": f"قوس لم يُغلَق: '{ch}'", "severity": "error"})
    if not errors:
        errors.append({"line": 1, "message": "فحص أساسي فقط لهذه اللغة (توازن الأقواس) — لا توجد أداة فحص متقدمة مثبّتة بعد.", "severity": "warning"})
    return errors


def analyze_js_errors_eslint(code, file_path):
    """ESLint مثبَّت محلياً (node_modules) لفحص JavaScript، مع fallback للفحص النصي اليدوي إن تعذّر تشغيله."""
    eslint_bin = os.path.join(BASE_DIR, "node_modules", ".bin", "eslint")
    config_path = os.path.join(BASE_DIR, "eslint.config.js")
    if not os.path.exists(eslint_bin):
        return analyze_js_errors(code)
    try:
        result = subprocess.run(
            [eslint_bin, "--no-config-lookup", "-c", config_path, "--format", "json", file_path],
            capture_output=True, text=True, timeout=10
        )
        reports = json.loads(result.stdout) if result.stdout.strip() else []
        errors = []
        for report in reports:
            for m in report.get("messages", []):
                errors.append({
                    "line": m.get("line", 1),
                    "message": f"[{m.get('ruleId') or 'syntax'}] {m.get('message', '')}",
                    "severity": "error" if m.get("severity") == 2 else "warning",
                })
        return errors
    except Exception:
        return analyze_js_errors(code)


def analyze_java_errors(code, analyze_dir):
    """javac -Xlint لفحص صياغة Java (فحص فقط، بدون تشغيل) إن توفّر JDK في الصورة، وإلا فحص أساسي."""
    javac = "javac"
    try:
        subprocess.run([javac, "-version"], capture_output=True, timeout=5)
    except Exception:
        return analyze_generic_basic(code)

    file_path = os.path.join(analyze_dir, "Main.java")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)
    errors = []
    try:
        result = subprocess.run(
            [javac, "-Xlint:all", "-d", analyze_dir, file_path],
            capture_output=True, text=True, timeout=15
        )
        for line in (result.stderr or "").splitlines():
            m = re.match(r'^[^:]+:(\d+):\s*(error|warning):\s*(.+)$', line)
            if m:
                errors.append({"line": int(m.group(1)), "message": m.group(3), "severity": m.group(2)})
    except Exception as e:
        errors.append({"line": 1, "message": f"تعذّر تشغيل javac: {e}", "severity": "warning"})
    return errors

VOID_HTML_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


def _rank_from_value(value):
    """تصنيف حرفي A-F لقيمة تعقيد رقمية، بنفس عتبات McCabe التي يعتمدها radon."""
    if value <= 5: return "A"
    if value <= 10: return "B"
    if value <= 20: return "C"
    if value <= 30: return "D"
    if value <= 40: return "E"
    return "F"


def _complexity_label(rank):
    if rank in ("A", "B"): return "بسيط"
    if rank in ("C", "D"): return "متوسط"
    return "معقد"


def analyze_python_errors(code, file_path):
    """Ruff: فحص ساكن سريع لبايثون (أخطاء صياغة + مشاكل شائعة)."""
    errors = []
    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=json", "--stdin-filename", file_path, "-"],
            input=code, capture_output=True, text=True, timeout=10
        )
        findings = json.loads(result.stdout) if result.stdout.strip() else []
        for f in findings:
            severity = "error" if f.get("severity") == "error" else "warning"
            line = f.get("location", {}).get("row", 1)
            rule_code = f.get("code") or ""
            message = f.get("message", "")
            errors.append({
                "line": line,
                "message": f"[{rule_code}] {message}" if rule_code else message,
                "severity": severity,
            })
    except Exception as e:
        errors.append({"line": 1, "message": f"تعذّر تشغيل أداة الفحص (ruff): {e}", "severity": "warning"})
    return errors


def analyze_python_complexity(code):
    try:
        blocks = cc_visit(code)
    except Exception:
        blocks = []
    if not blocks:
        return 1, "A"
    avg = round(sum(b.complexity for b in blocks) / len(blocks), 1)
    return avg, cc_rank(avg)


def analyze_js_errors(code):
    """فحص نصي بسيط لأخطاء JavaScript الشائعة (بديل مؤقت لحين إضافة ESLint)."""
    errors = []
    pairs = {')': '(', ']': '[', '}': '{'}
    stack = []
    for i, ch in enumerate(code):
        if ch in "([{":
            stack.append((ch, code.count('\n', 0, i) + 1))
        elif ch in ")]}":
            line = code.count('\n', 0, i) + 1
            if stack and stack[-1][0] == pairs[ch]:
                stack.pop()
            else:
                errors.append({"line": line, "message": f"قوس غير متطابق: '{ch}'", "severity": "error"})
    for ch, line in stack:
        errors.append({"line": line, "message": f"قوس لم يُغلَق: '{ch}'", "severity": "error"})

    for i, line_text in enumerate(code.split('\n'), start=1):
        if re.search(r'(?<![=!<>])==(?!=)', line_text):
            errors.append({"line": i, "message": "استخدم === بدلاً من == للمقارنة الدقيقة", "severity": "warning"})
        if re.search(r'(?<![=!<>])!=(?!=)', line_text):
            errors.append({"line": i, "message": "استخدم !== بدلاً من != للمقارنة الدقيقة", "severity": "warning"})
        if re.search(r'\bvar\b', line_text):
            errors.append({"line": i, "message": "استخدم let أو const بدلاً من var", "severity": "warning"})
    return errors


def analyze_c_cpp_errors(file_path, language):
    """Cppcheck لفحص الجودة + gcc/g++ -fsyntax-only لأخطاء الصياغة (فحص فقط، بدون تشغيل)."""
    errors = []
    try:
        result = subprocess.run(
            ["cppcheck", "--enable=warning,style,performance,portability",
             "--template={line}::{severity}::{message}", "--quiet", file_path],
            capture_output=True, text=True, timeout=10
        )
        for line in (result.stderr or "").splitlines():
            parts = line.split("::", 2)
            if len(parts) == 3:
                line_no_raw, sev, msg = parts
                try:
                    line_no = int(line_no_raw)
                except ValueError:
                    line_no = 1
                errors.append({
                    "line": line_no,
                    "message": msg,
                    "severity": "error" if sev == "error" else "warning",
                })
    except Exception as e:
        errors.append({"line": 1, "message": f"تعذّر تشغيل أداة الفحص (cppcheck): {e}", "severity": "warning"})

    compiler = "gcc" if language == "c" else "g++"
    try:
        result = subprocess.run([compiler, "-fsyntax-only", file_path], capture_output=True, text=True, timeout=10)
        for line in (result.stderr or "").splitlines():
            m = re.match(r'^[^:]+:(\d+):\d+:\s*(error|warning):\s*(.+)$', line)
            if m:
                errors.append({"line": int(m.group(1)), "message": m.group(3), "severity": m.group(2)})
    except Exception:
        pass
    return errors


def analyze_lizard_complexity(file_path):
    try:
        result = lizard.analyze_file(file_path)
        funcs = result.function_list
        if not funcs:
            return 1, "A"
        avg = round(sum(f.cyclomatic_complexity for f in funcs) / len(funcs), 1)
        return avg, _rank_from_value(avg)
    except Exception:
        return 1, "A"


def analyze_html_errors(code):
    """تحقق بسيط من توازن وسوم HTML المفتوحة والمغلقة (ليس فحصاً كاملاً للمعايير)."""
    errors = []
    stack = []
    tag_re = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>')
    for m in tag_re.finditer(code):
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3)
        line = code.count('\n', 0, m.start()) + 1
        if name in VOID_HTML_TAGS or name == "!doctype" or attrs.rstrip().endswith('/'):
            continue
        if closing:
            found_at = None
            for j in range(len(stack) - 1, -1, -1):
                if stack[j][0] == name:
                    found_at = j
                    break
            if found_at is None:
                errors.append({"line": line, "message": f"وسم إغلاق بلا وسم فتح مطابق: </{name}>", "severity": "error"})
            else:
                # أي وسوم متداخلة بين المطابقة وأعلى المكدس لم تُغلَق قبل هذا الوسم
                for skipped_name, skipped_line in stack[found_at + 1:]:
                    errors.append({"line": skipped_line, "message": f"وسم لم يُغلَق قبل </{name}>: <{skipped_name}>", "severity": "error"})
                del stack[found_at:]
        else:
            stack.append((name, line))
    for name, line in stack:
        errors.append({"line": line, "message": f"وسم لم يُغلَق: <{name}>", "severity": "error"})
    return errors


def analyze_json_errors(code):
    errors = []
    try:
        json.loads(code)
    except json.JSONDecodeError as e:
        errors.append({"line": e.lineno, "message": e.msg, "severity": "error"})
    except Exception as e:
        errors.append({"line": 1, "message": str(e), "severity": "error"})
    return errors


def count_lines(code, language):
    """عدّ تقريبي لأسطر الكود والتعليقات والأسطر الفارغة (تخمين بحسب نوع اللغة)."""
    lines = code.splitlines()
    total = len(lines)
    comments = 0
    blanks = 0
    in_block = False
    block_end = None
    for raw in lines:
        line = raw.strip()
        if not line:
            blanks += 1
            continue
        if in_block:
            comments += 1
            if block_end in line:
                in_block = False
            continue
        if language == "python" and line.startswith('#'):
            comments += 1
            continue
        if language in ("javascript", "c", "cpp"):
            if line.startswith('//'):
                comments += 1
                continue
            if line.startswith('/*'):
                comments += 1
                if '*/' not in line[2:]:
                    in_block, block_end = True, '*/'
                continue
        if language == "html" and line.startswith('<!--'):
            comments += 1
            if '-->' not in line[4:]:
                in_block, block_end = True, '-->'
            continue
    return {"total": total, "code": max(total - comments - blanks, 0), "comments": comments}


def compute_score(errors):
    score = 10
    for e in errors:
        score -= 2 if e["severity"] == "error" else 1
    return max(0, min(10, score))


def compute_summary(errors):
    n_err = sum(1 for e in errors if e["severity"] == "error")
    n_warn = sum(1 for e in errors if e["severity"] == "warning")
    if not n_err and not n_warn:
        return ""
    parts = []
    if n_err: parts.append(f"{n_err} خطأ")
    if n_warn: parts.append(f"{n_warn} تحذير")
    return "تم العثور على " + " و".join(parts)


def compute_fix_priority(errors, complexity_value):
    """أولوية إصلاح تقريبية للطالب: عالية عند وجود أخطاء فعلية، متوسطة عند
    وجود تحذيرات فقط أو تعقيد زائد، ومنخفضة غير ذلك."""
    n_err = sum(1 for e in errors if e["severity"] == "error")
    n_warn = sum(1 for e in errors if e["severity"] == "warning")
    if n_err:
        return {"label": "عالية", "level": "high"}
    if n_warn or complexity_value > 7:
        return {"label": "متوسطة", "level": "medium"}
    return {"label": "منخفضة", "level": "low"}


def _call_openai_compat(endpoint, api_key, model, messages, max_tokens=700):
    """استدعاء API متوافق مع OpenAI عبر urllib (Groq, Cerebras, إلخ)."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "groq-python/0.13.0",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def _parse_ai_json(text, defaults=None):
    """استخرج JSON من رد الذكاء الاصطناعي؛ إن فشل التحليل أعد النص داخل القيم الافتراضية."""
    try:
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    base = defaults.copy() if defaults else {"fixed_code": None}
    base["explanation"] = text
    return base


def _call_ai_chain(messages, max_tokens=700):
    """يجرّب المزوّدين بالترتيب ويُعيد أول رد نصي ناجح: Groq ← Cerebras ← Claude ← Gemini. None إن فشل الجميع."""
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            return _call_openai_compat(
                "https://api.groq.com/openai/v1/chat/completions",
                groq_key, "openai/gpt-oss-120b", messages, max_tokens
            )
        except Exception:
            pass

    cerebras_key = os.environ.get("CEREBRAS_API_KEY")
    if cerebras_key:
        try:
            return _call_openai_compat(
                "https://api.cerebras.ai/v1/chat/completions",
                cerebras_key, "llama3.1-8b", messages, max_tokens
            )
        except Exception:
            pass

    claude_key = os.environ.get("CLAUDE_API_KEY")
    if claude_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=claude_key)
            msg = client.messages.create(
                model="claude-haiku-20240307", max_tokens=max_tokens, messages=messages,
            )
            return msg.content[0].text.strip()
        except Exception:
            pass

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(
                messages[0]["content"], request_options={"timeout": 15}
            )
            return response.text.strip()
        except Exception:
            pass

    return None


# نقطة توسعة: أضف هنا endpoint أي مزوّد OpenAI-compatible جديد (مثل fireworks، together...)
PROVIDER_ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
}


def call_ai_model(role, messages, max_tokens=700):
    """نموذج مخصَّص حسب الدور: role='text' لشرح/تحليل تعليمي، role='code' لتوليد كود فقط.
    يقرأ {ROLE}_MODEL_PROVIDER / _NAME / _API_KEY من البيئة. عند غياب أي منها أو فشل
    الاستدعاء، يتراجع لسلسلة المزوّدين العامة _call_ai_chain() (توافق مع الإعداد القديم)."""
    prefix = role.upper() + "_MODEL_"
    provider = os.environ.get(prefix + "PROVIDER")
    model_name = os.environ.get(prefix + "NAME")
    api_key = os.environ.get(prefix + "API_KEY")

    if provider and model_name and api_key:
        endpoint = PROVIDER_ENDPOINTS.get(provider)
        if endpoint:
            try:
                return _call_openai_compat(endpoint, api_key, model_name, messages, max_tokens)
            except Exception:
                pass

    return _call_ai_chain(messages, max_tokens)


def _extract_code_block(text):
    """يستخرج الكود من رد قد يُحيطه AI بسياج Markdown ```lang ... ```، وإلا يُعيد النص كما هو."""
    m = re.search(r'```[a-zA-Z0-9]*\n([\s\S]*?)```', text)
    return m.group(1).strip() if m else text.strip()


def get_ai_explanation(language, errors, score, complexity, code="", security_issues=None, performance_notes=None):
    """شرح + كود مصحَّح عبر نموذجين منفصلين: TEXT_MODEL للشرح والتحليل، CODE_MODEL لتوليد fixed_code فقط."""
    n_err = sum(1 for e in errors if e["severity"] == "error")
    n_warn = sum(1 for e in errors if e["severity"] == "warning")
    errors_text = "\n".join(f"- سطر {e['line']}: {e['message']}" for e in errors[:6]) if errors else "لا توجد أخطاء"
    security_text = "\n".join(f"- {s}" for s in security_issues) if security_issues else "لا توجد ملاحظات أمان من الفحص الساكن"
    performance_text = "\n".join(f"- سطر {p['line']}: {p['message']}" for p in performance_notes) if performance_notes else ""

    text_prompt = (
        f"أنت مساعد تعليمي لطلاب البرمجة. فيما يلي كود بلغة {language} ونتائج فحصه الساكن:\n\n"
        f"الكود:\n```\n{code[:1200]}\n```\n\n"
        f"الأخطاء والتحذيرات ({n_err} خطأ، {n_warn} تحذير):\n{errors_text}\n\n"
        f"ملاحظات أمان أولية من الفحص الساكن:\n{security_text}\n\n"
        + (f"ملاحظات أداء أولية من الفحص الساكن:\n{performance_text}\n\n" if performance_text else "")
        + "أعد ردك بصيغة JSON فقط بهذا الشكل (بدون أي نص خارج JSON، ولا تضع حقل كود هنا):\n"
        '{"explanation": "شرح المشكلة الرئيسية بجملتين", '
        '"security_notes": "ملاحظات أمان إضافية بجملة أو جملتين، أو null إن لم توجد مخاطر", '
        '"improvements": ["نصيحة تحسين 1", "نصيحة تحسين 2"], '
        '"tip": "نصيحة أسلوب عامة"'
        + (', "performance_note": "تبدأ حرفياً بـ: 💡 ملاحظة تعليمية (ليست خطأ): ثم اشرح الملاحظة ببساطة ولطف (هذا ليس خطأ في الكود بل فرصة تعلّم لمفهوم متقدم)"' if performance_text else "")
        + "}"
    )
    text_result = call_ai_model("text", [{"role": "user", "content": text_prompt}])
    if not text_result:
        return None
    defaults = {"security_notes": None, "improvements": [], "tip": None}
    if performance_text:
        defaults["performance_note"] = None
    result = _parse_ai_json(text_result, defaults=defaults)

    code_prompt = (
        f"أصلح كل الأخطاء في الكود التالي المكتوب بلغة {language}. "
        "أعد الكود المصحَّح فقط، كاملاً ومنسَّقاً، بدون أي شرح أو نص إضافي خارج الكود نفسه:\n\n"
        f"```\n{code[:1500]}\n```"
    )
    code_result = call_ai_model("code", [{"role": "user", "content": code_prompt}], max_tokens=1200)
    result["fixed_code"] = _extract_code_block(code_result) if code_result else None
    return result


@app.route('/analyze', methods=['POST'])
def analyze():
    """فحص ذكي موحّد (دمج الفحص الساكن والتحليل الشامل السابقين) لكل اللغات المتاحة في المنصة.
    4 فئات: أخطاء برمجية، ثغرات أمنية، جودة الأسلوب، التعقيد."""
    data = request.get_json()
    if not data or 'code' not in data or 'language' not in data:
        return jsonify({"error": "البيانات المرسلة غير مكتملة"}), 400

    code = data['code']
    language = data['language'].lower()
    if language not in ANALYZE_EXTENSIONS:
        return jsonify({"error": "هذه اللغة غير مدعومة حالياً للفحص"}), 400

    # ملاحظة (لا حظر): الفحص الساكن مفيد حتى لو احتاج الكود جهازاً حقيقياً لاحقاً —
    # نُبلغ الطالب فقط، ولا نُلغي نتائج Ruff/الأمان/التعقيد
    hardware_lib = detect_hardware_imports(code) if language == "python" else None
    hardware_notice = (
        f"⚠️ ملاحظة: هذا الكود يستخدم مكتبة ({hardware_lib}) تحتاج جهازاً حقيقياً (كاميرا/حساس) لتعمل فعلياً. "
        "الفحص النصي للكود يعمل بشكل طبيعي، لكن التشغيل الفعلي يحتاج جهازك الشخصي."
    ) if hardware_lib else None

    analyze_dir = os.path.join(TEMP_DIR, f"analyze_{uuid.uuid4().hex}")
    os.makedirs(analyze_dir, exist_ok=True)
    file_path = os.path.join(analyze_dir, f"code{ANALYZE_EXTENSIONS[language]}")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)

    try:
        if language == "python":
            errors = analyze_python_errors(code, file_path)
            complexity_value, complexity_rank = analyze_python_complexity(code)
        elif language == "javascript":
            errors = analyze_js_errors_eslint(code, file_path)
            complexity_value, complexity_rank = analyze_lizard_complexity(file_path)
        elif language in ("c", "cpp"):
            errors = analyze_c_cpp_errors(file_path, language)
            complexity_value, complexity_rank = analyze_lizard_complexity(file_path)
        elif language == "html":
            errors = analyze_html_errors(code)
            complexity_value, complexity_rank = 1, "A"
        elif language == "json":
            errors = analyze_json_errors(code)
            complexity_value, complexity_rank = 1, "A"
        elif language == "java":
            errors = analyze_java_errors(code, analyze_dir)
            complexity_value, complexity_rank = analyze_lizard_complexity(file_path)
        else:  # Go, Rust, PHP, Ruby, C#, Kotlin, Swift, TypeScript, Bash — فحص أساسي حالياً
            errors = analyze_generic_basic(code)
            complexity_value, complexity_rank = analyze_lizard_complexity(file_path)

        # الأخطاء الحرجة أولاً
        errors.sort(key=lambda e: 0 if e["severity"] == "error" else 1)

        security_issues = scan_security_patterns(code)
        # فئة خامسة اختيارية: الأداء والكفاءة (Python فقط حالياً؛ TODO لبقية اللغات في analyze_performance_python)
        performance_notes = analyze_performance_python(code) if language == "python" else []

        score = compute_score(errors)
        complexity_obj = {
            "score": complexity_rank,
            "value": complexity_value,
            "label": _complexity_label(complexity_rank),
        }
        ai_explanation = get_ai_explanation(
            language, errors, score, complexity_obj, code=code,
            security_issues=security_issues, performance_notes=performance_notes,
        )

        return jsonify({
            "errors": errors,
            "score": score,
            "summary": compute_summary(errors),
            "complexity": complexity_obj,
            "fix_priority": compute_fix_priority(errors, complexity_value),
            "lines": count_lines(code, language),
            "security_issues": security_issues,
            "performance_notes": performance_notes,
            "hardware_notice": hardware_notice,
            "ai_explanation": ai_explanation,
        })
    finally:
        if os.path.exists(analyze_dir):
            shutil.rmtree(analyze_dir, ignore_errors=True)


# ============================================================
#  زر "تحليل ذكي": استخراج بنية الكود (دوال/كلاسات/استدعاءات)
#  لرسمها كشجرة تفاعلية + شرح تعليمي بالذكاء الاصطناعي (فهم، لا أخطاء).
# ============================================================

def extract_structure_python(code):
    """ast المدمجة: دوال، كلاسات، استيرادات، واستدعاءات الدوال داخل بعضها."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"nodes": [], "edges": []}

    nodes = []
    edges = []
    scope_stack = []

    class Visitor(ast.NodeVisitor):
        def _import(self, node):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                nodes.append({"id": name, "type": "import", "line": node.lineno})

        def visit_Import(self, node):
            self._import(node)
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            self._import(node)
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            nodes.append({"id": node.name, "type": "class", "line": node.lineno, "level": len(scope_stack)})
            scope_stack.append(node.name)
            self.generic_visit(node)
            scope_stack.pop()

        def _func(self, node):
            nodes.append({"id": node.name, "type": "function", "line": node.lineno, "level": len(scope_stack)})
            scope_stack.append(node.name)
            self.generic_visit(node)
            scope_stack.pop()

        visit_FunctionDef = _func
        visit_AsyncFunctionDef = _func

        def visit_Call(self, node):
            if scope_stack:
                callee = None
                if isinstance(node.func, ast.Name):
                    callee = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    callee = node.func.attr
                if callee:
                    edges.append({"source": scope_stack[-1], "target": callee})
            self.generic_visit(node)

    Visitor().visit(tree)
    known = {n["id"] for n in nodes if n["type"] in ("function", "class")}
    seen = set()
    uniq_edges = []
    for e in edges:
        if e["target"] in known and e["source"] != e["target"] and (e["source"], e["target"]) not in seen:
            seen.add((e["source"], e["target"]))
            uniq_edges.append(e)
    return {"nodes": nodes, "edges": uniq_edges}


def _js_body_text(code, start):
    brace_pos = code.find('{', start)
    if brace_pos == -1:
        return ""
    depth = 0
    for i in range(brace_pos, len(code)):
        if code[i] == '{':
            depth += 1
        elif code[i] == '}':
            depth -= 1
            if depth == 0:
                return code[brace_pos:i + 1]
    return code[brace_pos:]


def extract_structure_js(code):
    """استخراج مبسّط بـ regex لدوال وكلاسات JavaScript/TypeScript واستدعاءاتها."""
    patterns = [
        (r'function\s+([A-Za-z_$][\w$]*)\s*\(', "function"),
        (r'class\s+([A-Za-z_$][\w$]*)', "class"),
        (r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>', "function"),
        (r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*function', "function"),
    ]
    matches = []
    for pat, typ in patterns:
        for m in re.finditer(pat, code):
            matches.append((m.start(), m.group(1), typ))
    matches.sort(key=lambda t: t[0])

    nodes, seen = [], set()
    for start, name, typ in matches:
        if name in seen:
            continue
        seen.add(name)
        nodes.append({"id": name, "type": typ, "line": code.count('\n', 0, start) + 1, "level": 0, "_start": start})

    known = {n["id"] for n in nodes}
    edges, seen_edges = [], set()
    for n in nodes:
        body = _js_body_text(code, n["_start"])
        for other in known:
            if other == n["id"]:
                continue
            if re.search(r'\b' + re.escape(other) + r'\s*\(', body) and (n["id"], other) not in seen_edges:
                seen_edges.add((n["id"], other))
                edges.append({"source": n["id"], "target": other})
    for n in nodes:
        n.pop("_start", None)
    return {"nodes": nodes, "edges": edges}


GENERIC_FUNC_PATTERNS = {
    "go": r'func\s+([A-Za-z_]\w*)\s*\(',
    "rust": r'fn\s+([A-Za-z_]\w*)\s*\(',
    "php": r'function\s+([A-Za-z_]\w*)\s*\(',
    "ruby": r'def\s+([A-Za-z_]\w*[?!]?)',
    "kotlin": r'fun\s+([A-Za-z_]\w*)\s*\(',
    "swift": r'func\s+([A-Za-z_]\w*)\s*\(',
    "bash": r'(?:function\s+)?([A-Za-z_]\w*)\s*\(\)\s*\{',
    # Java/C#: تطابق توقيع دالة عام قبل قوس معقوص — تخمين نصي، قد يُغفل حالات نادرة
    "java": r'(?:public|private|protected|static|final|\s)+[\w<>\[\],\s]+?\s([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{',
    "csharp": r'(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{',
}
GENERIC_SKIP_NAMES = {"if", "for", "while", "switch", "catch", "else", "do"}


def extract_structure_generic(code, language):
    """فحص نصي أساسي لأسماء الدوال لبقية اللغات (TODO: استبداله بأداة تحليل بنية مخصصة لكل لغة لاحقاً)."""
    pattern = GENERIC_FUNC_PATTERNS.get(language)
    if not pattern:
        return {"nodes": [], "edges": []}

    nodes, seen = [], set()
    for m in re.finditer(pattern, code):
        name = m.group(1)
        if name in seen or name in GENERIC_SKIP_NAMES:
            continue
        seen.add(name)
        nodes.append({"id": name, "type": "function", "line": code.count('\n', 0, m.start()) + 1, "level": 0})

    nodes.sort(key=lambda n: n["line"])
    lines = code.split('\n')
    edges, seen_edges = [], set()
    for i, n in enumerate(nodes):
        end_line = nodes[i + 1]["line"] if i + 1 < len(nodes) else len(lines) + 1
        body = "\n".join(lines[n["line"]:end_line - 1])
        for other in seen:
            if other == n["id"]:
                continue
            if re.search(r'\b' + re.escape(other) + r'\s*\(', body) and (n["id"], other) not in seen_edges:
                seen_edges.add((n["id"], other))
                edges.append({"source": n["id"], "target": other})
    return {"nodes": nodes, "edges": edges}


def extract_code_structure(language, code):
    if language == "python":
        return extract_structure_python(code)
    if language in ("javascript", "typescript"):
        return extract_structure_js(code)
    return extract_structure_generic(code, language)


def get_ai_structure_explanation(language, code, structure):
    """شرح تعليمي لفهم الكود (لا أخطاء ولا تحسينات) — برومبت مختلف تماماً عن الفحص الذكي."""
    node_summary = ", ".join(f"{n['id']} (سطر {n['line']})" for n in structure["nodes"][:15]) or "لا توجد دوال واضحة"
    prompt = (
        f"اشرح للطالب كيف يعمل هذا الكود المكتوب بلغة {language} خطوة بخطوة بلغة عربية مبسطة ومشجعة. "
        "اذكر ماذا يفعل البرنامج عموماً بجملتين، ثم اشرح كل دالة أو جزء مهم بترتيب منطقي للفهم (لا بترتيب الأسطر)، "
        "مع ذكر سطر البداية لكل جزء. لا تذكر أخطاء أو تحسينات، فقط افهم واشرح.\n\n"
        f"الأجزاء المكتشفة: {node_summary}\n\n"
        f"الكود:\n```\n{code[:1500]}\n```\n\n"
        "أعد ردك بصيغة JSON فقط بهذا الشكل (بدون أي نص خارج JSON):\n"
        '{"overview": "نظرة عامة بجملتين", '
        '"sections": [{"title": "اسم الجزء", "line": رقم_البداية, "explanation": "شرح مبسط"}]}'
    )
    messages = [{"role": "user", "content": prompt}]
    text = call_ai_model("text", messages, max_tokens=900)
    if text:
        return _parse_ai_json(text, defaults={"sections": []})
    return None


@app.route('/explain', methods=['POST'])
def explain():
    data = request.get_json()
    if not data or 'code' not in data or 'language' not in data:
        return jsonify({"error": "البيانات المرسلة غير مكتملة"}), 400

    code = data['code']
    language = data['language'].lower()
    structure = extract_code_structure(language, code)
    ai_explanation = get_ai_structure_explanation(language, code, structure)

    return jsonify({
        "structure": structure,
        "ai_explanation": ai_explanation,
    })


@app.route('/judge0-status')
def judge0_status():
    """هل يوجد مفتاح Judge0 على الخادم (docker-compose المحلي)؟"""
    return jsonify({"server_key": bool(JUDGE0_API_KEY)})


@app.route('/run-judge0', methods=['POST'])
def run_judge0():
    """بروكسي آمن لـ Judge0 — يدعم Judge0 المحلي (JUDGE0_API_URL) أو RapidAPI."""
    data = request.get_json()
    if not data or 'code' not in data or 'language_id' not in data:
        return jsonify({"error": "البيانات المرسلة غير مكتملة"}), 400

    # مفتاح الخادم يأخذ الأولوية، ثم مفتاح المتصفح
    api_key = JUDGE0_API_KEY or request.headers.get("X-Judge0-Key", "").strip()
    if not api_key:
        return jsonify({
            "error": "judge0_not_configured",
            "message": "أضف مفتاح Judge0 لتفعيل هذه اللغة"
        })

    # وضع محلي (JUDGE0_API_URL مضبوط) أم RapidAPI
    if JUDGE0_API_URL:
        url = f"{JUDGE0_API_URL.rstrip('/')}/submissions?wait=true"
        headers = {"Content-Type": "application/json", "X-Judge0-Key": api_key}
    else:
        url = "https://judge0-ce.p.rapidapi.com/submissions?wait=true"
        headers = {
            "Content-Type": "application/json",
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": "judge0-ce.p.rapidapi.com"
        }

    payload = json.dumps({
        "source_code": data["code"],
        "language_id": int(data["language_id"]),
        "stdin": data.get("stdin", "")
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return jsonify(result)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return jsonify({
                "error": "judge0_key_invalid",
                "message": "مفتاح Judge0 غير صالح أو منتهي — يُرجى إدخال مفتاح جديد."
            })
        return jsonify({"error": f"HTTP {e.code}", "message": e.read().decode("utf-8", errors="replace")})
    except Exception as e:
        return jsonify({"error": "judge0_error", "message": str(e)})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
