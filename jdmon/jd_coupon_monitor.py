#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
京东外卖超级补贴 —— 优惠券补货监控

监控目标：
  · 华莱士「白条立减10元」券（0.9元起吃）补货
  · 塔斯汀出现并有库存

监控原理：
  定时抓取活动页，解析页面内嵌的券数据 JSON，判断
      canDrawReward = true   → 可以领取（有货）
      fail = false           → 校验通过
      activityStatusCode     → OL 表示活动在线
  一旦从"没货"变成"有货"，立刻通知

通知方式（任选，在下面配置）：
  1. 桌面通知（手机/电脑弹窗）
  2. Bark（iOS 推送，填 key）
  3. Server酱（微信推送，填 key）
  4. 企业微信机器人（填 webhook）
  5. 命令行打印（默认一直开着）

运行：
  python3 jd_coupon_monitor.py            # 持续监控
  python3 jd_coupon_monitor.py once       # 只查一次看状态
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

# ==================== 配置区 ====================
ACTIVITY_URL = "https://pro.m.jd.com/mall/active/2BuMtujoMx1EPnFvUrUpsrYucqUK/index.html"

# 监控间隔（秒）。别太快，建议 60~120 秒
INTERVAL = 45

# 要监控的品牌关键词（出现这些名字的券就会检查）
WATCH_BRANDS = ["华莱士", "塔斯汀"]

# ---------- 通知渠道，填哪个用哪个，留空就不启用 ----------
BARK_URL = ""          # 例：https://api.day.app/你的key

# ---------- 钉钉机器人 ----------
# 在钉钉群 → 群设置 → 智能群助手 → 添加机器人 → 自定义
# 复制 Webhook 地址，如果开了"加签"，把密钥也填上
DINGTALK_WEBHOOK = ""
DINGTALK_SECRET = ""   # 可选，开了加签才需要

# ---------- 邮箱 ----------
MAIL_TO = "692891885@qq.com"           # 收件邮箱，多个用逗号分隔
MAIL_SMTP = "smtp.qq.com"         # 例：smtp.qq.com / smtp.163.com
MAIL_PORT = 465        # SSL 一般 465，STARTTLS 用 587
MAIL_USER = "692891885@qq.com"         # 发件邮箱
MAIL_PASS = "fdarahrbgnfpbcci"         # 邮箱授权码（不是登录密码！）
SERVERCHAN_KEY = ""    # 例：SCT123456Txxxxxxxx
WECOM_WEBHOOK = ""     # 例：https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
DESKTOP_NOTIFY = True  # 本机弹窗（需要 plyer，没装会自动跳过）
# ================================================

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "monitor_state.json")
LOG_FILE = os.path.join(HERE, "monitor.log")

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
      "Mobile/15E148 Safari/604.1")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def log(msg):
    line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://u.jd.com/",
    })
    r = urllib.request.urlopen(req, context=CTX, timeout=timeout)
    return r.read().decode("utf-8", "ignore")


