#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云剪贴板后端 (纯 Python3 标准库, 无第三方依赖)

基于「房间码」的多份剪贴板：
  - 创建页 POST /api/new 分配一个两位码 (小写字母 + 数字, 36^2 = 1296 个)
  - 内容存 data/<code>/text.txt 与 data/<code>/files/ (files 目录按需创建)
  - 创建 24h 后自动过期；后台线程每小时清理一次
  - 清空 = 删除目录并释放码

接口:
    GET    /hello                       健康检查
    POST   /api/new                     分配码 -> {"code": "ab"}
    GET    /api/<code>                  查看 -> {"text": "...", "files": [...]}
    PUT    /api/<code>/text             写文本 (不限长度)
    PUT    /api/<code>/files/<name>     上传文件 (<=100MB)
    GET    /api/<code>/files/<name>     下载文件
    DELETE /api/<code>                  清空 (删目录 + 释放码)
    DELETE /api/<code>/files/<name>     删除单个文件
    GET    / 或 /<code>                 返回前端 SPA
"""

import os
import sys
import json
import time
import random
import shutil
import threading
import mimetypes
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

HOST = os.environ.get('CLIPBOARD_HOST', '127.0.0.1')
PORT = int(os.environ.get('CLIPBOARD_PORT', '27150'))

MAX_FILE_SIZE = 100 * 1024 * 1024   # 100MB
TTL_SECONDS = 24 * 3600             # 24 小时
CLEAN_INTERVAL = 3600               # 1 小时

CODE_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789'
STATIC_FILES = ('/index.html', '/style.css', '/app.js', '/favicon.ico', '/favicon.svg')

ALLOC_LOCK = threading.Lock()


def is_valid_code(code):
    return len(code) == 2 and all(c in CODE_CHARS for c in code)


def is_expired(dirpath):
    try:
        return time.time() - os.path.getmtime(dirpath) > TTL_SECONDS
    except OSError:
        return True


def cleanup_expired():
    try:
        names = os.listdir(DATA_DIR)
    except FileNotFoundError:
        return
    now = time.time()
    for name in names:
        d = os.path.join(DATA_DIR, name)
        if not os.path.isdir(d):
            continue
        try:
            if now - os.path.getmtime(d) > TTL_SECONDS:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue


def cleanup_loop():
    while True:
        time.sleep(CLEAN_INTERVAL)
        try:
            cleanup_expired()
        except Exception:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = 'Clipboard/1.0'
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        sys.stderr.write('[%s] %s\n' % (self.log_date_time_string(), fmt % args))

    # ---------- 基础响应 ----------

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, status=200):
        body = text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.end_headers()

    # ---------- 请求体处理 ----------

    def _read_body_to_file(self, dest, limit=None):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length < 0:
            length = 0
        if limit is not None and length > limit:
            self.close_connection = True
            return 0, 413

        tmp = dest + '.tmp'
        total = 0
        try:
            f = open(tmp, 'wb')
        except OSError:
            return 0, 500

        try:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                total += len(chunk)
                if limit is not None and total > limit:
                    self.close_connection = True
                    return 0, 413
                f.write(chunk)
                remaining -= len(chunk)
            f.close()
            os.replace(tmp, dest)
            return total, 200
        except Exception:
            return 0, 500
        finally:
            try:
                f.close()
            except Exception:
                pass
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ---------- 路由 ----------

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == '/hello':
            return self._hello()
        if path.startswith('/api/'):
            return self._api_get(path[len('/api/'):])
        return self._serve_static(path)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == '/api/new':
            return self._new_clip()
        return self._send_empty(404)

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/api/'):
            return self._api_put(path[len('/api/'):])
        return self._send_empty(404)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/api/'):
            return self._api_delete(path[len('/api/'):])
        return self._send_empty(404)

    # ---------- 健康检查 ----------

    def _hello(self):
        self._send_json({'hello': 'world'})

    # ---------- 码解析 / 目录 ----------

    def _code_dir(self, code):
        return os.path.join(DATA_DIR, code)

    def _split_code(self, rest):
        if not rest:
            return None, None
        parts = rest.split('/', 1)
        code = parts[0]
        if not is_valid_code(code):
            return None, None
        sub = parts[1] if len(parts) > 1 else None
        return code, sub

    def _ensure_alive(self, code):
        """码存在且未过期返回 True；过期则删除并返回 False。"""
        d = self._code_dir(code)
        if not os.path.isdir(d):
            return False
        if is_expired(d):
            shutil.rmtree(d, ignore_errors=True)
            return False
        return True

    # ---------- 创建 ----------

    def _allocate_code(self):
        for _ in range(60):
            code = ''.join(random.choices(CODE_CHARS, k=2))
            d = self._code_dir(code)
            if not os.path.isdir(d):
                return code
            if is_expired(d):
                shutil.rmtree(d, ignore_errors=True)
                return code
        return None

    def _new_clip(self):
        with ALLOC_LOCK:
            code = self._allocate_code()
            if code is None:
                return self._send_json({'error': 'no free code available'}, 503)
            try:
                os.makedirs(self._code_dir(code))
            except OSError:
                return self._send_json({'error': 'create failed'}, 500)
        self._send_json({'code': code})

    # ---------- 查看 / 文本 / 文件 ----------

    def _api_get(self, rest):
        code, sub = self._split_code(rest)
        if code is None:
            return self._send_empty(404)
        if sub is None:
            return self._view_clip(code)
        if sub.startswith('files/'):
            return self._download_file(code, sub[len('files/'):])
        return self._send_empty(404)

    def _api_put(self, rest):
        code, sub = self._split_code(rest)
        if code is None:
            return self._send_empty(404)
        if not self._ensure_alive(code):
            return self._send_empty(404)
        if sub == 'text':
            return self._put_text(code)
        if sub and sub.startswith('files/'):
            return self._upload_file(code, sub[len('files/'):])
        return self._send_empty(404)

    def _api_delete(self, rest):
        code, sub = self._split_code(rest)
        if code is None:
            return self._send_empty(404)
        if sub is None:
            return self._clear_clip(code)
        if sub.startswith('files/'):
            return self._delete_file(code, sub[len('files/'):])
        return self._send_empty(404)

    def _view_clip(self, code):
        if not self._ensure_alive(code):
            return self._send_empty(404)
        d = self._code_dir(code)
        text = ''
        try:
            with open(os.path.join(d, 'text.txt'), 'r', encoding='utf-8') as f:
                text = f.read()
        except FileNotFoundError:
            pass
        self._send_json({'text': text, 'files': self._list_files(code)})

    def _put_text(self, code):
        dest = os.path.join(self._code_dir(code), 'text.txt')
        _, err = self._read_body_to_file(dest, limit=None)
        self._send_empty(err if err != 200 else 200)

    def _list_files(self, code):
        d = os.path.join(self._code_dir(code), 'files')
        items = []
        try:
            names = os.listdir(d)
        except FileNotFoundError:
            return items
        for name in names:
            fp = os.path.join(d, name)
            if os.path.isfile(fp):
                st = os.stat(fp)
                items.append({
                    'name': name,
                    'type': 'file',
                    'mtime': datetime.fromtimestamp(st.st_mtime).isoformat(),
                    'size': st.st_size,
                })
        items.sort(key=lambda x: x['mtime'], reverse=True)
        return items

    def _upload_file(self, code, raw_name):
        name = os.path.basename(urllib.parse.unquote(raw_name))
        if not name or name in ('.', '..'):
            return self._send_empty(400)
        files_dir = os.path.join(self._code_dir(code), 'files')
        os.makedirs(files_dir, exist_ok=True)  # 只在真正上传时创建
        dest = os.path.join(files_dir, name)
        _, err = self._read_body_to_file(dest, limit=MAX_FILE_SIZE)
        if err == 413:
            return self._send_text('file too large (max 100MB)', 413)
        if err == 500:
            return self._send_empty(500)
        self._send_empty(200)

    def _download_file(self, code, raw_name):
        if not self._ensure_alive(code):
            return self._send_empty(404)
        name = os.path.basename(urllib.parse.unquote(raw_name))
        fp = os.path.join(self._code_dir(code), 'files', name)
        if not os.path.isfile(fp):
            return self._send_empty(404)
        ctype, _ = mimetypes.guess_type(name)
        if ctype is None:
            ctype = 'application/octet-stream'
        size = os.path.getsize(fp)
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(size))
        self.end_headers()
        with open(fp, 'rb') as f:
            shutil.copyfileobj(f, self.wfile)

    def _clear_clip(self, code):
        d = self._code_dir(code)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        self._send_empty(200)

    def _delete_file(self, code, raw_name):
        name = os.path.basename(urllib.parse.unquote(raw_name))
        try:
            os.remove(os.path.join(self._code_dir(code), 'files', name))
        except FileNotFoundError:
            pass
        self._send_empty(200)

    # ---------- 静态页面 ----------

    def _serve_static(self, path):
        if path == '/':
            path = '/index.html'
        elif is_valid_code(path.strip('/')):
            # /<code> 查看页，返回同一个 SPA，由前端读路径判断模式
            path = '/index.html'
        if path not in STATIC_FILES:
            return self._send_empty(404)
        fp = os.path.join(BASE_DIR, path.lstrip('/'))
        if not os.path.isfile(fp):
            return self._send_empty(404)
        ctype, _ = mimetypes.guess_type(fp)
        if ctype is None:
            ctype = 'application/octet-stream'
        with open(fp, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    t = threading.Thread(target=cleanup_loop, daemon=True)
    t.start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print('Cloud clipboard listening on http://%s:%d' % (HOST, PORT), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
