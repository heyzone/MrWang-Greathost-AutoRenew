##### greathost.py V2.1 - 增强状态兼容性版 ######

import os, re, time, json, requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- 环境变量配置 ---
EMAIL = os.getenv("GREATHOST_EMAIL", "")
PASSWORD = os.getenv("GREATHOST_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PROXY_URL = os.getenv("PROXY_URL", "") # 格式: socks5://user:pass@host:port 或 http://...
TARGET_NAME = os.getenv("TARGET_NAME", "furni1")

# 增强映射表，涵盖更多可能的 API 返回词
STATUS_MAP = {
    "running": ["🟢", "Running"],
    "online": ["🟢", "Running"],
    "active": ["🟢", "Running"],
    "starting": ["🟡", "Starting"],
    "pending": ["🟡", "Starting"],
    "stopped": ["🔴", "Stopped"],
    "offline": ["⚪", "Offline"],
    "suspended": ["🚫", "Suspended"]
}

MSG_MAP = {
    "Servidor gratuito renovado correctamente": "免费服务器续期成功",
    "Has alcanzado el límite máximo de renovaciones": "已达到最大续期上限",
    "Debes esperar antes de renovar de nuovo": "请等待冷却后再续期",
    "Servidor no encontrado": "未找到服务器",
    "No tienes permiso para renovar este servidor": "无权限续期此服务器",
}

def now_shanghai():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y/%m/%d %H:%M:%S')

def calculate_hours(date_str):
    try:
        if not date_str: return 0
        clean = re.sub(r'\.\d+Z$', 'Z', date_str)
        expiry = datetime.fromisoformat(clean.replace('Z', '+00:00'))
        diff = (expiry - datetime.now(timezone.utc)).total_seconds() / 3600
        return max(0, int(diff))
    except Exception as e:
        print(f"⚠️ 时间解析失败: {e}")
        return 0

def translate_msg(msg):
    return MSG_MAP.get(msg, msg)

def send_notice(kind, fields):
    titles = {
        "renew_success": "🎉 <b>GreatHost 续期成功</b>",
        "maxed_out": "🈵 <b>GreatHost 已达上限</b>",
        "cooldown": "⏳ <b>GreatHost 还在冷却中</b>",
        "renew_failed": "⚠️ <b>GreatHost 续期未生效</b>",
        "error": "🚨 <b>GreatHost 脚本报错</b>"
    }
    body = "\n".join([f"{e} {k}: {v}" for e, k, v in fields])
    msg = f"{titles.get(kind, '📢 通知')}\n\n{body}\n📅 时间: {now_shanghai()}"

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
                proxies={"http": None, "https": None},
                timeout=10
            )
            print(f"📨 TG推送结果: {r.status_code} | {r.text[:80]}")
        except Exception as e:
            print(f"📨 TG推送失败: {e}")
    else:
        print("📨 TG未配置，跳过推送")

    try:
        md = msg.replace("<b>", "**").replace("</b>", "**").replace("<code>", "`").replace("</code>", "`")
        with open("README.md", "w", encoding="utf-8") as f:
            f.write(f"# GreatHost 自动续期状态\n\n{md}\n\n> 最近更新: {now_shanghai()}")
    except: pass

class GH:
    def __init__(self):
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        proxy = {'proxy': {'http': PROXY_URL, 'https': PROXY_URL}} if PROXY_URL else None
        self.d = webdriver.Chrome(options=opts, seleniumwire_options=proxy)
        self.w = WebDriverWait(self.d, 30)

    def api(self, url, method="GET"):
        print(f"📡 API 调用 [{method}] {url}")
        script = f"return fetch('{url}',{{method:'{method}'}}).then(r=>r.json()).catch(e=>({{success:false,message:e.toString()}}))"
        try:
            return self.d.execute_script(script)
        except:
            return {"success": False}

    def get_ip(self):
        try:
            self.d.get("https://api.ipify.org?format=json")
            ip_data = json.loads(self.d.find_element(By.TAG_NAME, "body").text)
            ip = ip_data.get("ip", "Unknown")
            print(f"🌐 落地 IP: {ip}")
            return ip
        except:
            return "Unknown"

    def login(self):
        print(f"🔑 正在登录: {EMAIL[:3]}***...")
        self.d.get("https://greathost.es/login")
        self.w.until(EC.presence_of_element_located((By.NAME, "email"))).send_keys(EMAIL)
        self.d.find_element(By.NAME, "password").send_keys(PASSWORD)
        self.d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        self.w.until(EC.url_contains("/dashboard"))

    def get_server(self):
        res = self.api("/api/servers")
        servers = res.get("servers", []) if isinstance(res, dict) else []
        return next((s for s in servers if s.get("name") == TARGET_NAME), None)

    def get_status(self, sid):
        info = self.api(f"/api/servers/{sid}/information")
        # 兼容多种字段返回：status, state 或 直接返回字符串
        raw_st = info.get("status") or info.get("state") or "unknown"
        st = str(raw_st).lower().strip()
        
        icon, name = STATUS_MAP.get(st, ["❓", st])
        print(f"📋 实时状态: {TARGET_NAME} -> {icon} {name}")
        return icon, name, st

    def power_op(self, sid, action="start"):
        return self.api(f"/api/servers/{sid}/power", "POST")

    def get_renew_info(self, sid):
        data = self.api(f"/api/renewal/contracts/{sid}")
        if not isinstance(data, dict): return {}
        return data.get("contract", {}).get("renewalInfo") or data.get("renewalInfo", {})

    def get_btn(self, sid):
        self.d.get(f"https://greathost.es/contracts/{sid}")
        btn = self.w.until(EC.presence_of_element_located((By.ID, "renew-free-server-btn")))
        self.w.until(lambda d: btn.text.strip() != "")
        btn_text = btn.text.strip()
        print(f"🔘 页面按钮文字: '{btn_text}'")
        return btn_text

    def renew(self, sid):
        return self.api(f"/api/renewal/contracts/{sid}/renew-free", "POST")

    def close(self):
        self.d.quit()

