import { createApiClient } from "../src/api/client.js";
import type { components } from "../src/api/client.js";

// Compile-only probes. This function is never called and performs no requests.
export function contractProbes(document: components["schemas"]["Annotations"]) {
  const client = createApiClient();
  const response = client.request("get", "/api/videos", {});
  void response;
  void response.then((records) => {
    // @ts-expect-error Schema-less responses must remain unknown until validated.
    return records[0].id;
  });
  void client.request("put", "/api/videos/{video_id}/annotations", {
    path: { video_id: "example" },
    json: document,
  });
  // @ts-expect-error Nonexistent operations must not typecheck.
  void client.request("delete", "/api/videos", {});
  // @ts-expect-error Required path parameters cannot be omitted.
  void client.request("get", "/api/videos/{video_id}", {});
  void client.request("post", "/api/import/youtube", {
    // @ts-expect-error Backend request enums come from the actual OpenAPI schema.
    json: { url: "https://example.com", mode: "triples" },
  });
  // @ts-expect-error Mutation request bodies are required.
  void client.request("put", "/api/videos/{video_id}/annotations", {
    path: { video_id: "example" },
  });
}
