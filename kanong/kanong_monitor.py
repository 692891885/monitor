#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
卡农论坛「放水信号」监控
=====================================
原理（跟群里那个机器人一样）：
  定时抓【羊毛交流】板块最新帖子列表
  · 统计滑动窗口内（默认10分钟）的发帖数量
  · 匹配"放水关键词"：人人、速度、毕业、拿下、还有、有水、秒批...
  · 多词共振加分：短时间出现多个不同关键词 → 更可能是真放水
  · 综合分数超阈值 → 判定为放水信号，推送通知

判定逻辑：
  基础分 = 命中关键词数 × 权重
  速度分 = 窗口内发帖数 / 平时发帖数（突增倍数）
  共振分 = 窗口中不同关键词种类数
  综合分 >= 阈值 就通知

用法：
  python3 kanong_monitor.py          持续监控
  python3 kanong_monitor.py once     只查一次
  python3 kanong_monitor.py test     本地自测解析

依赖：只用标准库
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import http.cookiejar

# ==================== 配置 ====================
BASE = "https://www.51kanong.com"
# 羊毛交流板块
BOARD = "/yh-169-1.htm"

# 多久看一次（秒）。建议 60~90，太快容易被站方拦
INTERVAL = 75

# 滑动窗口（分钟）：统计这段时间内的帖子
WINDOW_MIN = 10

# 触发阈值：综合分 >= 这个数就通知
THRESHOLD = 5.0

# ---------- 放水关键词（命中即计分） ----------
KEYWORDS = {
    "人人": 2.0,    # 人人可撸，门槛低
    "速度": 2.0,    # 催促，快到货
    "毕业": 2.0,    # 已到手/结束
    "拿下": 1.5,
    "还有": 1.5,
    "有水": 2.5,    # 核心放水词
    "放水": 3.0,    # 核心放水词
    "秒批": 2.0,
    "秒到": 2.0,
    "大毛": 2.5,
    "刚中": 2.0,
    "必中": 2.5,
    "快去": 1.5,
    "入口": 0.8,
    "立减": 1.0,
    "红包": 1.0,
    "抽奖": 0.8,
    "白嫖": 1.5,
    "无门槛": 1.5,
    "名额": 1.5,
    "限量": 1.2,
}

# ---------- 排除词（含这些的帖子不算） ----------
EXCLUDE = ["请问", "求问", "怎么弄", "什么意思", "被骗", "投诉", "举报", "回收"]

# ---------- 推送配置 ----------
MAIL_TO = "692891885@qq.com"
MAIL_SMTP = "smtp.qq.com"
MAIL_PORT = 465
MAIL_USER = "692891885@qq.com"
MAIL_PASS = "fdarahrbgnfpbcci"

DINGTALK_WEBHOOK = ""
DINGTALK_SECRET = ""
DESKTOP_NOTIFY = True
# ===========================================

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "kanong_state.json")
LOG_FILE = os.path.join(HERE, "kanong.log")
SEEN_FILE = os.path.join(HERE, "seen_tids.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

_cj = http.cookiejar.CookieJar()
_op = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_cj),
    urllib.request.HTTPSHandler(context=CTX))
_op.addheaders = [
    ("User-Agent", UA),
    ("Accept", "text/html,application/xhtml+xml,*/*;q=0.8"),
    ("Accept-Language", "zh-CN,zh;q=0.9"),
]


def log(msg):
    line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def fetch(url, tries=4):
    """抓页面，自动处理站点的'页面重新载入'反爬页"""
    for i in range(tries):
        try:
            r = _op.open(url, timeout=20)
            h = r.read()
            for enc in ("utf-8", "gb18030"):
                try:
                    t = h.decode(enc)
                    break
                except Exception:
                    t = h.decode("utf-8", "ignore")
            if len(t) > 5000:
                return t
            log("  反爬页，重试 %d/%d" % (i + 1, tries))
            time.sleep(2)
        except Exception as e:
            log("  抓取异常: %s" % repr(e)[:80])
            time.sleep(2)
    return ""