def run():
    gh = GH()
    try:
        ip = gh.get_ip()
        gh.login()
        srv = gh.get_server()
        if not srv: raise Exception(f"未找到服务器 {TARGET_NAME}")
        sid = srv["id"]
        print(f"✅ 锁定目标: {TARGET_NAME} (ID: {sid})")

        # --- 1. 智能状态维护 ---
        icon, stname, raw_st = gh.get_status(sid)
        boot_msg = ""
        
        SHOULD_START = ["stopped", "offline"]
        TRANSITIONING = ["starting", "pending"]

        needs_wait = False
        if raw_st in SHOULD_START:
            print(f"⚠️ 服务器处于 {raw_st}，执行启动指令...")
            gh.power_op(sid, "start")
            needs_wait = True
        elif raw_st in TRANSITIONING:
            print(f"⏳ 服务器正忙({raw_st})，进入观测模式...")
            needs_wait = True
        elif raw_st == "running":
            print(f"✅ 服务器当前运行正常")
        else:
            print(f"⚠️ 未知状态 {raw_st}，尝试进入观测...")
            needs_wait = True

        if needs_wait:
            max_retries = 12  # 20秒 * 12次 = 4分钟
            wait_interval = 20
            for i in range(max_retries):
                print(f"🕒 启动观测中... (第 {i+1}/{max_retries} 次, 已过 {i*wait_interval}s)")
                time.sleep(wait_interval)
                icon, stname, raw_st = gh.get_status(sid)
                if raw_st in ["running", "online", "active"]:
                    print(f"✨ 服务器已就绪！耗时约 {i*wait_interval}s")
                    break
            else:
                print("🚨 服务器启动等待超时")
            boot_msg = f" (维护后: {stname})"
        
        status_disp = f"{icon} {stname}{boot_msg}"

        # --- 2. 续期逻辑 ---
        info = gh.get_renew_info(sid)
        before = calculate_hours(info.get("nextRenewalDate"))

        btn = gh.get_btn(sid)
        print(f"🔘 状态汇总: 按钮='{btn}' | 剩余时间={before}h")

        if "Wait" in btn:
            m = re.search(r"Wait\s+(\d+\s+\w+)", btn)
            send_notice("cooldown", [
                ("📛", "服务器", TARGET_NAME),
                ("⏳", "冷却中", m.group(1) if m else btn),
                ("📊", "当前累计", f"{before}h"),
                ("🚀", "状态", status_disp)
            ])
            return

        res = gh.renew(sid)
        ok = res.get("success", False)
        msg = translate_msg(res.get("message", "无返回消息"))

        # 深度提取下次续期时间
        next_date = None
        if isinstance(res, dict):
            next_date = res.get("nextRenewalDate") or \
                        res.get("details", {}).get("nextRenewalDate") or \
                        res.get("contract", {}).get("nextRenewalDate")
        
        after = calculate_hours(next_date) if (ok and next_date) else before

        if ok and after > before:
            send_notice("renew_success", [
                ("📛", "服务器", TARGET_NAME),
                ("⏰", "续期结果", f"{before}h ➔ {after}h"),
                ("🚀", "状态", status_disp),
                ("💡", "提示", msg),
                ("🌐", "落地 IP", f"<code>{ip}</code>")
            ])
        elif ok:
            send_notice("maxed_out", [
                ("📛", "服务器", TARGET_NAME),
                ("⏰", "剩余时间", f"{after}h"),
                ("🚀", "状态", status_disp),
                ("💡", "提示", msg),
                ("🌐", "落地 IP", f"<code>{ip}</code>")
            ])
        else:
            send_notice("renew_failed", [
                ("📛", "服务器", TARGET_NAME),
                ("🚀", "状态", status_disp),
                ("⏰", "剩余时间", f"{before}h"),
                ("💡", "提示", msg),
                ("🌐", "落地 IP", f"<code>{ip}</code>")
            ])

    except Exception as e:
        print(f"🚨 运行异常: {e}")
        send_notice("error", [
            ("📛", "服务器", TARGET_NAME),
            ("❌", "故障", f"<code>{str(e)[:100]}</code>")
        ])

    finally:
        if 'gh' in locals():
            try: gh.close()
            except: pass

if __name__ == "__main__":
    run()