def extract_json_objects(html):
    """从 HTML 里把所有像券数据的 JSON 对象抠出来"""
    out = []
    # 按 activityName 定位
    for m in re.finditer(r'"activityName"\s*:\s*"([^"]{2,80})"', html):
        name = m.group(1)
        # 向前找对象起点
        start = html.rfind("{", 0, m.start())
        # 逐层向前扩展，找到能完整解析的最大对象
        pos = start
        for _ in range(60):
            if pos < 0:
                break
            depth = 0
            end = None
            for k in range(pos, min(len(html), pos + 20000)):
                c = html[k]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = k + 1
                        break
            if end:
                try:
                    obj = json.loads(html[pos:end])
                    if isinstance(obj, dict) and obj.get("activityName") == name:
                        out.append(obj)
                        break
                except Exception:
                    pass
            pos = html.rfind("{", 0, pos)
    # 去重
    seen, uniq = set(), []
    for o in out:
        key = (o.get("activityName"), o.get("activityId"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(o)
    return uniq


def judge(coupon):
    """判断这张券现在能不能领"""
    name = coupon.get("activityName") or ""
    drawable = coupon.get("canDrawReward")
    fail = coupon.get("fail")
    status = coupon.get("activityStatusCode") or ""
    day_stock = coupon.get("activityDayStock")
    total_stock = coupon.get("activityTotalStock")
    verify = coupon.get("verifyResultCode")
    btn = coupon.get("batchBtnText") or coupon.get("batchReceivedBtnText") or ""
    # 有货判定：canDrawReward 为 True 且 fail 不为 True
    available = bool(drawable) and (fail is not True)
    return {
        "name": name,
        "available": available,
        "canDrawReward": drawable,
        "fail": fail,
        "status": status,
        "dayStock": day_stock,
        "totalStock": total_stock,
        "verify": verify,
        "btn": btn,
    }


def notify(title, body):
    """多渠道通知"""
    sent = []

    # 钉钉
    if DINGTALK_WEBHOOK:
        try:
            import hmac, hashlib, base64
            url = DINGTALK_WEBHOOK
            if DINGTALK_SECRET:
                ts = str(round(time.time() * 1000))
                sign_str = "%s\n%s" % (ts, DINGTALK_SECRET)
                h = hmac.new(DINGTALK_SECRET.encode(), sign_str.encode(),
                             digestmod=hashlib.sha256).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(h))
                url = url + ("&" if "?" in url else "?") + "timestamp=%s&sign=%s" % (ts, sign)
            payload = json.dumps({
                "msgtype": "markdown",
                "markdown": {"title": title, "text": "### " + title + "\n\n" + body}
            }).encode()
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, context=CTX, timeout=15).read().decode()
            if '"errcode":0' in resp or 'errcode": 0' in resp:
                sent.append("钉钉")
            else:
                log("  钉钉返回异常: %s" % resp[:120])
        except Exception as e:
            log("  钉钉 失败: %s" % repr(e)[:80])

    # 邮件
    if MAIL_TO and MAIL_SMTP and MAIL_USER and MAIL_PASS:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.header import Header
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = Header(title, "utf-8")
            msg["From"] = MAIL_USER
            msg["To"] = MAIL_TO
            if MAIL_PORT == 465:
                srv = smtplib.SMTP_SSL(MAIL_SMTP, MAIL_PORT, timeout=20, context=CTX)
            else:
                srv = smtplib.SMTP(MAIL_SMTP, MAIL_PORT, timeout=20)
                srv.starttls(context=CTX)
            srv.login(MAIL_USER, MAIL_PASS)
            srv.sendmail(MAIL_USER, [x.strip() for x in MAIL_TO.split(",") if x.strip()],
                         msg.as_string())
            srv.quit()
            sent.append("邮件")
        except Exception as e:
            log("  邮件 失败: %s" % repr(e)[:80])

    # Bark
    if BARK_URL:
        try:
            u = BARK_URL.rstrip("/") + "/" + urllib.parse.quote(title) + "/" + urllib.parse.quote(body)
            urllib.request.urlopen(u, context=CTX, timeout=15).read()
            sent.append("Bark")
        except Exception as e:
            log("  Bark 推送失败: %s" % repr(e)[:60])
    # Server酱
    if SERVERCHAN_KEY:
        try:
            u = "https://sctapi.ftqq.com/%s.send" % SERVERCHAN_KEY
            data = urllib.parse.urlencode({"title": title, "desp": body}).encode()
            urllib.request.urlopen(u, data=data, context=CTX, timeout=15).read()
            sent.append("Server酱")
        except Exception as e:
            log("  Server酱 失败: %s" % repr(e)[:60])
    # 企业微信
    if WECOM_WEBHOOK:
        try:
            payload = json.dumps({"msgtype": "text",
                                  "text": {"content": title + "\n" + body}}).encode()
            req = urllib.request.Request(WECOM_WEBHOOK, data=payload,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, context=CTX, timeout=15).read()
            sent.append("企业微信")
        except Exception as e:
            log("  企业微信 失败: %s" % repr(e)[:60])
    # 桌面弹窗
    if DESKTOP_NOTIFY:
        try:
            from plyer import notification
            notification.notify(title=title, message=body, timeout=15)
            sent.append("桌面")
        except Exception:
            pass
    log("  已通知: %s" % ("、".join(sent) if sent else "（无渠道，仅日志）"))


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(st):
    try:
        json.dump(st, open(STATE_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass


def check_once(state, first_run=False):
    """抓取一次并判断，返回是否有新的可领券"""
    try:
        html = fetch(ACTIVITY_URL)
    except Exception as e:
        log("抓取失败: %s" % repr(e)[:100])
        return False

    coupons = extract_json_objects(html)
    if not coupons:
        log("未解析到券数据（页面结构可能变了），HTML 长度 %d" % len(html))
        return False

    hits = []
    for c in coupons:
        info = judge(c)
        name = info["name"]
        if not any(b in name for b in WATCH_BRANDS):
            continue
        key = info["name"]
        old = state.get(key, {})
        was = old.get("available")

        # 状态日志
        flag = "★可领" if info["available"] else "无货"
        log("  [%s] %s  (canDraw=%s fail=%s status=%s 日库存=%s)"
            % (flag, name, info["canDrawReward"], info["fail"],
               info["status"], info["dayStock"]))

        # 从无货变有货 → 提醒
        if info["available"] and was is not True:
            hits.append(info)

        state[key] = {
            "available": info["available"],
            "canDrawReward": info["canDrawReward"],
            "fail": info["fail"],
            "status": info["status"],
            "dayStock": info["dayStock"],
            "lastCheck": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    if hits:
        lines = []
        for h in hits:
            lines.append("· %s（日库存 %s）" % (h["name"], h["dayStock"]))
        body = "\n".join(lines) + "\n\n快去领取：\n" + ACTIVITY_URL
        notify("🎉 优惠券补货了！", body)
        return True

    save_state(state)
    return False


def burst(state, rounds=12, gap=25):
    """连查多轮，适配低频定时任务（12轮×25秒≈5分钟）"""
    log("BURST 模式：连查 %d 轮，间隔 %ds" % (rounds, gap))
    for i in range(rounds):
        try:
            check_once(state)
        except Exception as e:
            log("  轮次异常: %s" % repr(e)[:80])
        if i < rounds - 1:
            time.sleep(gap)
    log("BURST 结束")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "burst":
        burst(load_state())
        return
    once = len(sys.argv) > 1 and sys.argv[1] == "once"
    log("=" * 52)
    log("京东外卖券监控启动")
    log("监控品牌: %s" % "、".join(WATCH_BRANDS))
    log("间隔: %ds" % INTERVAL)
    log("=" * 52)

    state = load_state()
    if once:
        log("单次检查模式")
        check_once(state, first_run=True)
        save_state(state)
        log("完成")
        return

    # 首次先建立基线（避免一启动就误报）
    log("首次检查，建立基线…")
    check_once(state, first_run=True)
    save_state(state)
    log("基线已建立，开始循环监控")
    log("")

    n = 0
    while True:
        try:
            time.sleep(INTERVAL)
            n += 1
            log("第 %d 次检查" % n)
            check_once(state)
            save_state(state)
        except KeyboardInterrupt:
            log("已停止")
            break
        except Exception as e:
            log("异常: %s" % repr(e)[:100])
            time.sleep(30)


if __name__ == "__main__":
    main()
