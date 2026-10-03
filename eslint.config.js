// إعداد ESLint لفحص أكواد الطلاب (يُستدعى عبر subprocess من app.py على ملف مؤقت)
const js = require("@eslint/js");

module.exports = [
    js.configs.recommended,
    {
        languageOptions: {
            ecmaVersion: "latest",
            sourceType: "script",
            globals: { console: "readonly", require: "readonly", module: "readonly" },
        },
        rules: {
            "no-unused-vars": "warn",
            "no-undef": "warn",
            "eqeqeq": "warn",
            "no-var": "warn",
        },
    },
];
