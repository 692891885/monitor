#!/bin/bash
# 本地执行：把部署包推到你的 GitHub 仓库
# 用法：bash 一键部署.sh 你的仓库地址
# 例：  bash 一键部署.sh https://github.com/用户名/monitor.git

set -e
REPO="$1"
if [ -z "$REPO" ]; then
  echo "用法: bash 一键部署.sh https://github.com/你的用户名/仓库名.git"
  exit 1
fi

echo "==> 初始化 git"
git init -q 2>/dev/null || true
git add -A
git -c user.email="deploy@local" -c user.name="deploy" commit -m "监控部署" -q || true

echo "==> 推送到 $REPO"
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO"
git push -u origin main

echo ""
echo "✅ 推送完成"
echo ""
echo "接下来去 GitHub 网页："
echo "1. 仓库 → Settings → Secrets and variables → Actions"
echo "2. 添加这几个 secret："
echo "   MAIL_TO     = 你的收件邮箱"
echo "   MAIL_USER   = 发件邮箱"
echo "   MAIL_PASS   = 邮箱授权码"
echo "   DINGTALK_WEBHOOK = 钉钉webhook（可选）"
echo "3. 仓库 → Actions → 放水监控 → Run workflow 测试"
