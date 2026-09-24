import os
import subprocess
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
CORS(app)

# إعداد مفتاح الذكاء الاصطناعي (يمكنك الحصول على مفتاح مجاني من Google AI Studio)
# للمطوّر محلياً، يمكنك وضعه مباشرة هنا للتجربة التعليمية
genai.configure(api_key="AQ.Ab8RN6IhufcjUUlzcZXnXJfUrolcyMSnARsrWPT10pqx6fFAWw")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_files")
os.makedirs(TEMP_DIR, exist_ok=True)

@app.route('/', methods=['GET'])
def home():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/api/check-code', methods=['POST'])
def check_code():
    data = request.get_json()
    if not data or 'code' not in data or 'language' not in data:
        return jsonify({"error": "البيانات المرسلة غير مكتملة"}), 400
    
    code_content = data['code']
    language = data['language'].lower()
    
    extensions = {"python": "temp.py", "c": "temp.c", "cpp": "temp.cpp"}
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
