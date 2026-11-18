# 放水监控 · GitHub Actions 免费部署

## 为什么用这个
- 完全免费，不用买服务器
- 永久在线，不会像手机后台被系统杀掉
- 每 5 分钟自动跑一次，每次内部连查 7 轮（每 40 秒一轮），实际覆盖不间断

## 部署步骤（10 分钟）

### 1. 建仓库
注册/登录 GitHub → 右上角 `+` → New repository
- 名字随意，比如 `monitor`
- 选 **Public**（公开仓库 Actions 免费不限时长；Private 每月只有 2000 分钟也够用）
- 创建

### 2. 上传文件
把本文件夹里所有内容传上去，保持这个结构：

```
monitor/
├── .github/
│   └── workflows/
│       └── monitor.yml
├── kanong/
│   └── kanong_monitor.py
├── jdmon/
│   └── jd_coupon_monitor.py
└── README.md
```

用网页上传：仓库页 → Add file → Upload files → 拖进去 → Commit

⚠️ `.github` 这个文件夹名以点开头，网页上传时注意别漏。

### 3. 配置 Secrets（放密码用，不会泄露）
仓库 → Settings → Secrets and variables → Actions → New repository secret

逐个添加：

| Name | Value |
|---|---|
| `MAIL_TO` | 692891885@qq.com |
| `MAIL_USER` | 692891885@qq.com |
| `MAIL_PASS` | 你的QQ邮箱授权码 |
| `DINGTALK_WEBHOOK` | 钉钉机器人Webhook（可选） |
| `DINGTALK_SECRET` | 钉钉加签密钥（可选） |

### 4. 开启 Actions
仓库 → Actions 标签 → 如果提示要启用，点 `I understand my workflows, go ahead and enable them`

### 5. 手动测试一次
Actions → 左侧「放水监控」→ 右侧 `Run workflow` 按钮 → 点绿色按钮
等 1 分钟，点进运行记录看日志，能看到「板块 20 条 | 窗口内 XX 条」就成功了

### 6. 完成
之后每 5 分钟自动跑，有信号就发邮件/钉钉

## 两个监控分别做什么

**卡农放水信号**
- 抓 51kanong.com 羊毛交流板块
- 按发帖时间统计最近 10 分钟
- 放水词加权 + 多词共振 + 发帖突增
- 综合分 ≥ 5.0 就通知

**京东外卖券**
- 监控华莱士白条立减10元券补货
- 塔斯汀上架也会提示
- canDrawReward 变 true 就通知

## 想调整

改 `kanong/kanong_monitor.py` 顶部：
```python
THRESHOLD = 5.0        # 阈值，调低更容易触发
WINDOW_MIN = 10        # 时间窗口
KEYWORDS = {...}       # 放水关键词和权重
```

改频率：编辑 `.github/workflows/monitor.yml` 里的 `cron: '*/5 * * * *'`
- `*/3` 是 3 分钟（GitHub 可能不准时）
- `*/10` 是 10 分钟

## 注意
- GitHub 的定时任务**不是精确的**，高峰期可能延迟几分钟
- 公开仓库的 Actions 日志别人能看到，但 Secrets 里的密码看不到
- 想更实时只能自己架服务器，免费方案这就是最好的
