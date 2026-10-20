# Style a PackOverflow page or slide

Every page and slide uses one dark navy gradient with SD Worx's blue as the cool color and a muted amber to rose gradient for people. Copy the tokens from `app/theme.css`, which owns the values. This file says how to use them. Version 0.1, first draft.

## The idea in one line

Blue is what the machine does automatically. Muted amber to rose is the human who actually knows. A judge reads the color before the words.

## Colors

The palette comes from SD Worx's own design system (Ignite), so the demo looks like it belongs to them.

| Token | Value | Use |
|---|---|---|
| `--navy-950`, `--navy-800` | `#000d3a`, `#001c52` | Page background gradient, text on a warm button |
| `--blue-600`, `--sky-300` | `#006dd8`, `#9ed2ff` | Automatic and AI things, links, the active tab |
| `--amber`, `--magenta` | `#e8a877`, `#b8688f` | A person, a human decision, the one word to emphasize |
| `--text`, `--muted` | `#f4f8ff`, `#9fb0cc` | Body text, secondary text |
| `--coral` | `#da3300` | Risk or a single point of failure, never decoration |

## Background

Use the `body` rule in `theme.css`: a navy diagonal gradient with a blue glow at the top right and a faint rose glow at the bottom left. Do not add other background images or a second gradient.

## Type

- Headings: Bricolage Grotesque, weight 800, tight line height. Load it from Google Fonts.
- Body: Inter, weight 400 and 600.
- One heading size per slide. Keep body text above 24px on a slide, because the jury reads from a distance.

## Components

- `.glass` is the card: translucent white on the gradient, a thin light border, rounded 18px.
- `.btn` is the primary action and uses the human gradient. `.btn.ghost` is secondary.
- `.kicker` is the small amber uppercase label above a heading.
- `.grad-human` colors one phrase per slide. `.grad-ai` colors a number or phrase about the machine.

## Slide rules

1. One message per slide, written as a sentence a judge can repeat.
2. At most 4 cards or 3 bullets on a slide.
3. Emphasize one phrase or number with `.grad-human`. Two highlighted phrases mean none is.
4. Show a real screenshot of the product in a `.glass` frame, not a mockup.
5. The deck is a PDF on the organisers' device, so it must not depend on hover, animation or an unloaded font. Check the exported PDF.

## Check before you say it is done

Open the rendered page or exported PDF and look at the last slide and the smallest text. Text on the navy background needs a contrast ratio of 4.5:1, which `--muted` and `--text` meet.
