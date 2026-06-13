# wenyan-web

一个轻量的本地 Web 小工具：输入现代语境下想表达的话，让大模型生成带有古意、但仍然适合直接发送的中文回应。

## 功能

- 提供 `V1` 极简界面和 `V2` 双栏界面
- 支持 `OpenAI` 兼容、`Gemini`、`Anthropic` 三类接口
- 支持在页面内保存 `API Type`、`API Base`、`Model`
- 支持历史记录、范例输入、结果复制

## 运行

```bash
python server.py
```

启动后可访问：

- `http://127.0.0.1:8765/V2`：卡片面板
- `http://127.0.0.1:8765/V1`：极简版本

## 配置

有两种方式：

1. 直接编辑 `apikey.py`
2. 在页面中填写配置后点击“保存配置”

页面保存后会写回 `apikey.py`，并立即更新当前服务进程的默认配置。

## 项目结构

- `server.py`：HTTP 服务与不同模型接口的适配层
- `apikey.py`：默认配置与配置持久化逻辑
- `style_prompt.py`：提示词模板
- `frontend_v1.html`：极简界面
- `frontend_v2.html`：双栏界面

## 说明

- 默认使用 Python 标准库，无额外依赖
- `API Key` 不会通过 `/api/config` 接口明文返回到前端
