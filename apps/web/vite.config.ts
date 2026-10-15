import { defineConfig } from "vite-plus";

// OpenCode-inspired terminal aesthetic, implemented with native HTML and CSS.
export default defineConfig({
  lint: { options: { typeAware: true, typeCheck: true } },
  server: { port: 3000, strictPort: true },
  preview: { port: 3000, strictPort: true },
});
