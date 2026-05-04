import fs from "node:fs";
import path from "node:path";
import { defineConfig, loadEnv } from "vite";

const workspaceRoot = path.resolve(process.cwd(), "..");

function resolveExistingFile(filePath: string): string | undefined {
  const candidates = path.isAbsolute(filePath)
    ? [filePath]
    : [path.resolve(process.cwd(), filePath), path.resolve(workspaceRoot, filePath)];

  if (filePath.startsWith("/app/")) {
    candidates.push(path.resolve(process.cwd(), filePath.slice("/app/".length)));
  }

  return candidates.find((candidate) => fs.existsSync(candidate));
}

export default defineConfig(({ mode }) => {
  const env = {
    ...loadEnv(mode, workspaceRoot, ""),
    ...loadEnv(mode, process.cwd(), ""),
    ...process.env
  };
  const useHttps = env.DEV_HTTPS === "true";

  let https: { key: Buffer; cert: Buffer } | undefined;
  if (useHttps) {
    const keyFile = env.DEV_HTTPS_KEY_FILE;
    const certFile = env.DEV_HTTPS_CERT_FILE;

    if (!keyFile || !certFile) {
      throw new Error(
        "DEV_HTTPS=true requires DEV_HTTPS_KEY_FILE and DEV_HTTPS_CERT_FILE"
      );
    }

    const resolvedKeyFile = resolveExistingFile(keyFile);
    const resolvedCertFile = resolveExistingFile(certFile);

    if (!resolvedKeyFile || !resolvedCertFile) {
      throw new Error("HTTPS cert or key file not found");
    }

    https = {
      key: fs.readFileSync(resolvedKeyFile),
      cert: fs.readFileSync(resolvedCertFile)
    };
  }

  return {
    server: {
      host: "0.0.0.0",
      port: 5173,
      https,
      proxy: {
        "/api": {
          target: env.VITE_API_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
          secure: false,
          rewrite: (path) => path.replace(/^\/api/, "")
        }
      }
    }
  };
});
