---
name: Twiga
description: "Voir loin. Voir juste." (See far. See true.) — personal finance steering, 100% local.
colors:
  accent: "#d4a96a"
  accent-hover: "#c99a58"
  on-accent: "#4a2f12"
  accent-ink: "#8a5a1f"
  accent-soft: "#f7efe3"
  page: "#faf8f5"
  container: "#ffffff"
  sunken: "#f3f0eb"
  primary: "#111827"
  secondary: "#585e6a"
  border: "#e7e2da"
  border-strong: "#d6cfc4"
  field: "#848a94"
  success: "#13703a"
  success-soft: "#eaf6ee"
  warning: "#a14a07"
  warning-gauge: "#f59e0b"
  warning-soft: "#fdf3e3"
  danger: "#c81e1e"
  danger-soft: "#fdecec"
  info: "#1d4ed8"
  info-soft: "#eef3fd"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 800
    lineHeight: 1.2
  headline:
    fontFamily: "'Bricolage Grotesque', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1.75rem"
    fontWeight: 800
    letterSpacing: "-0.02em"
    lineHeight: 1.15
  title:
    fontFamily: "'Bricolage Grotesque', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1.125rem"
    fontWeight: 800
    letterSpacing: "-0.02em"
    lineHeight: 1.3
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
  card-title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 500
    lineHeight: 1.4
  amount-large:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    fontFeature: "tabular-nums"
  amount:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    fontFeature: "tabular-nums"
  amount-small:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    fontFeature: "tabular-nums"
rounded:
  lg: "8px"
  xl: "12px"
  full: "9999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "6": "24px"
  "8": "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    typography: "{typography.body}"
    rounded: "{rounded.xl}"
    height: "50px"
    padding: "0 16px"
  button-secondary:
    backgroundColor: "{colors.container}"
    textColor: "{colors.primary}"
    typography: "{typography.body}"
    rounded: "{rounded.xl}"
    height: "50px"
    padding: "0 24px"
  button-danger:
    backgroundColor: "{colors.container}"
    textColor: "{colors.danger}"
    typography: "{typography.body}"
    rounded: "{rounded.xl}"
    height: "50px"
    padding: "0 16px"
  input-text:
    backgroundColor: "{colors.container}"
    textColor: "{colors.primary}"
    typography: "{typography.body}"
    rounded: "{rounded.xl}"
    height: "50px"
    padding: "0 12px"
  card:
    backgroundColor: "{colors.container}"
    textColor: "{colors.primary}"
    rounded: "{rounded.xl}"
    padding: "16px"
  nav-item:
    textColor: "{colors.secondary}"
    typography: "{typography.label}"
    height: "50px"
  nav-item-active:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.label}"
    height: "50px"
  dialog:
    backgroundColor: "{colors.container}"
    textColor: "{colors.primary}"
    rounded: "{rounded.xl}"
    padding: "0"
    width: "calc(100% - 2rem)"
---

# Design System: Twiga

## Overview

**Creative North Star: "The Lookout"**

Twiga borrows from the giraffe not its whimsy but its height: seeing far,
seeing true. The interface is an observation post, not a cockpit dashboard. It
does not comment, congratulate or dramatize; it presents exact figures,
legibly, and gets out of the way. Everything that stays on screen must have
earned its place: an amount, a category, an action. The rest is silence.

The atmosphere is **calm, warm and precise**. Warm because the palette is
built around a desaturated tan amber, the color of a giraffe's spots, set on
an off-white and never on pure white or clinical gray. Calm because the accent
color is rare and nothing moves without a reason. Precise because this is
money: amounts are `NUMERIC(15,2)` in the database and read as such, with no
cosmetic rounding and no decorative chart that would leave doubt about the
real value.

The giraffe-spot background pattern, a script-generated Voronoi diagram tiled
periodically, is the only ornament of the system, and it is deliberately set
at 22% opacity in the light theme. It should be guessed at, never noticed.
That is the simplest test of the whole system: if an element catches the eye
before the amount it accompanies, it is too strong.

**Key Characteristics:**
- A single radius (12px) on 90% of surfaces: shape carries no information
- Rare amber: a solid fill only for the primary action; the active state is a soft amber background with amber-ink text; never a link, a chart series or a decoration
- Almost flat: a 1px border and surface contrast before any shadow, two warm-tinted levels
- Touch targets of 50px minimum, designed for the thumb before the mouse
- One font file family loaded (Bricolage Grotesque 700/800, self-hosted), no CDN, no outgoing network request
- Light and dark themes in full parity, with no `dark:` variant in the templates

