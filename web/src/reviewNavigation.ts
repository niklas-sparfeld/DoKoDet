export type ReviewNavigationDirection = -1 | 1;

type ReviewNavigationItem = {
  itemId: string;
};

export function findAdjacentUnfinishedItem<Item extends ReviewNavigationItem>(
  items: readonly Item[],
  selectedItemId: string | null,
  direction: ReviewNavigationDirection,
  needsReview: (item: Item) => boolean,
): Item | undefined {
  const selectedIndex = items.findIndex(
    (item) => item.itemId === selectedItemId,
  );
  let index =
    selectedIndex < 0
      ? direction < 0
        ? items.length - 1
        : 0
      : selectedIndex + direction;

  while (index >= 0 && index < items.length) {
    const item = items[index];
    if (item !== undefined && needsReview(item)) return item;
    index += direction;
  }
  return undefined;
}

export function ignoresReviewNavigationShortcut(
  target: EventTarget | null,
): boolean {
  if (!(target instanceof Element)) return false;
  return (
    target.closest("input, textarea, select, [contenteditable='true']") !==
      null || target.closest('[data-timeline-seeking-controls="true"]') !== null
  );
}
