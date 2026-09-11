import { useEffect, useRef } from "react";

const PREWARM_BLOCK_SIZE = 4;
const PREWARM_MAX_CONCURRENT_REQUESTS = 2;
const PREWARM_MAX_PENDING_URLS = 4;
const MAX_WARMED_URLS = 256;

export function deriveReviewPrewarmBlocks(
  itemCount: number,
  selectedIndex: number,
): number[][] {
  if (
    itemCount <= 0 ||
    selectedIndex < 0 ||
    selectedIndex >= itemCount ||
    !Number.isInteger(selectedIndex)
  ) {
    return [];
  }

  const indexes = [
    ...Array.from(
      { length: itemCount - selectedIndex - 1 },
      (_, offset) => selectedIndex + offset + 1,
    ),
    ...Array.from(
      { length: selectedIndex },
      (_, offset) => selectedIndex - offset - 1,
    ),
  ];
  const blocks: number[][] = [];
  for (let offset = 0; offset < indexes.length; offset += PREWARM_BLOCK_SIZE) {
    blocks.push(indexes.slice(offset, offset + PREWARM_BLOCK_SIZE));
  }
  return blocks;
}

type PrewarmUrlFactory<Item> = (
  item: Item,
  index: number,
) => readonly (string | null | undefined)[];

type PendingWarm = symbol;

type PrewarmQueue = {
  warmedUrls: Set<string>;
  pendingUrls: Map<string, PendingWarm>;
  queuedUrls: string[];
  queuedUrlSet: Set<string>;
  activeRequests: number;
};

export function usePipelineReviewPrewarm<Item>(
  items: readonly Item[],
  selectedIndex: number,
  getUrls: PrewarmUrlFactory<Item>,
  resetKey?: unknown,
): void {
  const queueRef = useRef<PrewarmQueue>({
    warmedUrls: new Set<string>(),
    pendingUrls: new Map<string, PendingWarm>(),
    queuedUrls: [],
    queuedUrlSet: new Set<string>(),
    activeRequests: 0,
  });

  useEffect(() => {
    const queue = queueRef.current;
    const blocks = deriveReviewPrewarmBlocks(items.length, selectedIndex);
    const urls = Array.from(
      new Set(
        blocks
          .flatMap((block) =>
            block.flatMap((index) => getUrls(items[index]!, index)),
          )
          .filter((url): url is string => url !== null && url !== undefined),
      ),
    ).slice(0, PREWARM_MAX_PENDING_URLS);

    enqueuePrewarmUrls(urls, queue);

    return () => {
      // Active requests are left alone because the server may still be processing them.
      dropQueuedPrewarmUrls(queue);
    };
  }, [getUrls, items, resetKey, selectedIndex]);
}

function enqueuePrewarmUrls(
  urls: readonly string[],
  queue: PrewarmQueue,
): void {
  for (const url of urls) {
    if (
      queue.warmedUrls.has(url) ||
      queue.pendingUrls.has(url) ||
      queue.queuedUrlSet.has(url)
    ) {
      continue;
    }
    if (
      queue.pendingUrls.size + queue.queuedUrls.length >=
      PREWARM_MAX_PENDING_URLS
    ) {
      break;
    }
    queue.queuedUrls.push(url);
    queue.queuedUrlSet.add(url);
  }
  pumpPrewarmQueue(queue);
}

function dropQueuedPrewarmUrls(queue: PrewarmQueue): void {
  queue.queuedUrls.length = 0;
  queue.queuedUrlSet.clear();
}

function pumpPrewarmQueue(queue: PrewarmQueue): void {
  while (
    queue.activeRequests < PREWARM_MAX_CONCURRENT_REQUESTS &&
    queue.queuedUrls.length > 0
  ) {
    const url = queue.queuedUrls.shift();
    if (url === undefined) return;
    queue.queuedUrlSet.delete(url);
    if (queue.warmedUrls.has(url) || queue.pendingUrls.has(url)) continue;

    const pendingToken = Symbol(url);
    queue.pendingUrls.set(url, pendingToken);
    queue.activeRequests += 1;
    void prewarmUrl(url, queue, pendingToken).finally(() => {
      if (queue.pendingUrls.get(url) === pendingToken) {
        queue.pendingUrls.delete(url);
      }
      queue.activeRequests -= 1;
      pumpPrewarmQueue(queue);
    });
  }
}

async function prewarmUrl(
  url: string,
  queue: PrewarmQueue,
  pendingToken: PendingWarm,
): Promise<void> {
  try {
    const response = await fetch(url);
    await response.arrayBuffer();
    if (response.ok && queue.pendingUrls.get(url) === pendingToken) {
      rememberWarmedUrl(url, queue.warmedUrls);
    }
  } catch {
    // Review prewarming is best effort. The foreground image request owns review UX.
  }
}

function rememberWarmedUrl(url: string, warmedUrls: Set<string>): void {
  if (warmedUrls.has(url)) return;
  if (warmedUrls.size >= MAX_WARMED_URLS) {
    const oldest = warmedUrls.values().next().value;
    if (oldest !== undefined) warmedUrls.delete(oldest);
  }
  warmedUrls.add(url);
}