## Colors

A semantic palette driven by CSS variables (`@theme` in `design-system.css`), redefined as a block for the dark theme. Templates never use a raw color or a `dark:` variant.

### Primary
- **Giraffe Amber** (`#d4a96a`, hover `#c99a58`): the color of the spots. A solid fill for one thing only: the primary action button. Identical in light and dark.
- **Bark Brown** (`#4a2f12` light / `#2b1a08` dark): the foreground on amber, used for the text and icons of primary buttons. Never white.
- **Amber Ink** (`#8a5a1f` light / `#e2bd80` dark): amber when it has to be text or a fine line (5:1 on the page, where `#d4a96a` only reaches 2:1): the active navigation item, the focus ring, the selected choice card.
- **Soft Amber** (`#f7efe3` light / `#382a17` dark): the background of an active state (navigation pill, user avatar, selected row).

### Neutral
- **Warm Page** (`#faf8f5` light / `#17130f` dark): the page background. The sidebar shares it, separated by a hairline.
- **White Surface** (`#ffffff` light / `#211c17` dark): cards, fields, dialogs, the bottom bar. In dark it is lighter than the page: elevation comes from the tint, not from a shadow.
- **Sunken** (`#f3f0eb` light / `#120f0c` dark): rails, recessed zones, row hover. Darker than the page in dark.
- **Ink** (`#111827` light / `#efe7da` dark): the main text, the amounts and all links.
- **Faded Ink** (`#585e6a` light / `#b0a595` dark): labels, metadata, inactive states.
- **Hairline** (`#e7e2da` / dark `#463d33`) and **Strong Hairline** (`#d6cfc4` / dark `#5a4f42`): borders (1px) of surfaces, then of controls placed on a surface.
- **Field Outline** (`#848a94` / dark `#8d8272`): the border of text fields, 3.4:1 on the surface (WCAG 1.4.11).

### Tertiary
Verdict colors, each with a soft background, lightened in the dark theme where the soft background becomes a deep tint of the same hue:
- **Green** (`#13703a` / `#eaf6ee`; dark `#6fcf93` on `#14301f`): positive amount, healthy threshold.
- **Orange** (text `#a14a07`, gauge fill `#f59e0b`, background `#fdf3e3`; dark text `#f2a65a` on `#3b2610`, gauge fill unchanged): watch threshold. The gauge fill is a flat bar, never text.
- **Red** (`#c81e1e` / `#fdecec`; dark `#ff8f87` on `#3f1b19`): negative amount, exceeded threshold, destructive action.
- **Blue** (`#1d4ed8` / `#eef3fd`; dark `#7fb2f5` on `#172a45`): neutral information.

### Data palette
Eight series colors for charts and shares, read from CSS variables by the chart scripts (`--color-chart-1` to `8`): `#2563eb #0d9488 #9333ea #db2777 #65a30d #ea580c #0891b2 #64748b` in light, `#5b8def #2dc4b0 #b77df0 #f06aa8 #8fcf3a #f28a4a #36bfd8 #94a3b8` in dark (3:1 minimum on the dark surface). No amber, no verdict green or red.

### Named Rules

**The Rare Amber Rule.** A solid amber fill designates the primary action; amber-ink text and soft amber background designate the active state. Amber is never a link color, a decoration, an emphasis border or a chart color. Its rarity is what makes it readable as a signal.

**The Brown on Amber Rule.** On `accent`, the foreground is always `on-accent` (`#4a2f12`). Never white, never pure black.

**The Traffic Light Rule.** Green / orange / red are only computed verdicts: the sign of an amount, or a threshold being crossed (≥ 75% watch, ≥ 90% exceeded on budget bars). They are never used to categorize or decorate, and always come with a word.

### Giraffe on dark
In the dark theme the mascot gets a light outline (`#f0e2c8`, a zero-offset double `drop-shadow(0 0 1px)` on the whole drawing, `.dark .twiga-mascot`) so the silhouette detaches from the brown background. The shapes themselves never change.

## Typography

**Display Font:** Bricolage Grotesque, weights 700 and 800 (SIL Open Font License, `frontend/static/fonts/OFL.txt`). Page titles, section titles and the giraffe's lines.
**Body Font:** the system stack (`-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Roboto`...).

