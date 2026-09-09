# 学有所径 · 前端

React 19 + TypeScript + Vite。页面与统一 API 类型自 T03/T08 起实现（规格书 §13/§14）。

## 命令

```bash
npm install    # 安装依赖（版本锁定见 package-lock.json）
npm run dev    # 开发服务器，http://localhost:5174（strictPort；5173 留给本机其他项目）
npm run build  # tsc -b 类型检查 + 生产构建
npm run lint   # oxlint
```

后端启动方式见仓库根 README；跨域白名单由 `.env.example` 中的 `FRONTEND_DEV_URL` 控制。
