#!/usr/bin/env bash
# 生成 nginx HTTP Basic 口令文件（方案 a）。
# 用法：
#   bash scripts/gen_htpasswd.sh <用户名> [输出文件]
# 默认输出到 deploy/.htpasswd（已被 .gitignore 忽略，不会入仓）。
# 会交互式提示输入密码。生成后把该文件部署到 nginx 的 auth_basic_user_file 路径。
set -euo pipefail

USER_NAME="${1:-}"
OUT_FILE="${2:-deploy/.htpasswd}"

if [[ -z "$USER_NAME" ]]; then
  echo "用法: bash scripts/gen_htpasswd.sh <用户名> [输出文件]" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT_FILE")"

read -r -s -p "为用户 '$USER_NAME' 设置密码: " PASS1; echo
read -r -s -p "再次输入确认: " PASS2; echo
if [[ "$PASS1" != "$PASS2" ]]; then
  echo "两次输入不一致" >&2
  exit 1
fi

if command -v htpasswd >/dev/null 2>&1; then
  # apache2-utils 提供 htpasswd，-B 用 bcrypt
  htpasswd -B -b -c "$OUT_FILE" "$USER_NAME" "$PASS1"
else
  # 无 htpasswd 时退回 openssl apr1（nginx 兼容）
  HASH="$(openssl passwd -apr1 "$PASS1")"
  printf '%s:%s\n' "$USER_NAME" "$HASH" > "$OUT_FILE"
fi

chmod 600 "$OUT_FILE"
echo "已写入 $OUT_FILE"
echo "下一步：将其拷到 nginx auth_basic_user_file 指向的路径（如 /etc/nginx/tobacco.htpasswd）并 reload。"
