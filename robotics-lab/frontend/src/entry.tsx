// 浏览器挂载入口与应用组件分离，便于直接测试实际应用的网络和会话操作。
import { createRoot } from "react-dom/client";
import "katex/dist/katex.min.css";
import "./style.css";
import { App } from "./main";

createRoot(document.getElementById("root")!).render(<App />);
