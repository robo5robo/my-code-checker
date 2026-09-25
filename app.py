import os
import re
import uuid
import subprocess
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import google.generativeai as genai
import lizard
from radon.complexity import cc_visit, cc_rank

app = Flask(__name__)
CORS(app)

# إعداد مفتاح الذكاء الاصطناعي (يمكنك الحصول على مفتاح مجاني من Google AI Studio)
# للمطوّر محلياً، يمكنك وضعه مباشرة هنا للتجربة التعليمية
# اترك السطر هكذا تماماً ولا تضع مفتاحك الحقيقي هنا
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_files")
os.makedirs(TEMP_DIR, exist_ok=True)

MONACO_DIR = os.path.join(BASE_DIR, 'node_modules', 'monaco-editor', 'min')

@app.route('/', methods=['GET'])
def home():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/monaco/<path:filename>')
def serve_monaco(filename):
    """تقديم ملفات Monaco Editor من المجلد المحلي (لا يوجد CDN خارجي)."""
    return send_from_directory(MONACO_DIR, filename)

# ============================================================
#  المرحلة 3 و4: فحص الجودة والتعقيد والديون التقنية (POST /analyze)
#  ملاحظة: كل هذه الأدوات فحص ساكن فقط، لا شيء هنا يُشغّل كود الطالب.
# ============================================================

ANALYZE_EXTENSIONS = {
    "python": ".py", "javascript": ".js",
    "c": ".c", "cpp": ".cpp",
    "html": ".html", "json": ".json",
}

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
        return "لم يُعثر على أي أخطاء أو تحذيرات. الكود سليم ✅"
    parts = []
    if n_err: parts.append(f"{n_err} خطأ")
    if n_warn: parts.append(f"{n_warn} تحذير")
    return "تم العثور على " + " و".join(parts)


def compute_technical_debt(errors, complexity_value):
    """تقدير تقريبي مستوحى من فكرة SQALE: دقائق لكل خطأ/تحذير + عامل للتعقيد الزائد."""
    n_err = sum(1 for e in errors if e["severity"] == "error")
    n_warn = sum(1 for e in errors if e["severity"] == "warning")
    minutes = n_err * 3 + n_warn * 1 + max(0, round(complexity_value) - 5)
    if minutes == 0: return "0 دقيقة"
    if minutes == 1: return "دقيقة واحدة"
    if minutes == 2: return "دقيقتان"
    if minutes <= 10: return f"{minutes} دقائق"
    return f"{minutes} دقيقة"


