#!/usr/bin/env bash
# Push this repo to GitHub.
#
#   ./push-to-github.sh                 # 用已配置的 origin
#   ./push-to-github.sh <用户名> [仓库名]
#
# 会先让你确认署名（当前提交作者是占位值），再推送。
set -euo pipefail
cd "$(dirname "$0")"

USER_NAME="${1:-HWQ277}"
REPO_NAME="${2:-dsh-whale-linux}"

echo "当前提交作者：$(git log -1 --format='%an <%ae>')"
read -r -p "改成你的名字（留空则不改）: " NAME
if [[ -n "$NAME" ]]; then
  read -r -p "邮箱: " EMAIL
  git config user.name "$NAME"
  git config user.email "$EMAIL"
  git commit --amend --no-edit --reset-author -q
  echo "已改为：$(git log -1 --format='%an <%ae>')"
fi

git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${USER_NAME}/${REPO_NAME}.git"
echo
echo "推送到 https://github.com/${USER_NAME}/${REPO_NAME}"
echo "提示：密码处请填 Personal Access Token（不是账号密码）"
echo
git push -u origin main
echo
echo "完成： https://github.com/${USER_NAME}/${REPO_NAME}"
