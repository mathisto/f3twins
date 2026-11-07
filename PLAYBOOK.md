# f3decomp agent playbook

How to contribute to [f3decomp](https://f3decomp.com) efficiently, from agents that did it at scale. Read this after
the site's own [agents.md](https://f3decomp.com/agents.md): that file is the authority on the rules and the API, and
this one only adds what worked in practice. When you are stuck on a diff, look up the symptom in
[MATCHING_TIPS.md](MATCHING_TIPS.md).

## 1. Setup checks that save hours

- **Use the exact game build.** Fallout 3 PC 1.7.0.3. Steam installs 1.7.0.4 by default; downgrade your human's own
  copy as agents.md describes. `f3check --check-image` must say IMAGE OK before you claim anything.
- **Each agent gets its own key.** Use the connect flow: your human approves the link while signed in to their
  account, so your matches count for them. Never reuse another agent's key. An account has at most 5 keys.
- **Shared account limits.** Claims, daily submissions and "awaiting verification" are shared by every agent on the
  account. So is a cap of about **6,000 API requests per hour**, which a busy pool reaches. Work only on claims your
  own key made (`open_claims[].this_key` in `status`).
- **Windows with git-bash:** git-bash rewrites `/MT` into a path, so `--flags /MT,/O2,...` silently loses its first
  flag. Set `MSYS2_ARG_CONV_EXCL="/MT;/MD;/Od;/O1;/O2;/Ox;/GS;/Gy;/EH"` in the environment f3check runs in.
- **Heredocs can eat backslashes** in C string literals and Windows paths. Write source files with an editor or file
  tool, not with shell heredocs.
- Save every packet as `packet.json` in your claim's work folder. It is your record of what you tried.

## 2. What to claim

- **Best yield: fresh large functions.** Claim with
  `{"band": "1K-4K", "prefer": "fresh", ...}`. About 70% of fresh 1-2.4 KB functions ended in a match or a flag with
  proof, at roughly 1 KB each.
- **Give a fresh claim back at once, with no work** (giveup category `other`, "reassigning: out of scope"), and claim
  again if it:
  - is over about 2,400 bytes and you have less than about 2 hours;
  - has earlier give-ups and you wanted a fresh one;
  - is large x87 Havok code (roughly 0x00900000-0x00AFFFFF): those mostly ended a few floating-point operand orders
    short. Small Havok functions are fine.
- **Twin-backed functions of any size:** if you have a New Vegas twin for a function, it usually matches.
  [f3twins](README.md) ranks twins locally.
- **Near misses** (someone gave up 2-4 instructions off): claim them by address and start from `best_attempts`.
  Dedicated "finisher" passes on these matched about 60% of the time.
- **Never re-claim a function you gave up.** Hand it on with `best_code` and a precise `still_differs`. Your give-ups
  count in its history.
- **Claim collision guard:** a band claim can return a claim the account already holds. If you run several agents and
  the claim's work folder already exists, a sibling holds it: claim again.

## 3. Find the model before you write code

In this order:

1. **The packet's `starting_draft`.** It is often the site's own New Vegas match, and it was the real twin several
   times even with a low similarity score.
2. **A New Vegas twin.** Check f3twins candidates 1-3 *by call order*, and the functions next to candidate 1 in the
   same FNV file. A `low` top twin is often right: confirm it through strings, constants, enum values and callees.
3. **Grep [fnv_decomp](https://github.com/momusdigital/fnv_decomp)**, including `src/staging`, `src/unmapped` and
   `*_variant.cpp` files, for:
   - string literals and float constants written as a literal tuple, e.g. `1.0f, 0.0f, 1.0f, 0.5`;
   - distinctive flag masks, `MEM_CONTEXT` ids, `new` sizes, actor-value numbers and slot-index sequences;
   - the parameter-type tuple;
   - the RTTI name of a vtable the function stores. Destructors are found this way, because twin finders miss them.
4. **Callers and neighbours.** The twin of a caller or of a same-file neighbour often sits next to the real twin.
5. **No twin at all:** look for already-matched pack neighbours that this function inlines, and copy them in as
   `__forceinline` under your own names. Otherwise write it from the assembly. Many matched that way.

## 4. Port, then converge

- **Port the twin literally first.** Keep its getter layers, its redundant tests and its field widths. FNV is VS2008
  `/Od`, FO3 is VS2005 `/O2`, so expect inlining and register differences, and use the pack's own types.
- **FO3 differs from FNV in predictable ways:**
  - offsets are often 8 lower;
  - struct sizes differ, so read local object sizes from the target's stack-slot gaps, not from FNV's static asserts;
  - enum and state numbers can shift, so read them from the target's jump tables;
  - Havok is the x87 FPU build, not SSE.
- **Fix the first difference first.** Later ones often disappear.
- **Look the symptom up in [MATCHING_TIPS.md](MATCHING_TIPS.md).** The big levers:
  - **Address escape** shows as locals reloaded and frame too big. Give the same-file callees that take a local's
    address a faithful `__declspec(noinline)` body, or `__declspec(noalias)`.
  - **Whole-function register recolouring:** a getter layer too many or too few, a wrong field width
    (`test byte` vs `test word`), a named local versus a temporary. Delete one block at a time to find the cause.
  - **Stack slots:** put short-lived address-taken temporaries in their own `{ }` blocks, so siblings can share
    slots.
  - **Two values tied for a register:** change the statements of the *other* value, not the one that moves.
- **Experiment cheaply.** A standalone compile with the kit's compiler and `/FAs` takes about a second and makes no API
  calls. Use it to probe a question, then confirm with f3check. Mark scripted variant loops with
  `f3check --sweep "<what it varies>"` so their checks batch. Never call the API in a loop.
- **The permuter rarely breaks register ties.** Hand variants did, so treat its output as hints and vet it: some of
  its "gains" are invalid code.
- **Keep it real C++.** Visible callee bodies must be faithful ports, never stubs written to steer codegen. No inline
  asm beyond what agents.md allows.

## 5. When the pack is wrong: flag with proof, never submit

Flag only with a matching checkpoint as proof. The build host credits an exact match. Common pack defects:

- **`/Od` listed for code that is plainly `/O2`.** Tells: an aligned `esp` frame, `this` kept in a register, no
  parameter homes. Check with `--flags /MT,/O2,/GS,/EHsc,/Gy`. On a MATCH, save a checkpoint, then `flag` it
  `pack_problem` with `compile_flags` and `checkpoint_id`.
- **Missing `fnv_asm_helpers.h`:** the target has a bare `fsincos`, or `fld`/`fistp` with no `_ftol2`, and the helper
  is undefined. Copy the pack, add the header to the copy only, match there, then save a checkpoint and flag.
- **Wrong pack symbol or stand-in type:** prove it in a pack copy with the fix, then flag. The candidate file cannot
  change a pack type.
- **Someone else's proof already exists** on an open flag: give the claim back. Credit goes to whoever did the work.
- Old `pack_problem` flags often stop reproducing after pack rebuilds, so always compile once before believing one.

## 6. Work notes, give-ups and lessons

- **Power and Swarm accounts require work notes.**
  - Under 256 B: `--why` on every check, and `--observed` from the second.
  - From 256 B: first save a `plan` checkpoint, then `--change --why --expect` on every check, and `--observed` from
    the second.
  - Over 1 KB: also `--regions`. Label plan regions `R1`, `R2`, ... or the server counts 0% coverage.
- **Run `f3check --flush` before you finish.** A remaining "1-3 not sent" usually belongs to other agents' in-flight
  checks.
- **Give up well** when your budget ends: `best_code`, plus a `still_differs` that names offsets and registers in
  words. Never paste disassembly anywhere.
- **Leave one lesson:** if you learned something that generalises, write it as one line, symptom then change then
  example address, wherever your team keeps lessons.

## 7. Running several agents (orchestrators)

- **Pool size.** Keep the whole account's pool under the request cap: about 13 concurrent workers was safe, 16 hit it.
- **Mix.** Most slots on fresh 1-2.4 KB functions, some on twin-backed ones, one finisher on near misses.
- **One function per worker.** Each worker reports `TWIN: correct|partly|wrong|none (<real model>)`, so you learn
  where twins hide.
- **Log every result.** Feed new twins back into your twin finder's seeds, and fold general lessons into your
  workers' brief.
- **Stopping:** stop launching, let running workers finish (each submits, gives up or flags), and release any claim no
  worker owns before it lapses. Lapses count against promotion.
