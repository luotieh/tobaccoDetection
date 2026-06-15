# 部署：内部试点鉴权（方案 a — 反向代理 HTTP Basic）

对应《上线前任务优化书》P0-5。管理端本身无登录态，通过在其前面套一层反向代理 + HTTP Basic，
让内部试点的真实用户必须输入账号密码才能访问。**应用代码零改动**，最快可用。

## 架构

```
用户浏览器 ──HTTP Basic──> nginx/Caddy(:8443) ──proxy──> 管理端(127.0.0.1:8000)
                                                              ├─> 视觉服务 127.0.0.1:9000
                                                              ├─> 文本服务 127.0.0.1:8010
                                                              └─> 语音服务 127.0.0.1:8020
```

对外只暴露代理端口（示例 8443）；管理端与三个微服务都只绑定 `127.0.0.1`，不直接对网暴露。

## 步骤

### 1. 让服务只监听回环地址
编辑 `.env`（参考 `.env.example`），把对外不需要直连的服务绑定到本机：

```bash
MANAGEMENT_HOST=127.0.0.1     # 管理端只允许代理访问（app.py 已支持该环境变量）
HOST=127.0.0.1                # 视觉服务
TEXT_HOST=127.0.0.1           # 文本服务
AUDIO_HOST=127.0.0.1          # 语音服务
```

然后 `bash scripts/start_all.sh` 重启。

> 注意：单机试点用回环即可。若代理与服务不在同一台机器，则改绑内网网段并用防火墙限制来源。

### 2. 生成口令文件

```bash
bash scripts/gen_htpasswd.sh admin
# 交互输入密码，产出 deploy/.htpasswd（已被 .gitignore 忽略，不会入仓）
```

### 3a. 用 nginx
- 把 `deploy/.htpasswd` 拷到 nginx 主机的 `/etc/nginx/tobacco.htpasswd`。
- 引入 `deploy/nginx.conf`（放进 `conf.d/` 或 `include`），`nginx -t && nginx -s reload`。
- 访问 `http://<主机>:8443/`，浏览器弹出账号密码框。

### 3b. 或用 Caddy（更简单，可自动 HTTPS）

```bash
caddy hash-password --plaintext '你的密码'   # 复制输出的 bcrypt 哈希
# 填入 deploy/Caddyfile 的 basicauth 哈希处
caddy run --config deploy/Caddyfile
```

把 `:8443` 改成域名（如 `admin.example.com`）即可让 Caddy 自动签发 TLS 证书。

## 验收
- 不带凭据访问代理端口 → 返回 `401 Unauthorized`。
- 带正确账号密码 → 正常进入管理端，所有页面/接口可用。
- 直接访问 `127.0.0.1:8000` 仅限本机；外部无法绕过代理。
- 上传超过 200MB 被代理 `client_max_body_size` 或应用层 413 拦截。

## 后续演进
试点稳定后，可按《上线前任务优化书》P2 / `NEXT_OPTIMIZATION_PLAN.md` 任务 4.1
升级为应用内「用户表 + 登录 + 角色 + 审计日志」，实现按人归属的细粒度权限。
