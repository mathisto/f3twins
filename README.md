# f3twins: find the New Vegas twin of a Fallout 3 function

For [f3decomp](https://f3decomp.com) contributors. Give it the address of a Fallout 3 function. It ranks the functions
of the finished [New Vegas decomp](https://github.com/momusdigital/fnv_decomp) that most likely come from the same
original source, with their `file:line`. Fallout New Vegas is a branch of the Fallout 3 codebase, so many open Fallout 3
functions already exist there as matched, readable C++. Start a match from the twin instead of from nothing.

```text
$ python f3twins.py 0x00664aa0
== 0x00664aa0 (1024 B)  confidence: high
    86.2  AMMenuView::UpdateHolotapePlayback  fnv 0x0079a660  src/fallout/interface/menus/mapmenu.cpp:7232
    20.9  SaveNamer::BuildSaveFilename        fnv 0x00860ae0  src/fallout_shared/tessaveloadgame.cpp:6335
    20.3  NoteMenu::SetNote                   fnv 0x007993d0  src/fallout/interface/menus/mapmenu.cpp:7801
```

## Results

**Live test.** One batch of eight claims, about 1 KB each, all taken from the top of the high-confidence list:

- 7 of the 8 predicted twins were the same function. The eighth was a Havok function whose structure was right but
  whose code differs, because Fallout 3 ships an older x87 build of Havok than New Vegas.
- 6 of the 8 matched, several within 3 to 5 compiles. The other two got close, and their best drafts are saved on
  the site.
- For comparison, an earlier batch without twins matched 3 of 5 functions in the same size range, and took longer
  per function.

**Validation** on 5,867 known pairs. The validation hides 80% of the known anchors, so the tool has less context
than in real use:

| Size | Top-1 correct | Correct twin in top 3 |
|---|---|---|
| under 128 B | 46% | 56% |
| 128–255 B | 50% | 61% |
| 256–511 B | 60% | 70% |
| 512 B–1 KB | 69% | 78% |
| over 1 KB | 64% | 74% |

**Confidence labels** are calibrated on the same holdout:

| Label | Top-1 right |
|---|---|
| high | about 93% |
| medium | about 76% |
| low | about 45% |

Treat low as a lead to check, not an answer. On our copy, about 845 open functions up to 1 KB came out high or medium.

**One night of real use** (2026-11-05): about 230 claims were taken from its list. The top twin was right 76% of the
time, partly right 11% (right model, but Fallout 3 changed or inlined parts), and wrong 13%. Two fixes came out of the
misses:

- A top pick backed only by float constants is now always `low`; shared floats such as 1.0 and 0.5 misled it.
- `high` now needs at least one string, RTTI type or non-trivial constant, or two named callees. A pick that rests on
  link-order anchoring alone is capped at `medium`.

**`seeds.json`** holds 113 pairs that were found or confirmed by hand while matching. They are used
as extra anchors. Add your own the same way (`{"<F3 addr>": "<FNV addr>"}`), or point `F3TWINS_SEEDS` at another file.

## How it works

The Steam `FalloutNV.exe` is encrypted on disk, so the New Vegas side is the decomp's *source text*. The Fallout 3
side is the machine code from your own game image. For each function the tool collects the following and scores
shared ones by how rare they are (IDF):

- string literals;
- RTTI types used in `dynamic_cast`;
- non-trivial integer constants (trait IDs, record codes) and float constants;
- the names of the functions it calls.

Callees are named through functions known on both sides: same-named `Class::Method` pairs, and Fallout 3 functions
that the project's own reuse tooling named `FUN_<New Vegas address>`. Three more signals:

- **Link order.** Both games keep their source files and functions in the same order, so a function between two known
  twins most likely has its twin between their New Vegas counterparts.
- **Callers.** A function's twin is likely called by its caller's twin.
- **A second round.** Callees are named through their own first-round twins.

## Setup

You need your own Fallout 3 1.7.0.3 image (the one `f3check --check-image` accepts), the f3decomp shared files, a
clone of fnv_decomp, Python 3.10+ and `pip install capstone`.

```bash
git clone --depth 1 https://github.com/momusdigital/fnv_decomp
export F3CHECK_IMAGE=/path/to/Fallout3.exe          # the same variables f3check uses
export F3CHECK_SYMBOLS=/path/to/f3decomp_symbols.json
export F3CHECK_INDEX=/path/to/function_index.json
export FNV_DECOMP=/path/to/fnv_decomp
export F3TWINS_CACHE=/path/to/private/f3twins-cache  # optional; default ./f3twins-cache
export F3TWINS_SEEDS=/path/to/my_seeds.json          # optional; default ./seeds.json
python f3twins.py build      # a few minutes, once; again when the shared symbols change
python f3twins.py all        # precompute every function, seconds
python f3twins.py 0x00664aa0 # look up; `live <addr>` shows the evidence behind each score
python f3twins.py validate 0.8
```

## Using a twin well

- **A twin gives structure, names and constants, not bytes.** Fallout 3 was built with Visual C++ 2005 at `/O2`. Most
  New Vegas game code was built with Visual C++ 2008 at `/Od`. Expect Fallout 3 to inline getters that New Vegas calls,
  to allocate registers differently, and to drop or add the odd branch.
- **Use the pack's types and the claim's own flags.** Copy the twin's control flow, not its declarations.
- **Port near-identical twins nearly line for line.** In the test batch, the window procedure, the holotape view and the
  menu selection functions needed only offsets and inlined getters, then one or two codegen fixes.
- **Weak spots:** generic container code with nothing distinctive (list removal, array growth) and Havok internals.
- **Ties:** results can differ slightly between runs where candidates tie.

**New to f3decomp?** [PLAYBOOK.md](PLAYBOOK.md) is a practical guide for agents: what to claim, how to find the model
before writing code, how to prove pack defects, and how to run several agents on one account.

**Once you have the twin:** [MATCHING_TIPS.md](MATCHING_TIPS.md) collects the VS2005 `/O2` matching techniques from one
night of about 190 submitted matches, sorted by what the f3check diff shows. Tips that need fnv_decomp are marked.

## Privacy

`build` reads your game image and writes its features to the cache, and `all` writes a twin list derived from it. Keep
the cache private and never share it: it is derived from game files. This repository holds only the script. It has no
game data, no f3decomp data and no output.

## License

MIT (see LICENSE).
