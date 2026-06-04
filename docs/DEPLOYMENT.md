# 部署指南

本文档介绍 LongFiction-AI 在不同环境下的部署方式。

## 📋 部署前检查

### 系统要求

| 组件 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 2 核 | 4 核+ |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 5 GB | 20 GB+ |
| Python | 3.10 | 3.11+ |
| 网络 | 稳定的国际互联网 | - |

### 依赖检查

```bash
# Python 版本
python --version

# pip 版本
pip --version

# Git
git --version
```

## 🚀 快速部署

### 方式一：本地部署（开发/小规模）

```bash
# 1. 克隆仓库
git clone https://github.com/liu020800/longfiction-ai.git
cd longfiction-ai

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境
cp .env.example .env
nano .env  # 编辑 API Key 等

# 5. 启动服务
python main.py
```

服务将在 `http://localhost:8000` 启动。

### 方式二：Docker 部署（生产推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/liu020800/longfiction-ai.git
cd longfiction-ai

# 2. 配置环境
cp .env.example .env
nano .env

# 3. 构建并启动
docker-compose up -d

# 4. 查看日志
docker-compose logs -f

# 5. 停止服务
docker-compose down
```

### 方式三：systemd 服务（Linux 服务器）

```bash
# 1. 部署应用
sudo mkdir -p /opt/longfiction-ai
sudo cp -r . /opt/longfiction-ai/
cd /opt/longfiction-ai

# 2. 创建虚拟环境
sudo python -m venv venv
sudo venv/bin/pip install -r requirements.txt

# 3. 配置环境
sudo cp .env.example .env
sudo nano .env

# 4. 安装 systemd 服务
sudo cp deploy/longfiction-ai.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable longfiction-ai
sudo systemctl start longfiction-ai

# 5. 查看状态
sudo systemctl status longfiction-ai
```

## 🔧 生产环境配置

### 使用 PostgreSQL

1. 安装 PostgreSQL：
```bash
# Ubuntu/Debian
sudo apt install postgresql postgresql-contrib

# CentOS/RHEL
sudo yum install postgresql postgresql-server
```

2. 创建数据库和用户：
```sql
CREATE DATABASE longfiction;
CREATE USER longfiction_user WITH PASSWORD 'your-secure-password';
GRANT ALL PRIVILEGES ON DATABASE longfiction TO longfiction_user;
```

3. 修改 `.env`：
```env
DATABASE_URL=postgresql://longfiction_user:your-secure-password@localhost:5432/longfiction
```

4. 运行迁移：
```bash
alembic upgrade head
```

### 使用 Nginx 反向代理

`/etc/nginx/sites-available/longfiction`：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 流式输出支持
        proxy_buffering off;
        proxy_cache off;
    }

    location /static/ {
        alias /opt/longfiction-ai/web/;
        expires 30d;
    }
}
```

启用配置：
```bash
sudo ln -s /etc/nginx/sites-available/longfiction /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### HTTPS 配置（Let's Encrypt）

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## 🔐 安全加固

### 1. 修改默认密码

`.env`：
```env
ADMIN_PASSWORD=your-very-strong-password-here
```

### 2. 配置 JWT 密钥

`.env`：
```env
JWT_SECRET_KEY=your-jwt-secret-key-min-32-chars
```

### 3. 防火墙配置

```bash
# 仅开放必要端口
sudo ufw allow 22/tcp     # SSH
sudo ufw allow 80/tcp     # HTTP
sudo ufw allow 443/tcp    # HTTPS
sudo ufw enable
```

### 4. 限制 CORS

修改 `api/main.py`：
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-domain.com"],  # 替换为实际域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 📊 监控与日志

### 日志位置

- 应用日志：`logs/detail.log`
- 错误日志：`logs/error.log`
- LLM 调用日志：`logs/llm.log`

### 日志轮转

`/etc/logrotate.d/longfiction`：

```
/opt/longfiction-ai/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 www-data www-data
    sharedscripts
    postrotate
        systemctl reload longfiction-ai
    endscript
}
```

### 进程监控（systemd）

服务会自动重启失败的进程。

查看状态：
```bash
sudo systemctl status longfiction-ai
```

## 🔄 升级与维护

### 拉取最新代码

```bash
cd /opt/longfiction-ai
sudo git pull origin main
sudo venv/bin/pip install -r requirements.txt
sudo systemctl restart longfiction-ai
```

### 备份数据

```bash
# 备份 SQLite
sudo cp data/novel.db data/novel.db.backup.$(date +%Y%m%d)

# 备份 PostgreSQL
sudo pg_dump longfiction > backup_$(date +%Y%m%d).sql

# 备份会话数据
sudo tar -czf sessions_backup_$(date +%Y%m%d).tar.gz data/sessions/
```

### 恢复数据

```bash
# 恢复 SQLite
sudo cp data/novel.db.backup.YYYYMMDD data/novel.db

# 恢复 PostgreSQL
sudo psql longfiction < backup_YYYYMMDD.sql
```

## 🐛 故障排查

### 服务无法启动

```bash
# 查看日志
sudo journalctl -u longfiction-ai -n 100

# 检查端口
sudo netstat -tlnp | grep 8000

# 手动启动测试
cd /opt/longfiction-ai
source venv/bin/activate
python main.py
```

### LLM 调用失败

1. 检查 API Key 是否正确
2. 检查网络连接：
   ```bash
   curl -X POST https://api.openai.com/v1/chat/completions \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
   ```
3. 检查超时设置：`LLM_TIMEOUT_SECONDS`

### 数据库错误

```bash
# 检查数据库连接
sqlite3 data/novel.db "SELECT COUNT(*) FROM projects;"

# 运行迁移
alembic upgrade head
```

## 📈 性能调优

### 1. 启用 Redis 缓存

```env
REDIS_URL=redis://localhost:6379/0
```

### 2. 调整并发数

修改 `api/main.py`：
```python
uvicorn.run(app, host="0.0.0.0", port=8000, workers=4)
```

### 3. 增加 LLM 超时

```env
LLM_TIMEOUT_SECONDS=180
```

### 4. 启用 FAISS GPU

```bash
pip install faiss-gpu
```

## 🌐 跨平台部署

### Windows

使用 `start_longfiction.bat`：
```cmd
start_longfiction.bat
```

### WSL2（推荐 Windows 部署方式）

项目根目录下的 `start_longfiction.bat` 会自动在 WSL Ubuntu 中启动服务。

### macOS

```bash
brew install python@3.11
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```
