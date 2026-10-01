---
name: Twiga
description: "Voir loin. Voir juste." (See far. See true.) — personal finance steering, 100% local.
colors:
  accent: "#d4a96a"
  on-accent: "#5c3d1e"
  page: "#f9f9f9"
  container: "#ffffff"
  primary: "#111827"
  secondary: "#585e6a"
  border: "#e5e7eb"
  success: "#16a34a"
  warning: "#f59e0b"
  danger: "#dc2626"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 800
    lineHeight: 1.2
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.4
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
    textColor: "{colors.accent}"
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
- Rare amber: reserved for the primary action and the active state, nowhere else
- Almost flat: a 1px border and surface contrast before any shadow
- Touch targets of 50px minimum, designed for the thumb before the mouse
- No font loaded, no CDN, no outgoing network request
- Light and dark themes in full parity, with no `dark:` variant in the templates

## Colors

A semantic palette of ten tokens, driven by CSS variables and redefined as a
block for the dark theme. Templates never use a raw color or a `dark:` variant.

### Primary
- **Giraffe Amber** (`#d4a96a`): the color of the spots and the only identity color of the system. It is used for two things only: the background of primary action buttons, and the active navigation state (text + a `bg-accent/10` pill behind the icon). Identical in light and dark: a mid-tone reads correctly on both backgrounds, which avoids duplicating it.
- **Bark Brown** (`#5c3d1e`): the foreground color on amber, used for the text and icons of primary buttons. Never white: amber is too light to carry white legibly.

### Neutral
- **Light Sand** (`#f9f9f9` light / `#0f172a` dark): the page background, against which containers stand out. Also the background of progress bar rails.
- **White Surface** (`#ffffff` light / `#1e293b` dark): every content surface: cards, fields, dialogs, navigation bars.
- **Ink** (`#111827` light / `#f1f5f9` dark): the main text and the amounts.
- **Faded Ink** (`#585e6a` light / `#94a3b8` dark): labels, metadata, inactive navigation states.
- **Hairline** (`#e5e7eb` light / `#334155` dark): all borders and separators, always 1px.

### Tertiary
Three state colors, lightened in the dark theme to keep contrast on the navy background:
- **Green** (`#16a34a` light / `#22c55e` dark): positive amount, healthy threshold.
- **Warning Amber** (`#f59e0b` light / `#fbbf24` dark): watch threshold.
- **Red** (`#dc2626` light / `#f87171` dark): negative amount, exceeded threshold, destructive action.

### Named Rules

**The Rare Amber Rule.** Amber only designates the primary action and the active state. It is never a decoration color, a section background, an emphasis border or a chart color. Its rarity is what makes it readable as a signal.

**The Brown on Amber Rule.** On `accent`, the foreground is always `on-accent` (`#5c3d1e`). Never white, never pure black.

**The Traffic Light Rule.** Green / orange / red are only computed verdicts: the sign of an amount, or a threshold being crossed (≥ 75% watch, ≥ 90% exceeded on budget bars). They are never used to categorize or decorate.

## Typography

**Display Font:** none, the system stack (`-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Roboto`...)
**Body Font:** same.

**Character:** Twiga loads no font. This is a deliberate constraint of the project: no CDN, no font file to serve, an instant and native rendering on every platform. The typographic identity therefore rests entirely on scale and weight, not on letterforms: clear weight jumps (500 → 800) over a deliberately short range of sizes.

### Hierarchy
- **Display** (800, 1.875rem / 30px): the amount of the transaction being categorized in La Savane. One per screen, colored by the sign of the amount.
- **Headline** (700, 1.5rem / 24px): page and card titles, and the editable label of the transaction, which keeps the look of a title even as an input field.
- **Title** (600, 1.125rem / 18px): section headers and secondary amounts.
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

**The Two Weights Rule.** A single block never uses more than two font weights. Hierarchy comes from the weight jump (500 → 700), not from a continuous gradation.

## Layout

A **mobile-first** application with two layouts, switched at `lg` (1024px) and only there:

- **Below 1024px**: a fixed header at the top (56px) and a fixed navigation bar at the bottom (50px + 1px border), four destinations. The `<body>` reserves the space once for everyone (`pt-[64px] pb-[59px]`); no page adds its own compensation.
- **From 1024px**: the bottom bar gives way to a fixed full-height sidebar with three modes: pinned (240px), automatic (a 64px rail that expands on hover, overlaying the content), hidden (0). The content offset follows the mode, not the hover.

Content is constrained to `max-w-lg` (32rem) for forms and panels, `max-w-sm` (24rem) for cards and mobile dialogs; the categorization card widens to 600px on large screens. Spacing rhythm relies on a short range from 4px to 32px, with `gap-2` (8px) as the default breathing room between elements of a same group and `p-4` / `p-6` (16/24px) as card padding depending on width.

### Named Rules

**The 50px Rule.** Everything you tap is at least 50px tall: buttons, navigation rows, list entries. Input fields go down to 46px, never below. This is a product constraint, not an aesthetic preference: categorization is done with the thumb, on the go.

**The Balanced Columns Rule.** When cards of very different heights share a page (Settings), do not use a grid: it aligns by rows and leaves two columns half empty next to a column three screens tall. `.settings-columns` (CSS columns: 2 from `lg`, 3 from `xl`, `break-inside: avoid`) fills top to bottom and balances itself; the order of the markup groups the cards by purpose.

**The Single Breakpoint Rule.** The switch from mobile to desktop happens at `lg` and nowhere else. `sm` and `md` only adjust internal details (card padding, the orientation of a button group), never the navigation structure.

## Elevation & Depth

