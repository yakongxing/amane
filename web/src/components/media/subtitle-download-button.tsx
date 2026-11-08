import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Modal,
  Select,
  Skeleton,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDownload, IconRefresh } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getMetadataQueryKey,
  listSubtitleSourcesOptions,
  searchSubtitlesOptions,
} from "@/client/@tanstack/react-query.gen";
import { downloadSubtitle } from "@/client/sdk.gen";
import type { MediaFileResponse, SubtitleCandidateItem } from "@/client/types.gen";
import { extractErrorMessage } from "@/lib/api-error";

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

/** 等待覆盖确认的那一次下载: 同名字幕已存在时由用户决定是否覆盖. */
type PendingOverwrite = { candidateId: string; mediaId: number };

/**
 * 详情页「关联文件」卡片上的字幕下载入口.
 *
 * 没有已启用的字幕源或条目没有已入库文件时不渲染. 搜索在打开对话框后才发出 (字幕源是上游站点);
 * 落盘位置由主机按所选视频决定, 成功后让播放面板重新探测, 新字幕随即出现在播放器的轨道里.
 */
export function SubtitleDownloadButton({
  metadataId,
  number,
  files,
}: {
  metadataId: number;
  number: string;
  files: MediaFileResponse[];
}) {
  const { t } = useTranslation("metadata");
  const queryClient = useQueryClient();
  const [opened, setOpened] = useState(false);
  const [pickedSource, setPickedSource] = useState<string | null>(null);
  const [pickedMedia, setPickedMedia] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingOverwrite | null>(null);

  const sourcesQuery = useQuery(listSubtitleSourcesOptions());
  const sources = sourcesQuery.data?.items ?? [];
  const source = sources.find((item) => item.source_id === pickedSource) ?? sources[0];
  const media = files.find((item) => item.id === pickedMedia) ?? files[0];

  const candidatesQuery = useQuery({
    ...searchSubtitlesOptions({
      path: { source_id: source?.source_id ?? "", metadata_id: metadataId },
    }),
    enabled: opened && source != null,
    retry: false,
    staleTime: 5 * 60_000,
  });

  if (source == null || media == null) {
    return null;
  }

  const save = async (candidateId: string, mediaId: number, overwrite: boolean) => {
    setBusy(candidateId);
    setError(null);
    setPending(null);
    const result = await downloadSubtitle({
      path: { source_id: source.source_id, metadata_id: metadataId },
      body: { candidate_id: candidateId, media_id: mediaId, overwrite },
    });
    setBusy(null);
    if (result.response?.status === 409) {
      setPending({ candidateId, mediaId });
      return;
    }
    if (result.data == null) {
      setError(extractErrorMessage(result.error, t("detail.subtitleDownloadFailed")));
      return;
    }
    notifications.show({
      color: "teal",
      message: t("detail.subtitleSaved", { path: fileName(result.data.path) }),
    });
    // 播放面板按条目重新探测, 新字幕出现在轨道列表; 详情页的中字角标随之刷新.
    void queryClient.invalidateQueries({ queryKey: [{ _id: "listPlaybackStreams" }] });
    void queryClient.invalidateQueries({
      queryKey: getMetadataQueryKey({ path: { metadata_id: metadataId } }),
    });
    setOpened(false);
  };

  const candidates: SubtitleCandidateItem[] = candidatesQuery.data?.items ?? [];

  return (
    <>
      <Button
        size="compact-sm"
        variant="light"
        leftSection={<IconDownload size={14} />}
        onClick={() => setOpened(true)}
      >
        {t("detail.subtitleDownload")}
      </Button>
      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title={t("detail.subtitleDownloadTitle", { number })}
        size="lg"
      >
        <Stack gap="sm">
          <Group grow align="flex-end">
            {sources.length > 1 ? (
              <Select
                label={t("detail.subtitleSourceLabel")}
                data={sources.map((item) => ({ value: item.source_id, label: item.name }))}
                value={source.source_id}
                onChange={(value) => setPickedSource(value)}
                allowDeselect={false}
              />
            ) : null}
            <Select
              label={t("detail.subtitleTargetLabel")}
              data={files.map((item) => ({ value: String(item.id), label: fileName(item.path) }))}
              value={String(media.id)}
              onChange={(value) => setPickedMedia(value == null ? null : Number(value))}
              allowDeselect={false}
            />
          </Group>
          {error != null ? (
            <Alert color="red" variant="light">
              {error}
            </Alert>
          ) : null}
          {pending != null ? (
            <Alert color="yellow" variant="light">
              <Group justify="space-between" wrap="nowrap">
                <Text size="sm">{t("detail.subtitleExists")}</Text>
                <Button
                  size="compact-sm"
                  color="yellow"
                  onClick={() => void save(pending.candidateId, pending.mediaId, true)}
                >
                  {t("detail.subtitleOverwrite")}
                </Button>
              </Group>
            </Alert>
          ) : null}
          {candidatesQuery.isPending ? (
            <Skeleton height={120} />
          ) : candidatesQuery.isError ? (
            <Alert color="red" variant="light">
              <Group justify="space-between" wrap="nowrap">
                <Text size="sm">
                  {extractErrorMessage(candidatesQuery.error, t("detail.subtitleSearchFailed"))}
                </Text>
                <ActionIcon
                  variant="transparent"
                  color="red"
                  loading={candidatesQuery.isFetching}
                  onClick={() => void candidatesQuery.refetch()}
                >
                  <IconRefresh size={16} />
                </ActionIcon>
              </Group>
            </Alert>
          ) : candidates.length === 0 ? (
            <Text size="sm" c="dimmed">
              {t("detail.subtitleNoResults")}
            </Text>
          ) : (
            <Table verticalSpacing="xs">
              <Table.Tbody>
                {candidates.map((item) => (
                  <Table.Tr key={item.id}>
                    <Table.Td>
                      <Stack gap={2}>
                        <Group gap={6} wrap="nowrap">
                          <Text size="sm" fw={500}>
                            {item.name}
                          </Text>
                          {item.language != null ? (
                            <Badge size="xs" variant="light">
                              {item.language}
                            </Badge>
                          ) : null}
                          {item.format != null ? (
                            <Badge size="xs" variant="outline">
                              {item.format}
                            </Badge>
                          ) : null}
                        </Group>
                        {item.detail != null ? (
                          <Text size="xs" c="dimmed">
                            {item.detail}
                          </Text>
                        ) : null}
                      </Stack>
                    </Table.Td>
                    <Table.Td w={1}>
                      <Button
                        size="compact-sm"
                        loading={busy === item.id}
                        disabled={busy != null && busy !== item.id}
                        onClick={() => void save(item.id, media.id, false)}
                      >
                        {t("detail.subtitleFetch")}
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Modal>
    </>
  );
}
