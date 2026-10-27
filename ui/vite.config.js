import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Duas páginas, cada uma gerada na pasta que o Python já usa:
//   broadcaster → host/gui/ui (janela do Peek, aberta como arquivo local pelo QtWebEngine)
//   viewer      → web/        (página de quem assiste, servida pelo aiohttp em /static)
const APPS = {
  broadcaster: { outDir: "../../../host/gui/ui", base: "./" },
  viewer: { outDir: "../../../web", base: "/static/" },
};

// Em `npm run dev:viewer`, a página vem do Vite e a sinalização vai para o Peek rodando
// em outra janela (`python -m host --headless`).
const PEEK_DEV_SERVER = "http://localhost:8080";

export default defineConfig(({ command, mode }) => {
  if (!(mode in APPS)) throw new Error(`Use --mode ${Object.keys(APPS).join(" ou --mode ")}`);
  const app = APPS[mode];
  return {
    root: fileURLToPath(new URL(`src/${mode}`, import.meta.url)),
    base: command === "serve" ? "/" : app.base,
    plugins: [react()],
    server:
      mode === "viewer"
        ? { proxy: { "^/s/[^/]+/ws": { target: PEEK_DEV_SERVER, ws: true } } }
        : { port: 5173, strictPort: true },
    build: { outDir: app.outDir, emptyOutDir: true },
  };
});
