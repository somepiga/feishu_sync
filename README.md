# 飞书文档 → GitHub Pages 同步

自动将飞书文档同步到 GitHub Pages 的静态站点。

## 功能

- 自动获取飞书文件夹中的所有文档
- 转换为统一的 JSON 格式
- 增量同步（只同步有变化的文档）
- 支持手动触发和定时同步（每天凌晨 2 点）
- GitHub Actions 全自动部署

## 你需要配置的部分

### 1. 创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 点击「创建应用」→ 填写应用名称
3. 在「凭证与基础信息」中获取：
   - `App ID`
   - `App Secret`

4. 在「权限管理」中开通：
   - `docx.document:readonly`
   - `docx.document.meta:readonly`

5. 在「版本管理与发布」中创建版本并发布

### 2. 获取文件夹 Token

1. 在飞书中打开要同步的文件夹
2. 复制浏览器地址栏 URL：
   `https://xxxx.feishu.cn/drive/folder/xxxxxxxxxxxxxxxxxx`
3. `xxxxxxxxxxxxxxxxxx` 就是 `folder_token`

### 3. 分享文档给应用

1. 在飞书中右键目标文件夹 → 「分享」→ 「邀请链接」
2. 选择刚创建的应用，授予读取权限

### 4. 创建 GitHub 仓库

1. 在 GitHub 创建新仓库（如 `feishu-sync`）
2. 本地已初始化 git，直接推送：

```bash
git remote add origin https://github.com/YOUR_USERNAME/feishu-sync.git
git branch -M main
git push -u origin main
```

### 5. 配置 GitHub Secrets

在仓库页面 → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`：

| Secret 名称 | 值 |
|------------|-----|
| `FEISHU_APP_ID` | 第 1 步获取的 App ID |
| `FEISHU_APP_SECRET` | 第 1 步获取的 App Secret |
| `FEISHU_WIKI_TOKEN` | 第 2 步获取的 Wiki 节点 Token |

### 6. 启用 GitHub Pages

1. 仓库 `Settings` → `Pages`
2. Source 选择 `gh-pages` 分支（或 `main` + `/docs`）
3. 保存

### 7. 首次测试

1. 在 GitHub 仓库页面 → `Actions` → 选择 `Sync Feishu Docs`
2. 点击 `Run workflow` → `Run workflow`
3. 查看运行日志确认无错误

## 同步后的文档格式

```json
{
  "id": "doc_token",
  "title": "文档标题",
  "updated_at": "2024-01-01T12:00:00",
  "raw_content": "文档的纯文本内容",
  "blocks": []
}
```

## 目录结构

```
.
├── .github/workflows/sync.yml   # 同步工作流
├── scripts/
│   ├── fetch_docs.py            # 获取飞书文档
│   ├── convert.py               # 格式转换
│   ├── sync.py                  # 同步主脚本
│   └── requirements.txt         # Python 依赖
├── content/documents/           # 同步后的文档（自动生成）
└── docs/                        # GitHub Pages 源（你自定义前端）
```

## 自定义前端

在 `docs/` 目录下开发你的前端，读取 `content/documents/` 中的 JSON 数据进行展示。

## 手动本地测试

```bash
cd scripts
pip install -r requirements.txt
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_app_secret"
export FEISHU_FOLDER_TOKEN="your_folder_token"
python sync.py
```
