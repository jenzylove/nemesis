# NEMESIS brand assets

Generated from `public/favicon.svg`, so the mark here is the same geometry the
product ships. The mark is the product: a route enters a node and splits into
branches, which is what a fund trace looks like.

## Files

| File | Size | Use |
|---|---|---|
| `nemesis-pfp-400.png` | 400×400 | X / social avatar. X crops to a circle. |
| `nemesis-pfp-800.png` | 800×800 | Same artwork at 2x for larger placements. |
| `nemesis-x-banner-1500x500.png` | 1500×500 | X header. |
| `nemesis-x-banner-3000x1000.png` | 3000×1000 | Same at 2x for retina. |

## Layout constraints these were drawn against

- Avatars are cropped to a circle, so the artwork stays inside the inscribed
  square and nothing lands near the corners.
- X overlays the avatar on the lower left of the header, and crops the header's
  sides on narrow screens. The wordmark therefore starts at x=408 and the lower
  left is deliberately empty.

## Palette

    ink        #0A1220
    surface    #0b1524
    off-white  #F7F9FC
    blue       #2563FF
    muted      #8995a8

## Regenerating

    node brand/render.mjs

Requires `playwright`. Edit `pfp.html` / `banner.html` and re-run; sizes are
declared in `render.mjs`. `preview.html` shows the avatar at X's real display
sizes, which is worth checking after any change to the mark.
