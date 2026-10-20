// 复用项目的 TS/TSX 转换加载实际前端模块；测试不监听端口，也不启动文件监视。
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

export async function loadFrontendModule(path) {
  const server = await createServer({
    root: fileURLToPath(new URL("../..", import.meta.url)),
    configFile: false,
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false, watch: null },
  });
  try {
    return { module: await server.ssrLoadModule(path), close: () => server.close() };
  } catch (error) {
    await server.close();
    throw error;
  }
}
