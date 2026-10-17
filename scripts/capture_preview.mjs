import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const output = new URL("../data/processed/qa/", import.meta.url);
await mkdir(output, { recursive: true });
try {
  await page.goto("http://127.0.0.1:8000");
  for (const name of ["singles.mp4", "doubles.mp4"]) {
    const button = page.getByRole("button", { name: new RegExp(name) });
    const videoId = await button.getAttribute("data-video");
    await button.click();
    await page.waitForFunction(
      (n) => document.querySelector("#title").textContent === n,
      name,
    );
    await page.waitForFunction(() =>
      document
        .querySelector("#track-status")
        .textContent.includes("250 frames"),
    );
    await page.waitForFunction(() =>
      document
        .querySelector("#shuttle-status")
        .textContent.includes("/250 frames visible"),
    );
    await page.waitForFunction(
      () => Number(document.querySelector("#candidate-count").textContent) > 0,
    );
    await page.waitForFunction((id) => {
      const img = document.querySelector("#exact-frame");
      return (
        img.src.includes(`/videos/${id}/`) &&
        img.complete &&
        img.naturalWidth > 0 &&
        !img.hidden
      );
    }, videoId);
    await page.screenshot({
      path: fileURLToPath(new URL(`${name.slice(0, -4)}-tracking.png`, output)),
      fullPage: true,
    });
    console.log(name, await page.locator("#track-status").textContent());
  }
} finally {
  await browser.close();
}
