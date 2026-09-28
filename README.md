# 云剪贴板 Cloud Clipboard

跨设备复制粘贴，文本 / 图片 / 文件，一个链接搞定。

在电脑 A 上创建一条剪贴板，得到一个形如 `https://paste.example.com/a7` 的短链接；在手机或另一台电脑上打开这个链接，即可读取内容，用完点「清空」即焚。

我已部署的 demo: https://paste.940304.xyz

## 产品特色

- **一个链接，一份内容** —— 基于「房间码」的多份剪贴板，不同链接之间互不干扰，最多同时 1296 份。
- **文本不限长度** —— 长文档、日志、代码，想传多少传多少。
- **图片 / 文件 ≤ 100MB** —— 拖拽、点击或直接粘贴图片即可上传。
- **短码易输入** —— 两位小写字母 + 数字（`a7`、`9k`…），在另一台设备手输 URL 也不费劲。
- **自动过期，即焚即清** —— 内容 24 小时后自动删除，后台每小时清理；点「清空」立即删除并释放链接。
- **零依赖后端** —— 纯 Python3 标准库实现，无需 pip、无需数据库，一个文件跑起来。

## 架构

```
浏览器 ──HTTPS──> nginx ──proxy──> Python3 (server.py, 127.0.0.1:27150)
                                    └── data/<code>/text.txt
                                        data/<code>/files/
```

- `server.py`：无框架的 Python 后端，负责分配码、读写文本/文件、过期清理。
- `index.html` / `style.css` / `app.js`：单页前端，根据路径自动切换「创建页 / 查看页」。
- `nginx-paste.conf`：反向代理 + HTTPS 终止（SSL 证书复用 acme 通配证书）。
- `clipboard.service`：systemd 服务单元，守护后端进程。

## 目录结构

```
cloud-clipboard/
├── server.py          # 后端服务（Python3 标准库）
├── index.html         # 前端页面
├── style.css          # 样式
├── app.js             # 交互逻辑
├── favicon.svg        # 网站图标
├── nginx-paste.conf   # nginx 配置（放到 /etc/nginx/sites-enabled/）
└── clipboard.service  # systemd 服务（放到 /etc/systemd/system/）
```

## 部署

> 以域名 `paste.example.com`、目录 `/srv/clipboard` 为例。

```bash
# 1. DNS 添加记录：paste -> 服务器 IP

# 2. 放置文件并授权（服务以 dk 运行）
sudo mkdir -p /srv/clipboard
sudo cp server.py index.html style.css app.js favicon.svg /srv/clipboard/
sudo chown -R dk:dk /srv/clipboard

# 3. 安装并启动 systemd 服务
sudo cp clipboard.service /etc/systemd/system/clipboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now clipboard

# 4. 配置并重载 nginx
sudo cp nginx-paste.conf /etc/nginx/sites-enabled/paste.conf
sudo nginx -t && sudo systemctl reload nginx
```

> 换域名：改 `nginx-paste.conf` 里的 `server_name` 与证书路径即可。

## 使用方式

1. 打开 `https://paste.example.com/`，输入文本（或拖入文件），点「创建剪贴板」。
2. 页面生成短链接并自动复制，把它发到另一台设备。
3. 另一台设备打开该链接，即可读取文本、下载文件。
4. 用完点「清空」，内容即刻删除。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/hello` | 健康检查，返回 `{"hello":"world"}` |
| POST | `/api/new` | 分配码，返回 `{"code":"a7"}` |
| GET | `/api/<code>` | 查看，返回 `{"text":"...","files":[...]}` |
| PUT | `/api/<code>/text` | 写入文本（不限长度） |
| PUT | `/api/<code>/files/<name>` | 上传文件（≤100MB） |
| GET | `/api/<code>/files/<name>` | 下载文件 |
| DELETE | `/api/<code>` | 清空（删除目录并释放码） |
| DELETE | `/api/<code>/files/<name>` | 删除单个文件 |

## 排障

```bash
systemctl status clipboard --no-pager     # 服务状态
journalctl -u clipboard -n 30 --no-pager  # 日志
curl -s http://127.0.0.1:27150/hello      # 健康检查
```

## 说明

- 数据存于 `data/` 目录，服务启动时自动创建。
- 过期时长固定 24 小时，清理线程每小时扫描一次。
- 房间码可被枚举（1296 个），定位是「轻度隔离」，不适用于需要强隐私的场景。
- 无需注册登录，免费使用无广告，但请规范使用。
