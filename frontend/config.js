// این فایل تنها جایی است که برای انتشار (دیپلوی) روی گیت‌هاب پیجز + رندر باید ویرایش کنی.
//
// روی لپ‌تاپ خودت (development) همین مقادیر پیش‌فرض (localhost) درست کار می‌کنند.
//
// بعد از دیپلوی بک‌اند روی Render، یک آدرس شبیه این می‌گیری:
//   https://chatyar-backend.onrender.com
// همان آدرس را (بدون تغییر دیگری) به‌جای مقدار زیر بگذار، هم برای API_BASE (با https)
// و هم برای WS_BASE (با wss به‌جای https).

const API_BASE = "http://localhost:8000";
const WS_BASE = "ws://localhost:8000";

// مثال بعد از دیپلوی:
// const API_BASE = "https://chatyar-backend.onrender.com";
// const WS_BASE = "wss://chatyar-backend.onrender.com";
