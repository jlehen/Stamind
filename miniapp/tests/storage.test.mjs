// The pages' files (DESIGN_miniapp_storage.md §5): the example `tests/test_page_files.py`
// seals in Python, opened here with the page's own code.
// Run from the repository root: node --test miniapp/tests/*.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import * as storage from "../storage.js";

// The page key of the bot token "123456789:AAFakeTokenForTheTestsOnly", the name of
// September's file under it, and a file sealed with it.
const KEY = "IiDj40QCoCdJWU3MtQSdXiIUxAfdHa2tsSjfchSeSAg";
const SEPTEMBER = "e1e44c0cd3c43d90cc87728e35c3f0e9";
const BLOB = "Tpon53mKKQfBlovsF9sQxlNkm8jRYsUCh1PTsdNyd5/5EeXX5sL7WTRERu+/F1xZuu8m8LVIedBKY0vL"
  + "wHC+T1mQMgUBBssllEOSdH7P4ILDwB5FheWS2005KBo2NoDMfrZh3UrCDP7D+6mh4KGdOjZZMYxjlIP5HLsXZ9noL8"
  + "FxZZTZ35XCaIcKu15NR/SAXfxWCKK5F2rPconycyjRcCeMb2M=";

const HASH = `#tgWebAppData=query_id%3DAAH&c=abc&k=${KEY}&b=stamind-pages&f=123456789`
  + "&tgWebAppVersion=8.0";

function blob() {
  return Uint8Array.from(Buffer.from(BLOB, "base64"));
}

test("the key, the bucket and the folder are read next to Telegram's own parameters", () => {
  const found = storage.storageFromHash(HASH);
  assert.equal(found.bucket, "stamind-pages");
  assert.equal(found.folder, "123456789");
  assert.equal(found.key.length, 32);
  assert.equal(storage.storageFromHash("#c=abc"), null);
});

test("the page names September's file and opens it as Python sealed it", async () => {
  const files = storage.storageFromHash(HASH);
  assert.equal(await storage.fileName(files.key, "calendar/2026-09"), SEPTEMBER);
  const content = await storage.unseal(files.key, blob());
  assert.equal(content.v, 1);
  assert.deepEqual(content.days["2026-09-22"].sheet,
                   [["Planned", ["🏃 Easy run — 50 min", "Easy run in zone 2."]]]);
  assert.equal(storage.fileUrl(files, SEPTEMBER),
               "https://storage.googleapis.com/storage/v1/b/stamind-pages/o/"
               + `123456789%2F${SEPTEMBER}?alt=media`);
});

test("a file that cannot be had, or cannot be opened, throws", async (t) => {
  const files = storage.storageFromHash(HASH);
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 404 }));
  await assert.rejects(storage.fetchFile(files, "calendar/2026-09"), /HTTP 404/);
  t.mock.method(globalThis, "fetch", async () => new Response(blob().slice(0, 40)));
  await assert.rejects(storage.fetchFile(files, "calendar/2026-09"));
  t.mock.method(globalThis, "fetch", async (url) => {
    assert.ok(url.endsWith(`123456789%2F${SEPTEMBER}?alt=media`));
    return new Response(blob());
  });
  assert.equal((await storage.fetchFile(files, "calendar/2026-09")).v, 1);
});