@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    if not data or 'code' not in data or 'language' not in data:
        return jsonify({"error": "البيانات المرسلة غير مكتملة"}), 400

    code = data['code']
    language = data['language'].lower()
    if language not in ANALYZE_EXTENSIONS:
        return jsonify({"error": "هذه اللغة غير مدعومة حالياً للفحص"}), 400

    file_path = os.path.join(TEMP_DIR, f"analyze_{uuid.uuid4().hex}{ANALYZE_EXTENSIONS[language]}")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)

    try:
        if language == "python":
            errors = analyze_python_errors(code, file_path)
            complexity_value, complexity_rank = analyze_python_complexity(code)
        elif language == "javascript":
            errors = analyze_js_errors(code)
            complexity_value, complexity_rank = analyze_lizard_complexity(file_path)
        elif language in ("c", "cpp"):
            errors = analyze_c_cpp_errors(file_path, language)
            complexity_value, complexity_rank = analyze_lizard_complexity(file_path)
        elif language == "html":
            errors = analyze_html_errors(code)
            complexity_value, complexity_rank = 1, "A"
        else:  # json
            errors = analyze_json_errors(code)
            complexity_value, complexity_rank = 1, "A"

        return jsonify({
            "errors": errors,
            "score": compute_score(errors),
            "summary": compute_summary(errors),
            "complexity": {
                "score": complexity_rank,
                "value": complexity_value,
                "label": _complexity_label(complexity_rank),
            },
            "technical_debt": compute_technical_debt(errors, complexity_value),
            "lines": count_lines(code, language),
        })
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.route('/api/check-code', methods=['POST'])
def check_code():
    data = request.get_json()
    if not data or 'code' not in data or 'language' not in data:
        return jsonify({"error": "البيانات المرسلة غير مكتملة"}), 400
    
    code_content = data['code']
    language = data['language'].lower()
    
    extensions = {"python": "temp.py", "c": "temp.c", "cpp": "temp.cpp", "javascript": "temp.js"}
    if language not in extensions:
        return jsonify({"error": "هذه اللغة غير مدعومة حالياً"}), 400
        
    file_path = os.path.join(TEMP_DIR, extensions[language])
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code_content)
        
    try:
        raw_report = ""
        # 1. تشغيل أدوات الفحص الساكن والمترجمات وجلب التقارير الجافة
        if language == "python":
            result = subprocess.run(["pylint", "--errors-only", file_path], capture_output=True, text=True, timeout=5)
            raw_report = result.stdout if result.stdout else "كود بايثون سليم نحوياً."
        elif language in ["c", "cpp"]:
            compiler = "gcc" if language == "c" else "g++"
            result = subprocess.run([compiler, "-fsyntax-only", file_path], capture_output=True, text=True, timeout=5)
            raw_report = result.stderr if result.stderr else "الكود متوافق مع معايير المترجم العالَمية."
        elif language == "javascript":
            # لا توجد أداة فحص ساكن لـ JavaScript على الخادم حالياً، والكود لا يُشغَّل هنا أبداً
            raw_report = "لا توجد أداة فحص ساكن لـ JavaScript حالياً؛ التحليل يعتمد على الذكاء الاصطناعي فقط."

        # 2. استدعاء المعلم الذكي (AI) لتحليل الأخطاء والخدمات المتقدمة
        model = genai.GenerativeModel('gemini-pro')
        
        prompt = f"""
        أنت محرك فحص أكواد احترافي ومعلم برمجية لطلاب الجامعات.
        قم بتحليل الكود التالي المكتوب بلغة ({language}) بناءً على تقرير الخطأ الجاف هذا: "{raw_report}".
        
        أريدك أن تعيد لي الإجابة بتنسيق JSON حصراً وبالمفاتيح التالية باللغة العربية:
        {{
            "error_title": "عنوان الخطأ بشكل مبسط ومفهوم للطالب",
            "explanation": "شرح حقيقي وتفصيلي ومبسط جداً للسبب الذي أدى للخطأ برمجياً وماذا يحدث في الخلفية",
            "solution_steps": "خطوات عملية محددة (1، 2، 3) ليقوم الطالب بتطبيقها لإصلاح كوده",
            "security_check": "فحص أمان سريع للكود (هل توجد ثغرات أو ضعف أمني؟)",
            "technical_debt": "حساب الديون التقنية (مثلاً: الوقت المقدر للإصلاح بالدقائق، ونسبة جودة كتابة الكود من 10)",
            "fixed_code": "الكود كاملاً بعد إصلاحه وتنسيقه بشكل مثالي ليراه الطالب كنموذج يحتذى به"
        }}
        
        الكود البرمجي للطالب:
        \"\"\"
        {code_content}
        \"\"\"
        """
        
        ai_response = model.generate_content(prompt)
        # تحويل رد الذكاء الاصطناعي النصي إلى كائن JSON لإرساله للمتصفح
        processed_data = json.loads(ai_response.text)
        
        return jsonify({
            "raw_result": raw_report,
            "ai_analysis": processed_data
        })

    except Exception as e:
        # في حال عدم وجود مفتاح API أو حدوث خطأ، نعيد التحليل التقني الجاف كخطة بديلة
        return jsonify({
            "raw_result": raw_report if 'raw_report' in locals() else "حدث خطأ أثناء معالجة الملف",
            "error": str(e),
            "fallback": True
        }), 200
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
