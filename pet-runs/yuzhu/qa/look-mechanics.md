# Yuzhu look mechanics

Yuzhu is a compact felt-plush lion-dragon with a distinct head, soft mane and ears, four grounded paws, and a flexible tail ending in an attached pearl. Looking around should read as attention and curiosity, not as a rotating turntable.

## Natural motion

- Anchor the four-paw base, lower torso, body scale, and baseline in every direction.
- The dark eyes and muzzle lead the gaze. The head then turns or pitches, followed by a restrained upper-torso shift.
- Preserve the original physical eye construction: dark glossy eyes rotate with eyelid and highlight changes; do not add sliding googly pupils, new eye whites, or a second eye layer.
- The near ear opens toward the viewer while the far ear and far mane edge become partly occluded during left/right turns. The soft mane follows the head by a small amount.
- The tail remains attached to the rump. Its pearl tip lags the head slightly and moves in a shallow continuous arc without switching sides abruptly.
- Do not rotate, skew, or tilt the whole sprite. Do not change skull proportions, mane volume, paw spacing, pearl size, or plush material.

## Cardinal pose families

- `000 up`: muzzle lifts, pupils/eyes aim upward, upper eyelids open slightly, forehead pearl tilts back, and the upper mane compresses subtly. Both ears remain visible; the lower body stays front-biased and anchored.
- `090 screen-right`: muzzle and nose shift clearly to screen-right of head center; the screen-right face side and ear become more visible while the far face side and far ear are partly occluded. The upper torso follows right and the tail pearl lags slightly left of its neutral arc.
- `180 down`: chin tucks, eyes and muzzle aim downward, upper eyelids lower slightly, forehead and mane pitch forward, and the upper torso compresses gently. Both ears remain visible; paws and base do not move.
- `270 screen-left`: muzzle and nose shift clearly to screen-left of head center; the screen-left face side and ear become more visible while the far face side and far ear are partly occluded. The upper torso follows left and the tail pearl lags slightly right of its neutral arc.

## Motion budget and continuity

Each 22.5-degree step moves the eyes, muzzle, head, upper torso, ears/mane, and tail pearl by a small comparable amount. No adjacent pair may jump more than roughly one eighth of the full up-to-down or left-to-right excursion. `157.5 -> 180`, `337.5 -> 000`, and the row boundary must be as smooth as all other pairs. Scale, baseline, lower-body anchor, pearl attachment, and plush identity remain constant throughout the clockwise loop.

Row 9 advances `000 -> 090 -> 180` through even intermediate poses. Row 10 begins one step beyond `157.5`, advances `180 -> 270 -> 000`, and ends at `337.5`, one step before the approved `000` pose.