def within_window(tstr, minutes=None):
    """判断发帖时间是否在最近 N 分钟内"""
    if minutes is None:
        minutes = WINDOW_MIN
    if not tstr:
        return False
    tstr = tstr.strip()
    now = time.time()
    try:
        if tstr in ("昨天",):
            return minutes >= 1440
        if tstr in ("前天",):
            return False
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?: (\d{1,2}):(\d{2}))?$", tstr)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hh = int(m.group(4)) if m.group(4) else 0
            mi = int(m.group(5)) if m.group(5) else 0
            ts = time.mktime((y, mo, d, hh, mi, 0, 0, 0, -1))
            return (now - ts) <= minutes * 60
        if re.match(r"^\d{1,2}-\d{1,2}$", tstr):
            mm, dd = tstr.split("-")
            tm = time.localtime()
            ts = time.mktime((tm.tm_year, int(mm), int(dd), 0, 0, 0, 0, 0, -1))
            return (now - ts) <= minutes * 60 + 86400
        if re.match(r"^\d{1,2}:\d{2}$", tstr):
            hh, mi = tstr.split(":")
            tm = time.localtime()
            ts = time.mktime((tm.tm_year, tm.tm_mon, tm.tm_mday, int(hh), int(mi), 0, 0, 0, -1))
            if ts > now + 300:
                ts -= 86400
            return (now - ts) <= minutes * 60
    except Exception:
        return False
    return False


def parse_threads(html):
    """解析帖子列表，返回 [{tid,title,url}]

    卡农是 Discuz 改版，帖子链接形如：
        xyk-13108549-1.htm     （信用卡）
        yh-13108549-1.htm      （羊毛，同 tid 不同前缀）
    标题在 <a class="s xst">标题</a> 里
    """
    items = []
    # 主规则：class="s xst" 的链接就是帖子标题
    for m in re.finditer(
            r'<a\s+href="([a-z]{2,6}-(\d+)-\d+\.htm)"[^>]*class="[^"]*s xst[^"]*"[^>]*>'
            r'([^<]{2,120})',
            html):
        url, tid, title = m.group(1), m.group(2), m.group(3).strip()
        if not title or len(title) < 2:
            continue
        items.append({"tid": tid, "title": title, "url": BASE + "/" + url, "time": None})

    # 备用规则：任意 <a href="xxx-digits-1.htm"> 且有 title 属性
    if not items:
        for m in re.finditer(
                r'<a\s+href="([a-z]{2,6}-(\d+)-\d+\.htm)"[^>]*title="([^"]{4,120})"',
                html):
            url, tid, title = m.group(1), m.group(2), m.group(3).strip()
            items.append({"tid": tid, "title": title, "url": BASE + "/" + url, "time": None})

    # 补抓每帖的发帖时间
    # 卡农列表页结构：<span class="xi1"> 2026-11-18 10:34</span>
    for it in items:
        tid = it["tid"]
        # 从该帖的 tbody 块里找时间
        blk = re.search(r'normalthread_%s(.{0,4000}?)</tbody>' % tid, html, re.S)
        scope = blk.group(1) if blk else html
        m2 = re.search(r'<span class="xi1">\s*(\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{2})', scope)
        if not m2:
            m2 = re.search(r'<span class="xi1">\s*(\d{1,2}-\d{1,2}|\d{1,2}:\d{2}|昨天|前天)', scope)
        if m2:
            it["time"] = m2.group(1).strip()
    # 去重
    seen, out = set(), []
    for it in items:
        if it["tid"] in seen:
            continue
        seen.add(it["tid"])
        out.append(it)
    return out


def board_titles(html):
    """从列表页抓所有可见标题（放宽，用于统计活跃度）"""
    titles = []
    for m in re.finditer(r'class="[^"]*(?:s xst|title|subject)[^"]*"[^>]*>([^<]{4,80})<', html):
        t = m.group(1).strip()
        if t and not t.isdigit():
            titles.append(t)
    return titles


