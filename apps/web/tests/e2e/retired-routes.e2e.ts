import { expect, test } from "@playwright/test";

const retiredPaths = ["/api/trade-memos", "/api/attack-tickets", "/api/weekly-review"] as const;
const retiredMethods = ["GET", "POST", "PATCH", "PUT", "DELETE"] as const;

test("retired record and review routes are absent while Past Note remains", async ({ request }) => {
  for (const path of retiredPaths) {
    for (const method of retiredMethods) {
      const response = await request.fetch(path, {
        method,
        headers: { "content-type": "application/json" },
        data: {}
      });
      expect(response.status(), `${method} ${path}`).toBe(404);
    }
  }

  const getPastNotes = await request.get("/api/past-notes");
  expect(getPastNotes.status(), "GET /api/past-notes").not.toBe(404);

  const postPastNotes = await request.post("/api/past-notes", { data: {} });
  expect(postPastNotes.status(), "POST /api/past-notes").not.toBe(404);
});
