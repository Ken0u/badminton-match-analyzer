import { createApiClient } from "../api/client.js";

export interface UploadProgress {
  loaded: number;
  total: number | null;
}
export type Upload = (
  file: File,
  mode: "singles" | "doubles",
  signal: AbortSignal,
  progress: (value: UploadProgress) => void,
) => Promise<unknown>;
/** XHR supplies real browser transfer bytes; typed client retains HTTP/error parsing. */
export const uploadVideo: Upload = (file, mode, signal, progress) => {
  const body = new FormData();
  body.set("file", file);
  body.set("mode", mode);
  const fetcher: typeof fetch = async (input, init) =>
    new Promise<Response>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const abort = () => xhr.abort();
      const cleanup = () => signal.removeEventListener("abort", abort);
      xhr.open(init?.method ?? "POST", String(input));
      // Same origin only: never expose the session to a configurable remote URL.
      if (new URL(String(input), location.href).origin !== location.origin) {
        reject(new Error("Upload must use the same origin"));
        return;
      }
      xhr.timeout = 30 * 60 * 1000;
      xhr.withCredentials = false; // Same-origin cookies are sent by XHR by default.
      new Headers(init?.headers).forEach((v, k) => xhr.setRequestHeader(k, v));
      xhr.upload.onprogress = (e) =>
        progress({
          loaded: e.loaded,
          total: e.lengthComputable ? e.total : null,
        });
      xhr.onload = () => {
        cleanup();
        try {
          resolve(
            new Response(xhr.responseText, {
              status: xhr.status,
              headers: {
                "Content-Type": xhr.getResponseHeader("Content-Type") ?? "",
              },
            }),
          );
        } catch (error) {
          reject(error);
        }
      };
      xhr.ontimeout = () => {
        cleanup();
        reject(
          new Error(
            "Upload timed out. The server may already have received it; reload jobs before retrying.",
          ),
        );
      };
      xhr.onerror = () => {
        cleanup();
        reject(
          new TypeError(
            "Upload network failure. The server may already have received it; reload jobs before retrying.",
          ),
        );
      };
      xhr.onabort = () => {
        cleanup();
        reject(new DOMException("Upload cancelled", "AbortError"));
      };
      signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) {
        cleanup();
        reject(new DOMException("Upload cancelled", "AbortError"));
        return;
      }
      xhr.send(body);
    });
  return createApiClient({ fetch: fetcher }).request("post", "/api/upload", {
    body,
    signal,
  });
};
