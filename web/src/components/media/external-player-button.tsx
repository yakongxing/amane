import { Button, Menu, Text } from "@mantine/core";
import { IconExternalLink } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PlaybackStreamItem } from "@/client/types.gen";
import { extractErrorMessage } from "@/lib/api-error";
import { externalPlaybackOptions } from "@/client/@tanstack/react-query.gen";
import {
  externalPlaybackSchema,
  externalPlayerLinks,
  externalPlaylist,
} from "@/lib/media/external-player";

export function ExternalPlayerButton({
  metadataId,
  stream,
}: {
  metadataId: number;
  stream: PlaybackStreamItem;
}) {
  const { t } = useTranslation("metadata");
  const [actionError, setActionError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const query = useQuery({
    ...externalPlaybackOptions({
      path: { source_id: stream.source_id, metadata_id: metadataId, key: stream.key ?? "" },
      cache: "no-store",
      redirect: "error",
    }),
    select: (data) => externalPlaybackSchema.parse(data),
    enabled: false,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
  const target = query.data;
  const links = target == null ? null : externalPlayerLinks(target);
  const error =
    actionError ??
    (query.isError ? extractErrorMessage(query.error, t("detail.externalUnavailable")) : null);

  const download = () => {
    if (target == null) return;
    const url = URL.createObjectURL(
      new Blob([externalPlaylist(target)], { type: "audio/x-mpegurl;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `amane-${metadataId}-${stream.key ?? "stream"}.m3u`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <Menu
      shadow="md"
      position="bottom-end"
      withinPortal
      onChange={(opened) => {
        if (opened) {
          setActionError(null);
          setCopied(false);
          void query.refetch();
        }
      }}
    >
      <Menu.Target>
        <Button size="compact-sm" variant="light" leftSection={<IconExternalLink size={14} />}>
          {t("detail.externalPlayer")}
        </Button>
      </Menu.Target>
      <Menu.Dropdown maw={320}>
        {query.isFetching ? <Menu.Label>{t("detail.externalLoading")}</Menu.Label> : null}
        {error != null ? (
          <Menu.Label>
            <Text size="xs" c="red">
              {error}
            </Text>
          </Menu.Label>
        ) : null}
        {links != null && !query.isFetching && !query.isError ? (
          <>
            <Menu.Label>{t("detail.externalInstalled")}</Menu.Label>
            <Menu.Item component="a" href={links.android}>
              {t("detail.externalSystemAndroid")}
            </Menu.Item>
            <Menu.Item component="a" href={links.vlcAndroid}>
              VLC (Android)
            </Menu.Item>
            <Menu.Item component="a" href={links.potplayer}>
              PotPlayer (Windows)
            </Menu.Item>
            <Menu.Item component="a" href={links.iina}>
              IINA (macOS)
            </Menu.Item>
            <Menu.Item component="a" href={links.vlcIos}>
              VLC (iOS)
            </Menu.Item>
            <Menu.Divider />
            <Menu.Item onClick={download}>{t("detail.externalDownload")}</Menu.Item>
            <Menu.Item
              closeMenuOnClick={false}
              onClick={() => {
                if (target == null) return;
                const copy = async () => {
                  try {
                    await navigator.clipboard.writeText(target.url);
                    setCopied(true);
                  } catch {
                    setActionError(t("detail.externalCopyFailed"));
                  }
                };
                void copy();
              }}
            >
              {t(copied ? "detail.externalCopied" : "detail.externalCopy")}
            </Menu.Item>
          </>
        ) : null}
      </Menu.Dropdown>
    </Menu>
  );
}
