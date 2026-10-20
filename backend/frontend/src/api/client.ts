import type { paths } from "./generated/schema.js";

export type { components, paths } from "./generated/schema.js";
type Method = "get" | "post" | "put" | "delete" | "patch";
type Operation<
  P extends keyof paths,
  M extends Method,
> = M extends keyof paths[P] ? NonNullable<paths[P][M]> : never;
type SupportedMethod<P extends keyof paths> = {
  [M in Method]: Operation<P, M> extends never ? never : M;
}[Method];
type Parameters<O, K extends string> = O extends { parameters: infer P }
  ? K extends keyof P
    ? NonNullable<P[K]>
    : never
  : never;
type JsonBody<O> = O extends {
  requestBody: { content: { "application/json": infer B } };
}
  ? B
  : never;
type UploadBody<O> = O extends {
  requestBody: { content: { "multipart/form-data": unknown } };
}
  ? FormData
  : never;
type BodyOptions<O> = [JsonBody<O>] extends [never]
  ? [UploadBody<O>] extends [never]
    ? { json?: never; body?: never }
    : { body: FormData; json?: never }
  : { json: JsonBody<O>; body?: never };
export type RequestOptions<O> = {
  signal?: AbortSignal;
  headers?: HeadersInit;
} & ([Parameters<O, "path">] extends [never]
  ? { path?: never }
  : { path: Parameters<O, "path"> }) &
  ([Parameters<O, "query">] extends [never]
    ? { query?: never }
    : { query?: Parameters<O, "query"> }) &
  BodyOptions<O>;
type SuccessResponse<O> = O extends { responses: infer R }
  ? R[Extract<keyof R, 200 | 201 | 202 | 203 | 204 | 205 | 206>]
  : never;
// FastAPI emits {} where handlers have no return schema. Do not invent records.
type PreserveUnknown<T> = keyof T extends never ? unknown : T;
export type ResponseData<O> =
  SuccessResponse<O> extends { content: { "application/json": infer D } }
    ? PreserveUnknown<D>
    : unknown;

export class ApiError extends Error {
  readonly isConflict: boolean;
  constructor(
    readonly status: number,
    readonly detail: unknown,
    readonly rawBody: string,
    readonly url: string,
  ) {
    super(
      typeof detail === "string" && detail
        ? detail
        : `Request failed (${status})`,
    );
    this.name = "ApiError";
    this.isConflict = status === 409;
  }
}

export class ApiProtocolError extends Error {
  constructor(
    readonly status: number,
    readonly rawBody: string,
    readonly url: string,
  ) {
    super(`Expected a JSON response (${status})`);
    this.name = "ApiProtocolError";
  }
}

export function isCancellation(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function throwIfAborted(signal?: AbortSignal) {
  if (signal?.aborted)
    throw signal.reason ?? new DOMException("Request cancelled", "AbortError");
}

export function createApiClient({
  baseUrl = "",
  fetch: fetcher = globalThis.fetch.bind(globalThis),
}: { baseUrl?: string; fetch?: typeof globalThis.fetch } = {}) {
  return {
    async request<P extends keyof paths, M extends SupportedMethod<P>>(
      method: M,
      template: P,
      options: RequestOptions<Operation<P, M>>,
    ): Promise<ResponseData<Operation<P, M>>> {
      throwIfAborted(options.signal);
      const pathParameters = options.path as
        Record<string, unknown> | undefined;
      const path = template.replace(/\{([^}]+)\}/g, (_, key: string) => {
        const value = pathParameters?.[key];
        if (value === undefined)
          throw new TypeError(`Missing path parameter: ${key}`);
        return encodeURIComponent(String(value));
      });
      const query = new URLSearchParams();
      for (const [key, value] of Object.entries(options.query ?? {})) {
        if (value !== undefined && value !== null)
          query.set(key, String(value));
      }
      const url =
        baseUrl.replace(/\/$/, "") + path + (query.size ? `?${query}` : "");
      const headers = new Headers(options.headers);
      headers.set("Accept", "application/json");
      const init: RequestInit = {
        method: method.toUpperCase(),
        headers,
        credentials: "same-origin",
      };
      if (options.signal) init.signal = options.signal;
      if ("json" in options && options.json !== undefined) {
        headers.set("Content-Type", "application/json");
        init.body = JSON.stringify(options.json);
      } else if ("body" in options && options.body) init.body = options.body;
      const response = await fetcher(url, init);
      const raw = await response.text();
      // Aborting a fetch/body reader is best effort; also fence noncompliant transports.
      throwIfAborted(options.signal);
      let value: unknown;
      let validJson = false;
      if (raw) {
        try {
          value = JSON.parse(raw) as unknown;
          validJson = true;
        } catch {
          value = raw;
        }
      }
      if (!response.ok) {
        const detail =
          value && typeof value === "object" && "detail" in value
            ? value.detail
            : value;
        throw new ApiError(response.status, detail, raw, url);
      }
      if (response.status === 204 || response.status === 205 || !raw)
        return undefined as ResponseData<Operation<P, M>>;
      if (!validJson) throw new ApiProtocolError(response.status, raw, url);
      return value as ResponseData<Operation<P, M>>;
    },
  };
}
