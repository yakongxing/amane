import assert from "node:assert/strict";
import test from "node:test";
import {
  externalPlayerLinks,
  externalPlaylist,
  externalPlaybackSchema,
} from "../src/lib/media/external-player.ts";

test("player links preserve signed and encoded playback URLs", () => {
  const target = {
    url: "https://alist.example/d/video%20name.mp4?sign=a%2Fb%3D&v=1",
    content_type: "video/mp4",
    name: "TEST-001",
  };
  const links = externalPlayerLinks(target);
  assert.equal(new URL(links.iina).searchParams.get("url"), target.url);
  assert.equal(new URL(links.vlcIos).searchParams.get("url"), target.url);
  assert.equal(links.potplayer.slice("potplayer://".length), target.url);
  const [data, intent] = links.android.split("#Intent;");
  assert.equal(data.replace("intent:", "https:"), target.url);
  assert.ok(intent.includes("action=android.intent.action.VIEW;"));
  assert.ok(links.vlcAndroid.includes("package=org.videolan.vlc;"));
});

test("unsafe URLs cannot become application launch links", () => {
  for (const url of [
    "javascript:alert(1)",
    "file:///etc/passwd",
    "https://user:pass@example.com/a.mp4",
    "https://example.com/a\n.mp4",
    "https://example.com/a\\b.mp4",
  ]) {
    assert.equal(
      externalPlaybackSchema.safeParse({ url, content_type: "video/mp4", name: "test" }).success,
      false,
      url,
    );
  }
});

test("playlist titles cannot inject additional entries", () => {
  const target = {
    url: "https://example.com/a.mp4?sign=abc",
    content_type: "video/mp4",
    name: "Title\nhttps://injected.example/movie",
  };
  const text = externalPlaylist(target);
  const urls = text.split("\n").filter((line) => line && !line.startsWith("#"));
  assert.deepEqual(urls, [target.url]);
});

test("Android data does not interpret URL fragments as intent instructions", () => {
  const target = {
    url: "https://example.com/a.mp4?sign=abc#Intent;package=evil;end",
    content_type: "video/mp4",
    name: "test",
  };
  const link = externalPlayerLinks(target).android;
  assert.equal(link.split("#Intent;").length, 2);
  assert.ok(!link.includes("package=evil"));
});