**Character:** one expressive face for the voice of the app, one native stack for everything you read and compare. The two font files are self-hosted (about 18 KB each, subset to Latin, Latin-1, `€` and `−`, optical size fixed at 32), preloaded in `base.html`, loaded with `font-display: swap` and precached by the service worker. No CDN, no network call at runtime. Titles use `letter-spacing: -0.02em`; `h1` and `h2` get the display font from the base layer, `.text-page-title`, `.text-section-title` and `.text-replique` spell it out.

### Hierarchy
- **Display** (800, 1.875rem / 30px): the amount of the transaction being categorized in La Savane. One per screen, colored by the sign of the amount.
- **Headline** (Bricolage 800, 1.75rem / 28px, 2.125rem / 34px from `lg`): page titles. The editable label of the transaction keeps the look of a title even as an input field.
- **Title** (Bricolage 800, 1.125rem / 18px): section headers. The giraffe's lines (`.text-replique`) use 1.375rem / 22px.
- **Body** (400–500, 0.875rem / 14px): all running text, control labels, list content.
- **Label** (500, 0.75rem / 12px): metadata, navigation labels, dates, secondary notes.

### Amount scale

Amounts form a **separate scale** from text, because they are a semantic category of their own: they are tabular figures, always in `font-variant-numeric: tabular-nums`, and their size follows the importance of the figure, not that of the surrounding text.

- **Amount large** (700, 1.75rem / 28px): the hero amount of a screen: the current transaction in La Savane, a headline balance.
- **Amount** (600, 1rem / 16px): the amount of a row or a card.
- **Amount small** (500, 0.8125rem / 13px): amounts in dense contexts: table rows, compact lists.

**Card title** (500, 1rem / 16px) completes the set, the title of a card: one step below Title, for cards that live inside a section that already has a title.

### Named Rules

**The 14px Rule.** Body text is `text-sm` (14px), not 16px: it is the reference size of the whole application, and `text-base` is effectively unused. A screen that goes above it signals an exception, not a preference.

**The Two Weights Rule.** A single block never uses more than two font weights. Hierarchy comes from the weight jump (500 → 800), not from a continuous gradation. Bricolage is for titles only: never in a table, a field or an amount.

## Layout

A **mobile-first** application with two layouts, switched at `lg` (1024px) and only there:

- **Below 1024px**: a fixed header at the top (56px) and a fixed navigation bar at the bottom (50px + 1px border), four destinations. The `<body>` reserves the space once for everyone (`pt-[64px] pb-[59px]`); no page adds its own compensation.
- **From 1024px**: the bottom bar gives way to a fixed full-height sidebar with three modes: pinned (240px), automatic (a 64px rail that expands on hover, overlaying the content), hidden (0). The content offset follows the mode, not the hover.

A screen uses the whole width the shell leaves it, at every width up to and beyond 2000px (see The Full Width Rule); only dialogs are narrow: `max-w-sm` (24rem) or `max-w-md` for confirmations and forms, with `calc(100% - 2rem)` on a phone. Spacing rhythm relies on a short range from 4px to 32px, with `gap-2` (8px) as the default breathing room between elements of a same group and `p-4` / `p-6` (16/24px) as card padding depending on width.

### Named Rules

**The 50px Rule.** Everything you tap is at least 50px tall: buttons, navigation rows, list entries. Input fields go down to 46px, never below. This is a product constraint, not an aesthetic preference: categorization is done with the thumb, on the go.

**The Density Never Touches the 50px Rule.** Density (below) changes air, never size: the text keeps its size, and everything you tap stays at least 50px tall in Compact exactly as in Airy. Only rows nobody touches (`--row-static`) may go lower.

**The Balanced Columns Rule.** When cards of very different heights share a page (Settings), do not use a grid: it aligns by rows and leaves two columns half empty next to a column three screens tall. `.settings-columns` (CSS columns: 2 from `lg`, 3 from `xl`, `break-inside: avoid`) fills top to bottom and balances itself; the order of the markup groups the cards by purpose.

**The Full Width Rule.** A screen fills all the width available next to the sidebar, from 390px to 2000px and more. The mockups are drawn at 1320px: that width is a sample, not a ceiling. So no `max-w-*`, no fixed `px` width and no `minmax(0, …px)` on a page, a list column, a grid, a table or a filter bar. Columns share the width with `flex` / `fr` (`flex-1`, `flex-[1_1_180px]`, `grid-cols-[minmax(0,1fr)_380px]`), and a filter bar lets its fields grow and wrap (`flex-wrap`) instead of squeezing them until a label is cut. Below `lg`, the page is not centred in a narrow column either: no `max-w-lg mx-auto` on `<main>`. Exceptions, and only these: a side column (filters, detail, live panel) may keep a fixed width (300 to 380px) next to a `1fr` column; a paragraph or sentence meant to be read is capped at `70ch`; the search field of a filter bar may be capped; a `<dialog>` is a dialog, not a page; and a control that stands alone (a segmented switch, a stepper, a ring) keeps its own size. Check any new screen at 2000px before calling it done.

