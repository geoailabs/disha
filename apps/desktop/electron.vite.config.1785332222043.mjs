// electron.vite.config.ts
import { resolve } from "path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import react from "@vitejs/plugin-react";
var electron_vite_config_default = defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()]
  },
  preload: {
    plugins: [externalizeDepsPlugin()]
  },
  renderer: {
    resolve: {
      alias: {
        "@": resolve("src/renderer")
      }
    },
    plugins: [react()],
    optimizeDeps: {
      esbuildOptions: {
        target: "es2022"
      }
    },
    build: {
      target: "es2022"
    }
  }
});
export {
  electron_vite_config_default as default
};
