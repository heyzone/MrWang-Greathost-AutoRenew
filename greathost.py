##### greathost.py api后台协议抓取，指定名续期 ######

import os, re, time, json, requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

EMAIL = os.getenv("GREATHOST_EMAIL", "")
PASSWORD = os.getenv("GREATHOST_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PROXY_URL = os.getenv("PROXY_URL", "")
TARGET_NAME = os.getenv("TARGET_NAME", "loveMC")

STATUS_MAP = {
    "running": ["🟢", "Running"],
    "starting": ["🟡", "Starting"],
    "stopped": ["🔴", "Stopped"],
    "offline": ["⚪", "Offline"],
    "suspended": ["🚫", "Suspended"]
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
        proxy = {'proxy': {'http': PROXY_URL, 'https': PROXY_URL}} if PROXY_URL else None
        self.d = webdriver.Chrome(options=opts, seleniumwire_options=proxy)
        self.w = WebDriverWait(self.d, 25)

    def api(self, url, method="GET"):
        print(f"📡 API 调用 [{method}] {url}")
        script = f"return fetch('{url}',{{method:'{method}'}}).then(r=>r.json()).catch(e=>({{success:false,message:e.toString()}}))"
        return self.d.execute_script(script)

    def get_ip(self):
        try:
            self.d.get("https://api.ipify.org?format=json")
            ip = json.loads(self.d.find_element(By.TAG_NAME, "body").text).get("ip", "Unknown")
            print(f"🌐 落地 IP: {ip}")
            return ip
        except:
            print("🌐 落地 IP: 无法获取")
            return "Unknown"

    def login(self):
        print(f"🔑 正在登录: {EMAIL[:3]}***...")
        self.d.get("https://greathost.es/login")
        self.w.until(EC.presence_of_element_located((By.NAME, "email"))).send_keys(EMAIL)
        self.d.find_element(By.NAME, "password").send_keys(PASSWORD)
        self.d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        self.w.until(EC.url_contains("/dashboard"))

    def get_server(self):
        servers = self.api("/api/servers").get("servers", [])
        print(f"DEBUG 服务器列表: {[s.get('name') for s in servers]}")
        return next((s for s in servers if s.get("name") == TARGET_NAME), None)

    def get_status(self, sid):
        info = self.api(f"/api/servers/{sid}/information")
        st = info.get("status", "unknown").lower()
        icon, name = STATUS_MAP.get(st, ["❓", st])
        print(f"📋 状态核对: {TARGET_NAME} | {icon} {name}")
        return icon, name

    def get_renew_info(self, sid):
        data = self.api(f"/api/renewal/contracts/{sid}")
        print(f"DEBUG: 原始合同数据 -> {str(data)[:200]}...")
        return data.get("contract", {}).get("renewalInfo") or data.get("renewalInfo", {})

    def get_btn(self, sid):
        self.d.get(f"https://greathost.es/contracts/{sid}")
        btn = self.w.until(EC.presence_of_element_located((By.ID, "renew-free-server-btn")))
        self.w.until(lambda d: btn.text.strip() != "")
        btn_text = btn.text.strip()
        print(f"🔘 按钮状态: '{btn_text}'")
        return btn_text

    def renew(self, sid):
        print(f"🚀 正在执行续期 POST...")
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
        print(f"✅ 已锁定目标服务器: {TARGET_NAME} (ID: {sid})")

        icon, stname = gh.get_status(sid)
        status_disp = f"{icon} {stname}"

        info = gh.get_renew_info(sid)
        before = calculate_hours(info.get("nextRenewalDate"))

        btn = gh.get_btn(sid)
        print(f"🔘 按钮状态: '{btn}' | 剩余: {before}h")

        if "Wait" in btn:
            m = re.search(r"Wait\s+(\d+\s+\w+)", btn)
            send_notice("cooldown", [
                ("📛", "服务器名称", TARGET_NAME),
                ("🆔", "ID", f"<code>{sid}</code>"),
                ("⏳", "冷却时间", m.group(1) if m else btn),
                ("📊", "当前累计", f"{before}h"),
                ("🚀", "服务器状态", status_disp)
            ])
            return

        res = gh.renew(sid)
        ok = res.get("success", False)
        msg = res.get("message", "无返回消息")

        # ✅ 修复：兼容多种响应结构取 nextRenewalDate
        next_date = (
            res.get("nextRenewalDate") or
            res.get("details", {}).get("nextRenewalDate") or
            res.get("contract", {}).get("nextRenewalDate")
        )
        after = calculate_hours(next_date) if ok else before
        print(f"📡 续期响应: ok={ok} | next_date='{next_date}' | before={before}h | after={after}h | msg='{msg}'")

        if ok and after > before:
            send_notice("renew_success", [
                ("📛", "服务器名称", TARGET_NAME),
                ("🆔", "ID", f"<code>{sid}</code>"),
                ("⏰", "增加时间", f"{before} ➔ {after}h"),
                ("🚀", "服务器状态", status_disp),
                ("💡", "提示", msg),
                ("🌐", "落地 IP", f"<code>{ip}</code>")
            ])
        elif ok and ("5 d" in msg or before > 108):
            send_notice("maxed_out", [
                ("📛", "服务器名称", TARGET_NAME),
                ("🆔", "ID", f"<code>{sid}</code>"),
                ("⏰", "剩余时间", f"{after}h"),
                ("🚀", "服务器状态", status_disp),
                ("💡", "提示", msg),
                ("🌐", "落地 IP", f"<code>{ip}</code>")
            ])
        else:
            send_notice("renew_failed", [
                ("📛", "服务器名称", TARGET_NAME),
                ("🆔", "ID", f"<code>{sid}</code>"),
                ("🚀", "服务器状态", status_disp),
                ("⏰", "剩余时间", f"{before}h"),
                ("💡", "提示", msg),
                ("🌐", "落地 IP", f"<code>{ip}</code>")
            ])

    except Exception as e:
        print(f"🚨 运行异常: {e}")
        send_notice("error", [
            ("📛", "服务器名称", TARGET_NAME),
            ("❌", "故障", f"<code>{str(e)[:100]}</code>"),
            ("🌐", "代理状态", "已尝试直连")
        ])

    finally:
        if 'gh' in locals():
            try: gh.close()
            except: pass

if __name__ == "__main__":
    run()
