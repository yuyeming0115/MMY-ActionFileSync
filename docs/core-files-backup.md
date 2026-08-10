# 核心文件备份清单

以下内容建议纳入仓库或单独备份，作为“可恢复项目核心逻辑”的最小集合。

## 必备源码

- `main.py`
- `requirements.txt`
- `adapters/`
- `controllers/`
- `models/`
- `services/`
- `utils/`
- `views/`
- `workers/`
- `assets/icon.ico`

## 建议保留文档

- `README.md`
- `docs/`

## 通常不建议上传的大体积或本地产物

- `.venv/`
- `.venv-build/`
- `.pydeps/`
- `.cache/`
- `__pycache__/`
- `build/`
- `dist/`
- `release/`
- `*.spec` 是否保留，取决于你是否要一起维护打包配置

## 如果只做最小源码备份

至少保留以下内容：

```text
main.py
requirements.txt
adapters/
controllers/
models/
services/
utils/
views/
workers/
assets/
README.md
```
