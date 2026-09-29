
Act as a Senior Frontend Engineer and Expert UI Designer.
Your task is to code a complete Landing Page on the first attempt.

- Landing Page Theme: <INSERT THEME></insert>
- Sections to add: <INSERT SECTIONS></insert>

Generate the final code immediately following these definitions:

## Style

- **Name:** Anthropomorphic
- **Type:** Whimsical, Character-Driven, Playful, Vintage
- **Keywords:** Anthropomorphic, animal characters, human traits, whimsical, playful, vintage, mascot, storybook, charming, relatable
- **Era:** Victorian Illustration to Modern Character Design
- **Light/Dark:** ✓ Full / ◐ Partial

## Color Palette

- **Primary:** Warm Honey #E8A840, Soft Cream #FFF5E1, Forest Brown #5C3D2E, Sky Blue #87CEEB
- **Secondary:** Blush Pink #F5C6C6, Leaf Green #6B8E4E, Sunset Orange #E87040, Lavender #B8A9D4

## Visual Effects

Hand-drawn illustration style borders, rounded playful shapes (20-30px radius), bouncy hover animations (cubic-bezier), soft drop shadows, storybook-style section transitions, warm gradient backgrounds

## AI Visual Direction

Design a whimsical anthropomorphic-themed landing page with playful character-driven aesthetics. Use warm honey, cream and forest brown palette. Apply hand-drawn style borders, rounded shapes (20-30px), bouncy animations, storybook-like section layouts. Typography should be friendly and rounded. Create a charming, vintage-meets-modern atmosphere suitable for character brands.

## CSS Technical

```css
font-family: 'Nunito', sans-serif, border-radius: 24px, background: #FFF5E1, color: #5C3D2E, border: 2px solid #E8A840, box-shadow: 4px 4px 0 rgba(92,61,46,0.15), transition: transform 300ms cubic-bezier(0.34,1.56,0.64,1), animation: bounce
```

## Design System Variables

```css
--color-honey: #E8A840, --color-cream: #FFF5E1, --color-brown: #5C3D2E, --font-primary: 'Nunito', --border-radius: 24px, --shadow-playful: 4px 4px 0 rgba(92,61,46,0.15), --bounce: cubic-bezier(0.34,1.56,0.64,1), --spacing: 1.5rem
```

## Implementation Checklist

- ☐ Warm playful color palette
- ☐ Rounded shapes throughout (20-30px)
- ☐ Hand-drawn style decorative elements
- ☐ Bouncy hover animations
- ☐ Friendly rounded typography
- ☐ Storybook-like section layouts
- ☐ Responsive with maintained charm

## Execution Rules

1. Strictly follow the defined visual style.
2. Use high-quality inline SVG icons (Heroicons or Lucide style) — NEVER use emojis as icons.
3. Add `cursor-pointer` and smooth `hover` states (transition-all) on all interactive elements.
4. Required Page Structure:
   - Navbar (Logo + Links + CTA)
   - Hero Section (Impactful Headline + Subtitle + 2 buttons + 3D/Abstract visual element via CSS)
   - Features (3 cards with icons)
   - Testimonials (3 cards)
   - Pricing (3 tiers, highlight the middle one)
   - Final CTA
   - Full Footer with social links, privacy policy, terms of use, contact and SEO links.
5. All text content must be in English.
6. The visual must be CLEARLY distinct — do not create a "default Bootstrap" design. Force the use of the provided design system variables.
7. Use `<style>` tags in the head for custom classes (especially for complex backdrop-filter effects and animations) that Tailwind CDN doesn't cover.
8. Full Responsiveness: Layout must adapt perfectly to Mobile, Tablet and Desktop (vertical stack on mobile).
9. Include basic SEO, Viewport and Open Graph meta tags in `<head>`.
10. Footer must contain: Copyright 2026, Secondary navigation links and Social media icons.
11. Make the creative decisions needed to deliver the complete, functional result now.
