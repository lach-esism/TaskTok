# TaskTok 队友交接

更新日期：2026-11-13

## 1. 可直接访问的网站

- HTTPS 演示地址：`https://245b0a632342c0.app.lhr.life/`
- HTTP 稳定入口：`http://62.234.154.212/`
- 进化实验：`https://245b0a632342c0.app.lhr.life/?view=lab&preview=v2`

HTTPS 使用 SSH 反向隧道。隧道重启后域名可能变化，不代表源码或服务器失效。

在服务器上读取当前 HTTPS 地址：

```bash
sudo journalctl -u evomatch-tunnel.service --no-pager |
  grep -o 'https://[^ ]*app.lhr.life' |
  tail -1
```

## 2. 源码位置

本机：

```text
F:\Codex自留\evomatch
```

服务器：

```text
/home/agent/repos/evomatch-baseline
```

主要文件：

```text
index.html
styles.css
src/app.js
src/data.js
src/router-engine.js
tests/router-engine.test.js
README.md
```

这是一个零 npm 依赖的静态网站。浏览器代码和 Node 测试共享同一份路由引擎。

## 3. 服务器连接信息

如果队友只需要修改静态代码，推荐先给他一个私有 Git 仓库，不需要开放服务器。

如果确实需要直接改服务器，向他提供：

```text
SSH URI: ssh://agent@62.234.154.212:22
项目目录: /home/agent/repos/evomatch-baseline
```

让他生成自己的 SSH 密钥，并且只把他的 `.pub` 公钥发给你：

```bash
ssh-keygen -t ed25519 -C "teammate-name"
cat ~/.ssh/id_ed25519.pub
```

你把公钥加入服务器 `agent` 用户的 `authorized_keys`。不要把服务器的私钥、密码、API Key、Webhook 或 token 发给队友。

## 4. 运行与测试

本地或服务器：

```bash
cd /home/agent/repos/evomatch-baseline
npm test
npm start
```

默认本地地址：

```text
http://127.0.0.1:4173
```

服务器内部：

- `evomatch-baseline.service`：用户服务，监听 `127.0.0.1:4173`
- `evomatch-baseline-web.service`：systemd 服务，监听公网 HTTP `80`
- `evomatch-tunnel.service`：提供临时 HTTPS 地址

当前网站是静态文件，修改 HTML/CSS/JS 后刷新即可，不需要构建。服务重启命令需要 `ubuntu` 用户的 sudo 权限。

## 5. 修改后必须保持的能力

1. v1 必须仍能复现 T3、T4、T6 三个合理误分。
2. v2 必须保持校准集 8/8、隐藏集 4/4。
3. 高风险任务必须覆盖 C 合规预审和人工复核节点。
4. 学习函数不能读取隐藏任务标签。
5. 回滚后 v1 排名和指标必须恢复，恢复 v2 后结果一致。
6. `npm test` 必须全部通过。
7. 默认用户入口仍是极简首页，并保持首页、任务、我的、实验四个页面分开。

## 6. 推荐交付方式

最推荐顺序：

1. 创建私有 Git 仓库并让队友提交 Pull Request。
2. 你在本地或测试服务器跑 `npm test`。
3. 验收后再同步到 `/home/agent/repos/evomatch-baseline`。
4. 最后刷新线上页面检查桌面和手机尺寸。

只有在需要多人直接维护同一台服务器时，才给 `agent` 用户 SSH 权限；`ubuntu` 是管理员账号，不需要时不要提供。
