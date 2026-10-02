#!/usr/bin/env bash
# 登录 GitHub 并推送。token 存进系统 keyring，不落明文、不进 shell 历史。
set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1. 登录 GitHub ==="
echo "    会给你一个 8 位设备码，在浏览器里输入即可。"
echo "    选 HTTPS，并按提示用 git 凭证。"
echo
gh auth login --hostname github.com --git-protocol https --web

echo
echo "=== 2. 让 git 用 gh 作为凭证助手 ==="
gh auth setup-git
git remote set-url origin https://github.com/HWQ277/dsh-whale-linux.git

echo
echo "=== 3. 改成你的署名（回车跳过） ==="
read -r -p "名字: " NAME
if [[ -n "$NAME" ]]; then
  read -r -p "邮箱: " EMAIL
  git config user.name "$NAME"
  git config user.email "$EMAIL"
  git commit --amend --no-edit --reset-author -q
fi

echo
echo "=== 4. 推送 ==="
git push -u origin main

echo
echo "完成: https://github.com/HWQ277/dsh-whale-linux"
