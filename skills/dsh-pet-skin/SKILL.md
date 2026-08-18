---
name: dsh-pet-skin
description: Turn one image into a desk pet skin. Emits an 18-pose generation spec the user's own image tool runs on their own credentials, then installs the result. Use when someone wants their own character, photo, or drawing as the DSH desk pet.
---

# Make a desk pet skin from one image

You are turning a single image into a complete skin: six states, three frames
each, eighteen images total.

**You do not generate the art. The user's own image tool does, on the user's own
credentials.** Your job is the specification, the ordering, and the install.

---

## Before you ask for anything: the tool contract

Check that the image tool available to you can do all four of these. If it
cannot, say so now and stop. Finding out after fifteen generations costs the
user real money.

1. **Image-to-image with an input reference.** Text-to-image alone cannot hold a
   character's identity across calls — ask twice and you get two different
   animals, in two palettes, at two scales.
2. **Feeding a generated frame back as the reference for the next one.**
3. **PNG output.** Not JPEG: the installer decodes PNG only, and refuses a JPEG
   by name.
4. **A fixed square size**, the same for every frame.

Then tell the user the cost before the first request: **eighteen image
generations on their account.**

---

## The background is magenta, and this is not negotiable

Every frame is generated on a **flat `#FF00FF` magenta plate**, and **nothing in
the character or its props may be magenta.**

Do not ask the model for a transparent background. No image backend this
project has ever used returns an alpha channel — every one of them returns a
flat opaque image — so a transparency request produces an opaque frame the
installer will refuse. The magenta is removed after the fact, by us.

Magenta specifically because it appears in none of the shipped palettes. The
first batch of art was generated on pastel plates, and a mint-green background
sat close enough to a jellyfish's own highlights that no threshold separated
them: that jellyfish shipped with its eyes cut out.

---

## Step 1: the base pose

From the user's image, generate one frame: the character at rest, facing the
viewer, whole body in shot, on the magenta plate.

If the source is a photograph rather than a drawing, this is also the step that
restyles it — a chibi sprite with clean flat colours and a bold outline, not a
filtered photo.

**Stop and show the user.** This one frame decides every other. If it is wrong,
regenerate it now, before spending seventeen more.

## Step 2: prove the identity survives

Generate `idle/01` from the base pose — the same character an instant later, a
small breath, nothing else moves.

**Stop and show the user both frames.** If they do not look like the same
character, the tool cannot hold identity through reference chaining, and the
remaining sixteen generations would produce sixteen strangers. Say so and stop.

## Step 3: the remaining sixteen, in dependency order

The order matters and is not a preference.

**Wave one** — each state's first frame, generated from the base pose:

| Frame | The character is… |
|---|---|
| `working/00` | leaning in, holding a pencil, focused |
| `waiting/00` | head tilted, one brow raised, a small question mark above |
| `error/00` | wide-eyed, mouth open, a bead of sweat |
| `happy/00` | eyes closed and smiling, small sparkles around it |
| `sleeping/00` | eyes shut, curled, a bold Z drifting up |

**Wave two** — the second and third frame of each state, each generated from
**that state's own first frame**, never from the base pose:

- `01`: the same pose a fraction of a second later — a breath, a blink, one
  small drift.
- `02`: one step further along the same motion, so `00 → 01 → 02 → 00` reads as
  a loop.

Generating `01` from the base pose instead produced a loop that read as the
character exploding and re-forming once a second. It has to be the same pose an
instant later, not a second interpretation of the state.

Props follow the same rule: a pencil, sparkles, or a Z must be **bold and
solid**. Thin outlines vanish when the frame is scaled down, and a prop that
appears in `00` and disappears in `01` strobes.

---

## Step 4: install

Write the eighteen frames into a directory **outside** the skin root, laid out
as `<state>/00.png`, `<state>/01.png`, `<state>/02.png` for each of `idle`,
`working`, `waiting`, `error`, `happy`, `sleeping`.

Then run the installer. Never write into `~/.dsh-desk-pet/skins/` yourself: the
installer owns validation, the manifest, and the atomic rename, and a skin
placed there by hand is treated as the user's own and refused for replacement
forever after.

```bash
<package>/bin/dsh-desk-pet --install-skin <id> --from <your-frames-directory>
```

Resolve `<package>` relative to this file: the launcher ships beside it, two
directories up.

`<id>` is lowercase letters, digits, dash or underscore, up to 32 characters.

---

## If it refuses

The installer validates every frame and installs nothing unless all eighteen
pass. What it says maps to one cause:

| Message | What happened |
|---|---|
| `…% opaque, so its background was never removed` | The model ignored the magenta plate. Regenerate that frame. |
| `…% opaque; the character is missing` | The character itself was keyed away — it was probably too close to magenta. |
| `holes punched through the character` | Part of the character matched the plate colour. Check for magenta in the art. |
| `expected a PNG, got jpeg` | The tool returned JPEG. Ask it for PNG. |
| `is a built-in skin` | Pick a different id. |

**On a partial failure, name the poses that did not arrive and keep the frames
you already have.** The user has already paid for them. Regenerate only what is
missing, then run the installer again — it is all-or-nothing on install, not on
generation.

---

## Never

- Never ask the user for an API key, and never read one. The tool you already
  have is the tool that generates.
- Never write into the skin root directly.
- Never generate all eighteen before the user has confirmed the base pose.