The system is **almost flat**. Depth comes first from the contrast between the page background and the container surface, reinforced by a 1px border; the shadow is only a whisper on top. There are only two levels, and nothing in between.

### Shadow Vocabulary
- **Rest** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.05)`, i.e. `shadow-sm`): every card or content container placed on the page. This is the default level, used a hundred times in the application.
- **Overlay** (`box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)`, i.e. `shadow-lg`): only what really floats above the content: native `<dialog>` dialogs, the user menu, pop-up panels.

### Named Rules

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
- **Focus:** a 2px Giraffe Amber ring with a 2px offset, on `:focus-visible` only, never on mouse click.
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
- **Usage:** a choice among a few options that are compared at a glance (language, number and date format in Settings > Preferences); beyond five options, or for a binary setting, use a field or a checkbox.
- **Style:** 50px minimum height, 12px radius, 1px Hairline border, White Surface background; content stacks (title in `font-medium`, example or hint in faded 12px).
- **Selected:** Giraffe Amber border and inner line plus a 12% amber background: the state reads from shape, not from color alone.
- **Radio:** visually hidden (`.sr-only`) but never removed: the whole card is clickable, the keyboard keeps working, and the focus ring (2px amber) sits on the card (`:has(input:focus-visible)`).
- **Class:** `.choice-card` (design-system.css). Show the real rendering inside the card (a sample date and amount) rather than describing it.

### Navigation
- **Mobile (< 1024px):** fixed bottom bar, four destinations, each 50px tall, icon above the 12px label. Active = Giraffe Amber text in `font-semibold` + a `bg-accent/10` pill behind the icon.
- **Desktop (≥ 1024px):** a sidebar with three modes (pinned / automatic / hidden), seven destinations, rows of 44px minimum, active = `bg-accent/10` background and amber text. In automatic mode, the bar expands as an overlay on hover, at `z-50` to pass above the header.
- **Icons:** hand-drawn line SVGs, 24×24 `viewBox`, `stroke-width: 2`, rounded caps and joins, `stroke="currentColor"`. A single system, shared between both bars.

### Dialogs
A native `<dialog>` element, `backdrop:bg-black/50` backdrop, 12px radius, Overlay shadow, width `calc(100% - 2rem)` capped at `max-w-sm`. Opened and closed by HTMX swap, not by JavaScript state. On large screens, some detail panels switch to a full-height right-hand drawer (380px, rounded corners on the left only) rather than a centered modal.

### Categorization card (La Savane)
The signature component of the application and its measure of success: thirty transactions handled in under three minutes. A single centered card, `max-w-sm` on mobile and 600px on desktop, with a 2px border in the account's color. It stacks the editable label (typeset as a title), the raw import label in faded 12px, then the amount in 30px `font-extrabold` colored by its sign. Category selection happens in two steps, category then subcategory.

### Privacy mode
Every amount carries a static `.amount-blur` class set by the template; only the `.privacy-mode` class on `<body>` triggers a `blur(8px)`. Pure CSS, so it is effective on any content injected afterwards by HTMX or Chart.js, without relying on a JavaScript re-scan. No `:hover` or `:active` rule on the amount: only the dedicated button can lift the blur, never an accidental hover or tap.

## Do's and Don'ts

### Do:
- **Do** use the semantic utility classes (`bg-page`, `bg-container`, `text-primary`, `text-secondary`, `border-border`, `bg-accent`, `text-on-accent`) for every color. They are driven by CSS variables and switch to the dark theme on their own.
- **Do** redefine the dark tokens in the `.dark` block of `design-system.css`, outside any `@layer`: a rule without a layer always beats a rule that has one, which avoids adding a `dark:` variant to every template.
- **Do** keep the `color-scheme` declaration (`light` on `:root`, `dark` in `.dark`, plus the `<meta name="color-scheme">` of `base.html`). Without it, browsers with forced dark mode (a native Chrome Android setting or an extension) rewrite the whole palette into neutral grays and remove the background pattern; observed in production.
- **Do** give at least 50px of height to every tappable element, and 46px to input fields.
- **Do** draw new icons as line SVGs, 24×24 `viewBox`, `stroke-width: 2`, `currentColor`, to stay consistent with the existing set.
- **Do** color an amount by its sign (green positive, red negative) and a gauge by its threshold (≥ 75% watch, ≥ 90% exceeded).
- **Do** put `.amount-blur` on every new displayed amount, no exception: an amount that escapes privacy mode is a functional defect.
- **Do** recompile `frontend/static/vendor/tailwind.min.css` after any change to `design-system.css` or any new utility class added in a template: that compiled file is what gets served, not the source.

### Don't:
- **Don't** make Twiga look like a dark "data" dashboard: black background, saturated neons, sparklines everywhere, cockpit density. Dark mode exists for night-time comfort; it is not the identity of the product.
- **Don't** use amber anywhere other than the primary action and the active state. No amber section background, no emphasis border, no amber chart series by default.
- **Don't** put white on amber: the foreground on `accent` is always `on-accent` (`#5c3d1e`).
- **Don't** introduce a third shadow level or a third radius. If a separation is missing, add a 1px border or change surface.
- **Don't** write a raw color (`bg-white`, `text-black`, `#fff`) in a template: it will not switch to the dark theme.
- **Don't** add an inline `<script>` in a Jinja2 template. An `&&` or a special character can be badly escaped depending on the context; files in `static/js/` with data passed through `data-*` attributes are the normal way.
- **Don't** load anything from a CDN: font, script, stylesheet or image. The application must work without Internet access.
- **Don't** make the background pattern more present than it is (10% in light, 35% in dark). It should be guessed at; if it is noticed, it steals the attention meant for the amounts.