def score_post(title, window_count, avg_count, kw_hits):
    """给单个帖子评分"""
    s = 0.0
    hit_words = []
    for kw, w in KEYWORDS.items():
        if kw in title:
            s += w
            hit_words.append(kw)
    # 活跃度加成
    if avg_count > 0:
        ratio = window_count / float(avg_count)
        if ratio >= 1.8:
            s += 1.5
        if ratio >= 2.5:
            s += 1.0
    # 多词共振
    if len(set(hit_words)) >= 2:
        s += len(set(hit_words)) - 1
    return s, hit_words


def notify(title, body):
    sent = []
    if DINGTALK_WEBHOOK:
        try:
            import hmac, hashlib, base64
            url = DINGTALK_WEBHOOK
            if DINGTALK_SECRET:
                ts = str(round(time.time() * 1000))
                sign_str = "%s\n%s" % (ts, DINGTALK_SECRET)
                hh = hmac.new(DINGTALK_SECRET.encode(), sign_str.encode(),
                              digestmod=hashlib.sha256).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hh))
                url += ("&" if "?" in url else "?") + "timestamp=%s&sign=%s" % (ts, sign)
            payload = json.dumps({
                "msgtype": "markdown",
                "markdown": {"title": title, "text": "### " + title + "\n\n" + body}}).encode()
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, context=CTX, timeout=15).read().decode()
            if "errcode" in resp and '"errcode":0' in resp.replace(" ", ""):
                sent.append("钉钉")
            else:
                log("  钉钉返回: %s" % resp[:100])
        except Exception as e:
            log("  钉钉失败: %s" % repr(e)[:60])
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
            log("  邮件失败: %s" % repr(e)[:60])
    if DESKTOP_NOTIFY:
        try:
            from plyer import notification
            notification.notify(title=title, message=body[:200], timeout=15)
            sent.append("桌面")
        except Exception:
            pass
    log("  已推送: %s" % ("、".join(sent) if sent else "（无渠道）"))


PUSHED_FILE = os.path.join(HERE, "pushed_tids.json")


def load_seen():
    """已看过/已推送的帖子 ID（去重用）"""
    merged = set()
    for f in (SEEN_FILE, PUSHED_FILE):
        if os.path.exists(f):
            try:
                d = json.load(open(f, encoding="utf-8"))
                if isinstance(d, list):
                    merged.update(str(x) for x in d)
                elif isinstance(d, dict):
                    merged.update(str(k) for k in d.keys())
            except Exception:
                pass
    return merged


def save_seen(s):
    try:
        json.dump(list(s)[-5000:], open(SEEN_FILE, "w", encoding="utf-8"))
    except Exception:
        pass


