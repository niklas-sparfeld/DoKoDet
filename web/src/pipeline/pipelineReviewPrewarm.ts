import { useEffect, useRef } from "react";

const PREWARM_BLOCK_SIZE = 4;
const PREWARM_BATCH_SIZE = 4;
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

  const blockStart =
    Math.floor(selectedIndex / PREWARM_BLOCK_SIZE) * PREWARM_BLOCK_SIZE;
  return [
    blockStart,
    blockStart - PREWARM_BLOCK_SIZE,
    blockStart + PREWARM_BLOCK_SIZE,
  ]
    .filter(
      (start, index, starts) =>
        start >= 0 && start < itemCount && starts.indexOf(start) === index,
    )
    .map((start) =>
      Array.from(
        { length: Math.min(PREWARM_BLOCK_SIZE, itemCount - start) },
        (_, offset) => start + offset,
      ),
    );
}

type PrewarmUrlFactory<Item> = (
  item: Item,
  index: number,
) => readonly (string | null | undefined)[];

type PendingWarm = symbol;

export function usePipelineReviewPrewarm<Item>(
  items: readonly Item[],
  selectedIndex: number,
  getUrls: PrewarmUrlFactory<Item>,
  resetKey?: unknown,
): void {
  const warmedUrlsRef = useRef(new Set<string>());
  const pendingUrlsRef = useRef(new Map<string, PendingWarm>());

  useEffect(() => {
    const controller = new AbortController();
    const pendingUrls = pendingUrlsRef.current;
    const blocks = deriveReviewPrewarmBlocks(items.length, selectedIndex);

    void prewarmReviewBlocks(
      items,
      blocks,
      getUrls,
      controller.signal,
      warmedUrlsRef.current,
      pendingUrls,
    );

    return () => {
      controller.abort();
      pendingUrls.clear();
    };
  }, [getUrls, items, resetKey, selectedIndex]);
}

async function prewarmReviewBlocks<Item>(
  items: readonly Item[],
  blocks: readonly number[][],
  getUrls: PrewarmUrlFactory<Item>,
  signal: AbortSignal,
  warmedUrls: Set<string>,
  pendingUrls: Map<string, PendingWarm>,
): Promise<void> {
  for (const block of blocks) {
    if (signal.aborted) return;
    const urls = Array.from(
      new Set(
        block
          .flatMap((index) => getUrls(items[index]!, index))
          .filter((url): url is string => url !== null && url !== undefined),
      ),
    );
    for (let offset = 0; offset < urls.length; offset += PREWARM_BATCH_SIZE) {
      if (signal.aborted) return;
      await Promise.all(
        urls
          .slice(offset, offset + PREWARM_BATCH_SIZE)
          .map((url) => prewarmUrl(url, signal, warmedUrls, pendingUrls)),
      );
    }
  }
}

async function prewarmUrl(
  url: string,
  signal: AbortSignal,
  warmedUrls: Set<string>,
  pendingUrls: Map<string, PendingWarm>,
): Promise<void> {
  if (warmedUrls.has(url)) return;
  if (pendingUrls.has(url)) return;

  const pendingToken = Symbol(url);
  pendingUrls.set(url, pendingToken);
  try {
    const response = await fetch(url, { signal });
    await response.arrayBuffer();
    if (response.ok && !signal.aborted) rememberWarmedUrl(url, warmedUrls);
  } catch {
    // Review prewarming is best effort. The foreground image request owns review UX.
  } finally {
    if (pendingUrls.get(url) === pendingToken) pendingUrls.delete(url);
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
