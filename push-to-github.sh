#!/usr/bin/env bash
# One-shot publisher for the DeepSeek whale widget.
#
#   1. Create an EMPTY repo on GitHub (no README, no .gitignore, no licence).
#   2. Run:  ./push-to-github.sh <你的用户名> <仓库名> [你的名字] [你的邮箱]
#
# Example:
#   ./push-to-github.sh hwq dsh-whale-linux "张三" "zhangsan@example.com"
set -euo pipefail

USER_NAME="${1:?用法: ./push-to-github.sh <用户名> <仓库名> [名字] [邮箱]}"
REPO_NAME="${2:?用法: ./push-to-github.sh <用户名> <仓库名> [名字] [邮箱]}"
AUTHOR_NAME="${3:-}"
AUTHOR_EMAIL="${4:-}"

cd "$(dirname "$0")"

if [[ -n "$AUTHOR_NAME" && -n "$AUTHOR_EMAIL" ]]; then
  echo "==> 设置提交署名: $AUTHOR_NAME <$AUTHOR_EMAIL>"
  git config user.name "$AUTHOR_NAME"
  git config user.email "$AUTHOR_EMAIL"
  # Rewrite the existing commit so the placeholder author is replaced.
  git commit --amend --no-edit --reset-author -q
fi

REMOTE="https://github.com/${USER_NAME}/${REPO_NAME}.git"
echo "==> remote -> $REMOTE"
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE"

echo "==> 推送中（会提示输入 GitHub 用户名 + Personal Access Token）"
git push -u origin main

echo
echo "完成： https://github.com/${USER_NAME}/${REPO_NAME}"
