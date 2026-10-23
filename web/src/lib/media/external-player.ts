import { z } from "zod";

function controlCharacter(char: string): boolean {
  const code = char.charCodeAt(0);
  return code < 32 || code === 127;
}

export const externalPlaybackSchema = z.object({
  url: z
    .string()
    .refine(
      (value) =>
        !Array.from(value).some(
          (char) => controlCharacter(char) || /\s/.test(char) || char === "\\",
        ),
    )
    .pipe(z.url())
    .refine((value) => {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password;
    }),
  content_type: z.string(),
  name: z.string(),
});

export type ExternalPlayback = z.infer<typeof externalPlaybackSchema>;

export function externalPlayerLinks(target: ExternalPlayback) {
  const parsed = externalPlaybackSchema.parse(target);
  // URL 片段不参与 HTTP 取流，移除后避免与 Android Intent 的分隔符混淆。
  const networkUrl = parsed.url.split("#", 1)[0] ?? parsed.url;
  const colon = networkUrl.indexOf(":");
  const scheme = networkUrl.slice(0, colon);
  const data = networkUrl.slice(colon + 1);
  const mime = encodeURIComponent(parsed.content_type.split(";", 1)[0] || "video/mp4");
  const intent = `intent:${data}#Intent;scheme=${scheme};action=android.intent.action.VIEW;type=${mime};`;
  return {
    android: `${intent}end`,
    vlcAndroid: `${intent}package=org.videolan.vlc;end`,
    potplayer: `potplayer://${parsed.url}`,
    iina: `iina://weblink?url=${encodeURIComponent(parsed.url)}`,
    vlcIos: `vlc-x-callback://x-callback-url/stream?url=${encodeURIComponent(parsed.url)}`,
  };
}

export function externalPlaylist(target: ExternalPlayback): string {
  const parsed = externalPlaybackSchema.parse(target);
  const title = Array.from(parsed.name, (char) => (controlCharacter(char) ? " " : char)).join("");
  return `#EXTM3U\n#EXTENC:UTF-8\n#EXTINF:-1,${title}\n${parsed.url}\n`;
}