**The Single Breakpoint Rule.** The switch from mobile to desktop happens at `lg` and nowhere else. `sm` and `md` only adjust internal details (card padding, the orientation of a button group), never the navigation structure.

### Density

A per-account display preference (Mon profil, Paramètres > Préférences), saved on the account and mirrored in the `twiga_density` cookie, and rendered by the server as `<html data-density="compact|normal|comfortable">`. Seven CSS variables in `design-system.css` change with it; the components read them, the templates never hard-code the spacing they cover.

| Variable | Compact | Normal | Airy (`comfortable`) | Used for |
| --- | --- | --- | --- | --- |
| `--space-card` | 12px (16px from `lg`) | 16px (24px from `lg`) | 24px (32px from `lg`) | padding of `.card` and panels |
| `--space-block` | 10px | 16px | 24px | gap between the blocks of a page |
| `--space-list` | 8px | 12px | 18px | gap between list items and grid cells |
| `--row-pad` | 4px | 8px | 14px | vertical padding of a row or a group header |
| `--row-touch` | 50px | 56px | 68px | minimum height of an Operations row (tappable) |
| `--row-list` | 50px | 50px | 62px | minimum height of a tappable list row (Panorama) |
| `--row-static` | 34px | 44px | 56px | height of a row nobody taps |

Compact shows more lines on screen, Airy gives more breathing room. What does not move, in any density: the font sizes, the 50px height of buttons, checkboxes and tappable rows (`--row-touch` and `--row-list` never go below 50px), colors, order and components. The selector is the attribute alone (`[data-density="..."]`), so the preview of the preference screen can set its own density on a small element. `/design-system` has a "Densité" button that cycles the whole page through the three and a section that shows them side by side.

The theme follows the same path: the server renders `class="dark"` on `<html>` for "dark", nothing for "light", and only "system" is left to the browser (`prefers-color-scheme`, followed live by the head script). So there is no flash on load.

## Elevation & Depth

The system is **almost flat**. Depth comes first from the contrast between the page background and the container surface, reinforced by a 1px border; the shadow is only a whisper on top. There are only two levels, and nothing in between.

### Shadow Vocabulary
- **Rest** (`box-shadow: 0 1px 2px rgb(60 40 20 / 0.06)`, i.e. `shadow-sm`): every card or content container placed on the page. This is the default level, used a hundred times in the application.
- **Floating** (`box-shadow: 0 12px 24px -6px rgb(60 40 20 / 0.16)`, i.e. `shadow-lg`): only what really floats above the content: native `<dialog>` dialogs, the user menu, pop-up panels.

### Named Rules

**Dark elevation.** In the dark theme the shadows are nearly zero (`--shadow-sm` is empty, `--shadow-lg` is a faint 0.4 black): the page is `#17130f`, the surface one step lighter (`#211c17`), the sunken zones one step darker (`#120f0c`), and the 1px borders do the rest.

**The Whispered Shadow Rule.** Two levels, not three. If an element seems to need an intermediate shadow, it lacks a border or a surface contrast, not a shadow.

## Shapes

The shape language is deliberately monotone: **12px radius** (`rounded-xl`) on practically every surface: cards, buttons, fields, dialogs, navigation pills. The radius carries no information; it does not vary to tell one component from another.

The full circle (`rounded-full`) is reserved for three geometric uses: progress bar rails and gauges, status dots (8 to 10px) and initials avatars. An 8px radius (`rounded-lg`) remains on a few compact controls under 32px, where 12px would look disproportionate.

Borders are 1px, in `border`, on all surfaces. The only deliberate exception is the La Savane categorization card, which has a 2px border colored by the bank account concerned: it is the only place where a border carries information.

### Named Rules

**The Single Radius Rule.** 12px everywhere, except geometric circles. Do not introduce a third radius to "differentiate" a component: differentiate it by color, weight or spacing.