def save_pushed(tids, titles=None):
    """单独记录已推送过的帖子（含时间），用于审计和永久去重"""
    d = {}
    if os.path.exists(PUSHED_FILE):
        try:
            d = json.load(open(PUSHED_FILE, encoding="utf-8"))
            if not isinstance(d, dict):
                d = {}
        except Exception:
            d = {}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for t in tids:
        d[str(t)] = (titles or {}).get(t, now)
    # 只保留最近 2000 条
    if len(d) > 2000:
        items = sorted(d.items(), key=lambda x: x[1])[-2000:]
        d = dict(items)
    try:
        json.dump(d, open(PUSHED_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def check_once(seen, first_run=False):
    url = BASE + BOARD
    html = fetch(url)
    if not html:
        log("抓取失败")
        return False

    items = parse_threads(html)
    titles = board_titles(html)
    log("  板块帖子 %d 条（解析到链接 %d 个）" % (len(titles), len(items)))

    if not items and not titles:
        log("  没解析到内容，页面结构可能变了")
        return False

    # 估算活跃度：本次可见帖子总数 vs 历史均值
    st = {}
    if os.path.exists(STATE_FILE):
        try:
            st = json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            st = {}
    hist = st.get("counts", [])
    avg = sum(hist) / float(len(hist)) if hist else 0

    new_items = [it for it in items if it["tid"] not in seen]

    # 按真实发帖时间做窗口过滤
    win_items = [it for it in items if within_window(it.get("time"))]
    if not win_items:
        win_items = new_items  # 时间抓不到就退回用新帖
    log("  板块 %d 条 | 窗口内(%d分) %d 条 | 新帖 %d 条 | 历史均值 %.0f"
        % (len(items), WINDOW_MIN, len(win_items), len(new_items), avg))

    # 评分：只评估尚未推送过的帖子，避免同一帖反复提醒
    win_count = len(win_items)
    fresh_items = [it for it in win_items if it["tid"] not in seen]
    hits = []
    for it in fresh_items:
        title = it["title"]
        if any(x in title for x in EXCLUDE):
            continue
        s, words = score_post(title, win_count, avg, None)
        if s >= 2.0:
            hits.append((s, it, words))

    hits.sort(key=lambda x: -x[0])

    # 综合分 = 最高分 + 共振加成
    total = 0.0
    if hits:
        allwords = set()
        for s, it, w in hits:
            allwords.update(w)
        total = hits[0][0] + max(0, len(allwords) - 1) * 0.5
        # 发帖突增加成
        if avg > 0 and len(items) / avg >= 2.0:
            total += 2.0

    log("  综合分 %.1f（阈值 %.1f） 命中 %d 条" % (total, THRESHOLD, len(hits)))

    for s, it, w in hits[:5]:
        log("    %.1f分 [%s] %s" % (s, ",".join(w[:3]), it["title"][:40]))

    if not first_run and total >= THRESHOLD and hits:
        lines = ["窗口 %d 分钟 | 板块帖子 %d 条 | 综合 %.1f 分"
                 % (WINDOW_MIN, len(items), total), ""]
        lines.append("命中：")
        for s, it, w in hits[:6]:
            lines.append("· %s  （%s）" % (it["title"][:44], "、".join(w[:3])))
            lines.append("  " + it["url"])
        lines.append("")
        lines.append("板块地址：%s%s" % (BASE, BOARD))
        notify("🎣 卡农放水信号（%.1f分）" % total, "\n".join(lines))
        # 记录已通知：窗口内所有帖子都标记，避免同一批再次触发
        for it in win_items:
            seen.add(it["tid"])
        save_seen(seen)
        save_pushed([it["tid"] for it in win_items],
                    {it["tid"]: it["title"][:40] for it in win_items})
        return True

    for it in items:
        seen.add(it["tid"])
    save_seen(seen)

    # 更新活跃度历史
    hist.append(len(items))
    st["counts"] = hist[-50:]
    st["lastCheck"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        json.dump(st, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    return False


def main():
    once = len(sys.argv) > 1 and sys.argv[1] == "once"
    test = len(sys.argv) > 1 and sys.argv[1] == "test"

    if test:
        # 用已保存的页面自测解析
        p = os.path.join(HERE, "yh169.html")
        if not os.path.exists(p):
            print("没有测试页面，先跑一次 once")
            return
        h = open(p, encoding="utf-8", errors="ignore").read()
        items = parse_threads(h)
        print("解析到帖子 %d 条：" % len(items))
        for it in items[:10]:
            print("  [%s] %s" % (it["tid"], it["title"][:50]))
        return

    log("=" * 52)
    log("卡农放水信号监控启动")
    log("板块: %s%s" % (BASE, BOARD))
    log("间隔: %ds  阈值: %.1f" % (INTERVAL, THRESHOLD))
    log("=" * 52)

    seen = load_seen()
    if once:
        log("单次检查")
        check_once(seen, first_run=True)
        log("完成")
        return

    log("首次检查建立基线…")
    check_once(seen, first_run=True)
    log("基线完成，开始循环")
    n = 0
    while True:
        try:
            time.sleep(INTERVAL)
            n += 1
            log("第 %d 次检查" % n)
            check_once(seen)
        except KeyboardInterrupt:
            log("已停止")
            break
        except Exception as e:
            log("异常: %s" % repr(e)[:100])
            time.sleep(30)


if __name__ == "__main__":
    main()
