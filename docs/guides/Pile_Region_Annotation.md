# Pile-region annotation

Use the reviewed Visible Cards workbench to mark one coarse region around each visible physical
pile. A pile region records visible grouping evidence. It does not record the pile's contents,
card count, owner, or game status.

## Review a frame

1. Open the maintained Visible Cards reference and select the exact source frame.
2. Keep **Camera** view. Calibration and rectification are optional.
3. Select **Draw pile region** and click at least three points around one pile. Keep the outline
   inside the frame and exclude nearby isolated cards and unrelated table area.
4. Save the polygon. Select its outline to edit it. The Pile regions layer shows the saved regions.
5. To group card proposals, select only the pending proposals to consume, select **Group selected
   cards into pile**, draw the footprint, and save. Touching or intersecting proposals are not
   consumed unless selected.
6. To convert an ignore region, select it and use **Convert ignore region to pile**. Check the
   outline first. Existing ignore regions remain editable until conversion.
7. Delete a pile region to undo it. If it consumed cards, deletion restores their saved card and
   pose-review work.
8. **Copy piles from previous frame** copies geometry as pending work. Inspect and accept every
   copied region on the new frame.
9. Review any individual cards outside piles. Accept the frame only after its piles and remaining
   individual-card work are correct. Complete the maintained reference after all required frames
   have a review decision.

The workbench reports pile-region count, individual-card work still pending, and frame review
state. Do not assign identities to grouped cards or review component poses inside a coarse pile.

## Annotation handoff: `cardeventnet-IMG_0662`

Review the named 0662 source frame in the maintained reference. Mark the three visible piles with
three separate coarse regions. Keep the isolated card as an individual visible card. Do not group
it into a pile. Inspect the outlines, accept the frame, then complete the reference through the
normal recording workflow. The expected three-pile layout is a review target, not a generated
annotation; the operator must confirm the source image and make the final decisions.
