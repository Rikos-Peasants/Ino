# April Fools Avatar Cycle

Place the following PNG files in this directory:

| File | When used |
|------|-----------|
| `1.png` | Hour 0  (midnight) |
| `2.png` | Hour 1  |
| `3.png` | Hour 2  |
| `4.png` | Hour 3  |
| `5.png` | Hour 4  |
| `6.png` | Hour 5  |
| `7.png` | Hour 6  |
| `8.png` | Hour 7  |
| `9.png` | Hour 8  |
| `default.png` | Hour 9 (1-hour break, then cycle repeats) |

The bot cycles through images **1 → 9** (one per hour), then shows `default.png` for one hour, then loops back to `1.png`. This only activates on **April 1st**.

`default.png` should be the bot's normal profile picture so it gets restored during the break hour.