**The Coat Scale Rule.** A patch of the background pattern measures about 140px on screen: large patches, comparatively thin light channels. Below ~100px the pattern stops reading as a giraffe and becomes snakeskin: small tight polygons with overly marked joints. Two settings determine it together and must move together: the density of the SVG (a 4×4 grid on a 1000-unit canvas) and `background-size: 560px` in `design-system.css`. Changing one without the other cancels the gain.

## Components

**Philosophy: frank and reassuring.** Controls are large, with constant corners, and respond instantly to the finger: a press gives visual feedback before the network request even leaves.

### Buttons
- **Shape:** 12px radius (`rounded-xl`), minimum height 50px.
- **Primary:** Giraffe Amber background, Bark Brown text, `font-semibold`. It is the single dominant action of a screen.
- **Secondary:** White Surface background, 1px Hairline border, Ink text, `font-medium`. For everything that accompanies the primary action.
- **Danger:** Red background, white text, `font-medium`. Reserved for deletions, systematically behind a confirmation.
- **Hover:** `filter: brightness(0.96)`, applied only under `@media (hover: hover)` to avoid a "stuck" hover state after a touch tap.
- **Active:** `transform: scale(0.97)` and `opacity: 0.85` in 100ms.
- **Focus:** a 2px Amber Ink ring with a 2px offset, on `:focus-visible` only, never on mouse click.
- **During a request:** `opacity: 0.6` and `pointer-events: none` (`.htmx-request` class), which also neutralizes double-clicks.

### Cards / Containers
- **Corner Style:** 12px.
- **Background:** White Surface on the Light Sand page background.
- **Shadow Strategy:** Rest level only (see Elevation & Depth).
- **Border:** none by default, surface contrast is enough; a 1px border when the card sits on another light surface.
- **Internal Padding:** 16px on mobile, 24px from `md` on main cards.

### Inputs / Fields
- **Style:** 46px height, 12px radius, 1px Hairline border, White Surface background, 14px text, 12px horizontal padding.
- **Focus:** the global accent ring (`:focus-visible`).
- **Title field:** a distinctive variant: a field with no background or border, underlined by a simple 1px line that turns amber on focus, and typeset like a title (24px, 700). Used to rename a transaction label without ever feeling like filling in a form.

### Choice cards
- **Usage:** a choice among a few options that are compared at a glance (language, number and date format, interface, theme and density in Settings > Preferences and Mon profil; a choice that is not available yet, such as "L'autre voie", is shown disabled with a "Bientôt" hint); beyond five options, or for a binary setting, use a field or a checkbox.
- **Style:** 50px minimum height, 12px radius, 1px Hairline border, White Surface background; content stacks (title in `font-medium`, example or hint in faded 12px).
- **Selected:** Giraffe Amber border and inner line plus a 12% amber background: the state reads from shape, not from color alone.
- **Radio:** visually hidden (`.sr-only`) but never removed: the whole card is clickable, the keyboard keeps working, and the focus ring (2px amber) sits on the card (`:has(input:focus-visible)`).
- **Class:** `.choice-card` (design-system.css). Show the real rendering inside the card (a sample date and amount) rather than describing it.

### Navigation
- **Mobile (< 1024px):** fixed bottom bar, four destinations, each 50px tall, icon above the 12px label. Active = Amber Ink text in `font-semibold` + a `bg-accent-soft` pill behind the icon.
- **Desktop (≥ 1024px):** a sidebar on the page background with three modes (pinned / automatic / hidden), five destinations, rows of 50px, active = `bg-accent-soft` background, Amber Ink text and `font-semibold`. In automatic mode, the bar expands as an overlay on hover, at `z-50` to pass above the header.
- **Icons:** hand-drawn line SVGs, 24×24 `viewBox`, `stroke-width: 2`, rounded caps and joins, `stroke="currentColor"`. A single system, shared between both bars.

### Dialogs
A native `<dialog>` element, `backdrop:bg-scrim` backdrop (`--color-scrim`: black at 50% in light, `rgb(8 6 4 / 0.66)` in dark), 12px radius, Overlay shadow, width `calc(100% - 2rem)` capped at `max-w-sm`. Opened and closed by HTMX swap, not by JavaScript state. On large screens, some detail panels switch to a full-height right-hand drawer (380px, rounded corners on the left only) rather than a centered modal.

### Categorization card (La Savane)
The signature component of the application and its measure of success: thirty transactions handled in under three minutes. A single centered card, `max-w-sm` on mobile and 600px on desktop, with a 2px border in the account's color. It stacks the editable label (typeset as a title), the raw import label in faded 12px, then the amount in 30px `font-extrabold` colored by its sign. Category selection happens in two steps, category then subcategory.

