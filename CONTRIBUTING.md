# 贡献指南

感谢你考虑为 LongFiction-AI 做出贡献！我们欢迎所有形式的贡献，包括但不限于：

- 🐛 报告 Bug
- 💡 提出新功能
- 📝 改进文档
- 🔧 提交代码修复
- ✨ 实现新功能
- 🧪 编写测试

## 📋 行为准则

- 尊重所有贡献者
- 接受建设性批评
- 关注对项目最有利的事情
- 对新贡献者保持耐心

## 🚀 快速开始

### 1. Fork 仓库

点击 GitHub 页面右上角的 Fork 按钮。

### 2. 克隆你的 Fork

```bash
git clone https://github.com/your-username/longfiction-ai.git
cd longfiction-ai
```

### 3. 创建分支

```bash
git checkout -b feature/your-feature-name
# 或
git checkout -b fix/your-bug-fix
```

### 4. 设置开发环境

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 安装开发工具
pip install pytest black flake8 mypy pre-commit
```

### 5. 进行修改

确保你的代码符合以下要求：
- 通过 `black .` 格式化
- 通过 `flake8 .` 检查
- 通过 `mypy .` 类型检查
- 添加适当的测试
- 更新相关文档

### 6. 提交修改

```bash
git add .
git commit -m "feat: add new feature"
# 或
git commit -m "fix: resolve bug in chapter generation"
```

我们使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

- `feat:` - 新功能
- `fix:` - Bug 修复
- `docs:` - 文档变更
- `style:` - 代码风格（不影响功能）
- `refactor:` - 重构
- `test:` - 添加测试
- `chore:` - 构建/工具变更

### 7. 推送到你的 Fork

```bash
git push origin feature/your-feature-name
```

### 8. 创建 Pull Request

在 GitHub 上创建 Pull Request，填写 PR 模板。

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_writer_agent.py

# 带覆盖率
pytest --cov=. tests/
```

## 📁 项目结构

请熟悉以下目录：

- `agents/` - 8 个核心 Agent
- `core/` - 核心基础设施
- `memory/` - 记忆系统
- `api/` - REST 端点
- `web/` - 前端
- `tests/` - 测试

## 🎯 贡献方向

我们特别欢迎以下方向的贡献：

### 短期（P0）
- 修复 Bug 和稳定性问题
- 改进错误处理
- 添加单元测试

### 中期（P1）
- 实现流式输出
- 多模型路由
- RAG 2.0 增强
- 字数控制算法优化

### 长期（P2）
- 风格学习与迁移
- 强化学习反馈
- 协作编辑

## 📞 联系方式

- **GitHub Issues**: 报告 Bug 或请求功能
- **GitHub Discussions**: 一般性问题讨论

## 📄 许可证

通过贡献代码，你同意你的贡献将根据 [MIT 许可证](LICENSE) 进行许可。
