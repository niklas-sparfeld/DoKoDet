import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const defaultApiProxyTarget = "http://127.0.0.1:8000";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget =
    process.env.VITE_API_PROXY_TARGET ??
    env.VITE_API_PROXY_TARGET ??
    defaultApiProxyTarget;

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/v1": {
          target: apiProxyTarget,
          changeOrigin: false,
        },
      },
    },
  };
});