### Privacy mode
Every amount carries a static `.amount-blur` class set by the template; only the `.privacy-mode` class on `<body>` triggers a `blur(8px)`. Pure CSS, so it is effective on any content injected afterwards by HTMX or Chart.js, without relying on a JavaScript re-scan. No `:hover` or `:active` rule on the amount: only the dedicated button can lift the blur, never an accidental hover or tap.

## Motion

One easing, `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)` (fast arrival, soft end), and three durations (100 / 200 / 300 ms). Page entry, content swapped in by HTMX, the upload indicator ("Twiga tend le cou…"), the tour bubble and the rule-suggestion popup rise by a few pixels while fading in over 0.3 s. All of it sits under `@media (prefers-reduced-motion: no-preference)`: with the preference set, nothing slides.

### Named Rules

**The No Transform on Main Rule.** The page-entry animation targets the children of `<main>`, never `<main>` itself, and skips fixed elements: a transform on an ancestor becomes the containing block of its `position: fixed` descendants.

## The giraffe

The mascot is an inline SVG macro, `mascot(state, size)` in `frontend/templates/_macros/brand.html`, with five states: `default` (the logo), `done` ("Twiga a tout brouté !"), `waiting` ("Twiga tend le cou…"), `swallowed` ("Twiga a tout avalé !") and `cap` ("Le cap est fixé !"). Same shapes and colors as the logo; only the eyes, the mouth, the neck and one prop change. The favicon and the app icon stay files. The navigation icons shared by the sidebar and the bottom bar live in the same file (`nav_icon`).

## Do's and Don'ts

### Do:
- **Do** use the semantic utility classes (`bg-page`, `bg-container`, `bg-sunken`, `text-primary`, `text-secondary`, `border-border`, `border-field`, `bg-accent`, `text-on-accent`, `text-accent-ink`, `bg-accent-soft`) for every color. They are driven by CSS variables and switch to the dark theme on their own.
- **Do** redefine the dark tokens in the `.dark` block of `design-system.css`, outside any `@layer`: a rule without a layer always beats a rule that has one, which avoids adding a `dark:` variant to every template.
- **Do** keep the `color-scheme` declaration (`light` on `:root`, `dark` in `.dark`, plus the `<meta name="color-scheme">` of `base.html`). Without it, browsers with forced dark mode (a native Chrome Android setting or an extension) rewrite the whole palette into neutral grays and remove the background pattern; observed in production.
- **Do** give at least 50px of height to every tappable element, and 46px to input fields.
- **Do** draw new icons as line SVGs, 24×24 `viewBox`, `stroke-width: 2`, `currentColor`, to stay consistent with the existing set.
- **Do** color an amount by its sign (green positive, red negative) and a gauge by its threshold (≥ 75% watch, ≥ 90% exceeded).
- **Do** put `.amount-blur` on every new displayed amount, no exception: an amount that escapes privacy mode is a functional defect.
- **Do** recompile `frontend/static/vendor/tailwind.min.css` after any change to `design-system.css` or any new utility class added in a template, with `tools/css.sh build` (`tools/css.sh watch` while iterating): that compiled file is what gets served, not the source.

### Don't:
- **Don't** make Twiga look like a dark "data" dashboard: black background, saturated neons, sparklines everywhere, cockpit density. Dark mode exists for night-time comfort; it is not the identity of the product.
- **Don't** use amber anywhere other than the primary action (solid) and the active state (soft background, amber-ink text). No amber link, section background, emphasis border or chart series.
- **Don't** put white on amber: the foreground on `accent` is always `on-accent` (`#4a2f12`).
- **Don't** introduce a third shadow level or a third radius. If a separation is missing, add a 1px border or change surface.
- **Don't** write a raw color (`bg-white`, `text-black`, `#fff`) in a template: it will not switch to the dark theme.
- **Don't** add an inline `<script>` in a Jinja2 template. An `&&` or a special character can be badly escaped depending on the context; files in `static/js/` with data passed through `data-*` attributes are the normal way.
- **Don't** load anything from a CDN: font, script, stylesheet or image. The application must work without Internet access. The one font family is self-hosted.
- **Don't** pass a CSS class name through the translation function (`_("pelage")` once made the login page lose its pattern in English).
- **Don't** make the background pattern more present than it is (10% in light, 35% in dark). It should be guessed at; if it is noticed, it steals the attention meant for the amounts.
