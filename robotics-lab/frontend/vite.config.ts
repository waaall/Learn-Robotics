// 开发页面通过应用网关访问课程与查看器，保持与生产部署相同的同源协议。
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL("..", import.meta.url)), "ROBOTICS_LAB_");
  const target = `http://127.0.0.1:${env.ROBOTICS_LAB_PORT || "18320"}`;
  const proxy = Object.fromEntries(
    ["/api", "/viewer", "/assets", "/model", "/ui", "/state", "/drop"].map(
      (path) => [path, { target, ws: ["/ui", "/state", "/drop"].includes(path) }],
    ),
  );
  return {
    plugins: [react()],
    // 官方客户端使用 /assets，课程构建资源使用独立目录。
    build: { assetsDir: "lab-assets" },
    server: {
      host: "127.0.0.1",
      headers: {
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Embedder-Policy": "require-corp",
      },
      proxy,
    },
  };
});
