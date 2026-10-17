import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // MuJoCo WebViewer 使用根路径 /assets；应用资源使用独立目录。
  build: { assetsDir: "lab-assets" },
  server: { host: "127.0.0.1", proxy: { "/api": "http://127.0.0.1:8000" } },
});
