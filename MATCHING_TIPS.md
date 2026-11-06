# Fallout 3 matching: techniques by symptom

These are field notes from one night of matching f3decomp functions (about 190 submitted matches, 33 flag proofs, 85 give-ups), merged and sorted by symptom.
Target: Fallout 3 PC 1.7.0.3, built with VS2005 SP1 (cl 14.00.50727.762), mostly `/O2` even where the pack lists `/Od`. New Vegas's fnv_decomp is VS2008 and mostly `/Od`: port its source *shapes*. Its codegen will not carry over.
How to use it: find what your f3check diff shows in section 1, then try the levers it points to (sections 2-4). Section 5 covers pack and flag problems, 6 covers tooling, 7 lists what is still open.
Read the site's `compiler_tips.md` and `large_functions.md` first. This file does not repeat them. Where a finding extends or contradicts them, it says so with a pointer ("cf. tips: <section>").
Tips marked **[needs FNV]** need the fnv_decomp source. The rest are universal. Addresses are FO3 unless marked FNV.

## Top 10 levers by number of matches tonight

Counted from the night log's outcomes and notes; one function can count under several levers, so counts are rough.

1. **Literal port of the right FNV twin, refined afterwards** (about 150 of the 191 submits had a correct or partly
   correct twin). A fresh port beat earlier restructured near misses again and again. **[needs FNV]**
2. **Re-claiming earlier give-ups** (about 70 matches were functions someone had given up before). Usually the fix was
   a fresh port or one lever below, applied to the saved `best_code`.
3. **Finding the real twin when twins.py is wrong or low** (38 submits had a wrong twin listed): grep for strings, float
   tuples, sizes, RTTI, or read candidates 2-3 and the neighbours (section 4). **[needs FNV]**
4. **Flag proofs for `/Od`-listed code that is really `/O2`** (33 proofs, each a MATCH under `--flags`; section 5).
5. **Same-file callee bodies to stop address escape** (`__declspec(noinline)`, `noinline inline`, `noalias`; about 28
   matches; section 2.1).
6. **Inline getters and FNV getter layers** in place of direct field reads (about 25; section 2.2).
7. **Scripted variant sweeps** (`f3check --sweep`, cross products of neutral knobs; about 15 matches, several after
   permuter runs of hundreds of trials found nothing).
8. **Missing `fnv_asm_helpers.h` proofs** (a pack copy with the header; 9 flags).
9. **Real types**: `signed char` flags, `short` refcounts, `bool` returns, `int` vs `unsigned` (about 9; section 2.5).
10. **Block scopes and declaration placement for slot sharing** (about 9; section 2.3). A close 11th: calling-convention
    and arity fixes (thiscall vs stdcall, fastcall, free `__stdcall`, `ret N`; about 8; section 2.12).

## 1. Reading the diff

- **Whole-function register recolouring** (callee-saved registers differ everywhere, instruction shapes identical): one
  value too many or too few in some hot block, often far from where the swap shows. Typical causes are a spare named
  intermediate, a missing getter layer, a ternary whose condition calls a virtual, a wrong-width flag test, or an
  escaped local. Probe it: delete one block (then one statement) at a time, or replace one value with a constant, and
  watch which change flips the prologue. Examples: `0x005cf920`, `0x00769fa0`, `0x00472ce0`.
- **Scratch registers rotated by one over a later region** (`eax`/`ecx`/`edx`): an extra or missing temporary
  *earlier*, possibly in an earlier loop or 0x100 bytes before. A field read vs an inline getter, or a folded byte test,
  is the usual cause (`0x00446220`, `0x0071a690`). Sweep neutral rewrites in the code *before* the bad region.
- **A single swapped callee-saved pair**: cf. tips "The last instruction or two" (set-first rule). Beyond it: which of
  kept-value/copy receives the select (`0x0061c5b0`), real virtuals vs vtable casts (`0x00534b20`), and a shared
  refcount base class (`0x0069a4b0`).
- **Frame too big by N x 12**: `NiPoint3` temporaries the original packs into one slot (section 2.3). **By 0x10/0x20**:
  `hkVector4`/aligned locals or matrices that should share. **By 4**: one pointer copy, out local or struct cursor in a
  slot of its own. **0x10 plus a `/GS` cookie the original lacks**: a GS buffer you created (section 2.5).
- **Frame too small**: the original has a slot you folded away. A float rounded through an inline getter's temp
  (`0x004f2a30`), a local declared at function scope (`0x0045afe0`), or a register web you merged (`0x004e0890`).
- **Same instructions, only slot offsets differ**: liveness plus escape plus scope. Fix code before slots; slots often
  fall into place once the code is right (`0x00540270`). cf. `large_functions.md` "Stack slots under /O2".
- **x87 operand order swapped** (`fld a; fmul b` vs `fld b; fmul a`, `fld st0` dup vs memory operand): the rank sort,
  not source order (cf. tips "Operand order"). It moves with symbol numbering: named locals, `this`, dead lanes
  (section 2.8). Large Havok functions often stay open (section 7).
- **One instruction out of place around stores**: may-alias links from an escaped local, an inlined sub-object method
  holding later stores, or a barrier (sections 2.1, 2.7).
- **A helper inlined where you call it, or the reverse**: the inline budget runs out in big functions; `__forceinline`
  fixes it. A member you name `FUN_<addr>` is always a call, because the checker drops `FUN_` bodies. Under `/EHsc` a
  function returning an object with a destructor by value never inlines.
- **EH state count differs**: count member and local destructors and `new`-expressions. A lone high state on one
  inlined `new` means a big callee was inlined and folded but kept its own numbering (`0x005a9540`; section 2.10).
- **Tail call vs real call to itself**: any escaping local (a `char buf[260]`) blocks tail-recursion elimination.
  Scope it into the inner block (`0x004ee000`).
- **Jump-table compare signedness**: `ja` where the original has `jg` (or `jl`/`jle` on a form type) means the switch
  value comes from an `int` getter, not `unsigned` (`0x007c9d80`, `0x004f6570`). An `or -1`/`sub` pair plus a
  `fmul` by -4.0 before a table is VS2005's own `switch ((int)(r * 4.0))` (`0x007e3f20`).
- **Constants and imports shown as `0xe000x000`** in a shifted diff are display only. They bind once the code before
  them lines up, and `--json` `diffs` counts the real bytes (`0x00af4210`, `0x00737460`).
- **`compiled function extent differs`, every instruction identical, function has `try`/`catch`**: the index cut the
  function at its `ret` before the catch funclets. Flag it as `index_problem` (section 5).
- **A `push` one instruction early or late around calls**: check the callee's `ret N` and return type before anything
  else (section 2.12).
- **`cmp reg,<zero register>` where you get `test reg,reg`**: the value is compared against a coloured zero web (result
  local starting at 0, or an inline wrapper that returns the call's value; sections 2.2, 2.3).

## 2. Universal VS2005 /O2 levers

Format: *Symptom* -> change. Why. Examples.

### 2.1 Address escape (the biggest single lever)

Extends tips "Escape: define callees from the same file".

- *Struct-copy loads that will not hoist above a `rep movs`, stores to a local that all land before later loads, a value
  reloaded from its slot after a call* -> give every same-file callee that takes the local's address a real
  `__declspec(noinline)` body that does not keep the pointer. The compiler then knows the address is not captured.
  `0x00710870`, `0x004e0160` (172 lines to MATCH in two compiles), `0x004e3dc0`.
- *One body did nothing* -> escape counts across the whole function. If another opaque callee still takes `&k`, put
  `__declspec(noalias)` on *every* callee that takes it. `0x004fd4e0`.
- *Bodies for the direct callees changed nothing* -> they hand the pointer on to big opaque callees (an escape chain).
  `__declspec(noalias)` on the direct callees took 286 diffs to 13 in one check. Try noalias before porting bodies.
  `0x004ccbb0`.
- *An out-param local reloaded after only one of two later calls* -> `__declspec(noalias)` on the filler (your own
  name; calls bind by position), and read the member directly with no cached copy. `0x00829790` (13 earlier give-ups),
  `0x00608760`, `0x0071a690`.
- *A pointer kept in `esi` across a same-file call, but your visible noinline body makes it `edx`* -> declare the body
  `__declspec(noinline) inline`. The compiler still sees that it writes no memory but treats `edx` as clobbered.
  `0x0046b830` (112 to MATCH).
- *An x87 value kept on the FPU stack, or a global kept in a register, across a call* -> the compiler does that only when
  it can see that the callee leaves the FPU or the global alone. Give it a same-file body, even one defined after the
  caller. `0x006237e0`, `0x0043e5c0`. The converse also holds: if the original reloads loop invariants on every pass,
  the callee is opaque there, so leave it without a body (`0x0048fff0`).
- *The buffer still reloads* -> the visible body must be pure: a body that writes even one static global brings back
  the reload. `0x005b7340`.
- *Header inlines (NiPoint3 `operator-`, `Length`, NiTArray `SetAt`) that stay calls in a big function* -> they still
  need their inline bodies in your draft, because the bodies tell the compiler they write no memory. `0x006931c0`,
  `0x00787580`.
- *Smart-pointer local refilled by a by-value return and reloaded in the loop* -> noinline bodies for the hidden-return
  callee (`BSSimpleArray::GetAt`) and for the filler, and a visible body for the out-of-line copy-assign too.
  `0x004e0160`, `0x004dbee0`, `0x005ee080`, `0x006f1080`.
- *BSString `pString` reloaded after calls* -> noinline bodies for `Set` (0x4019c0), assign, `+=` and append, or for
  the whole sprintf chain (one self-contained `FUN_00403a00` body is enough). `0x00686ee0`, `0x004aaba0`, `0x0068d420`.
- *A local list's item spilled and a zero cached in a spare register* -> its dtor's `RemoveAll` lets the list escape;
  give `RemoveAll` a noinline body. `0x004e0890`.
- *Map and list loops reload, frame a few dwords big* -> real Gamebryo noinline bodies for NiTMap `GetFirstPos`/
  `GetNext`/`GetAt`/`SetAt` and for list `InsertHead`/`AddTail`. `0x0043e5c0`, `0x00499b30`, `0x006ce8a0`,
  `0x00497160` (457 to MATCH).
- *A neighbour's callee body you copied makes things worse* -> it may be a stand-in. Disassemble the real callee first;
  declaring it without a body can be closer. `0x005d91a0`.
- *A global store that the original sinks below vtable loads* -> make the global `static` (file or function scope) so
  it cannot alias pointer loads. `0x00664aa0`.

### 2.2 Inline getters and getter layers

- *A scratch rotation or one load scheduled in the wrong place* -> read the field through a one-line inline getter
  (`GetTile()`, `GetFormID()`). The getter's result is not CSE'd with plain field reads, which changes temporaries and
  costs. `0x00653d40`, `0x0076f560`, `0x006d36e0`, `0x00481490`, `0x007ec020`.
- *The converse: a float field gets an extra `fstp`/`fld` round trip* -> read it directly (`0x007c9d80`). *A frame
  one slot short, with that round trip in the original* -> the factor came from an inline getter returning `float`
  (`0x004f2a30`).
- *No single-site edit fixes one scratch load* -> sweep the cross product of getter-vs-field at every use of that
  member (2^n files). Only one mixed combination matched `0x006a4b20`, after 700 permuter trials.
- *A flat getter merges return paths the original keeps apart* -> keep FNV's two inline layers. `0x00557780`,
  `0x00704fd0`; a TLS-cached key select wants two nested inlines, `0x007ce6e0`.
- *Callee-saved registers flip back whenever you drop a layer* -> match every getter layer FNV has. Getters on reads
  helped, but inline wrappers around plain calls hurt: direct calls cut 70 lines. `0x006b7bc0`. **[needs FNV]**
- *A join kept by the original (zero set, then a test at the join), threaded away in yours* -> read the last field
  through its own inline getter in the true arm (`p ? p->GetBody() : 0`). Result locals, if/else and forceinline all
  threaded it. `0x0076f560`, `0x00622520`.
- *A redundant second null test survives in the original* -> it survives only when the null path reaches it in the IL.
  Use an inline getter whose fallback passes the compare (`return process ? process->level : 0;`). `0x004fc020`.
- *A global read after a call where the original reads it before* -> an inline getter is evaluated ahead of the other
  call in the same expression. `0x00646cc0`.
- *A bool virtual's result compared with the cached zero* -> the wrapper returns the call's value: `if (!p) return
  false; return p->IsX();`. `return p && p->IsX();` gives `test`. `0x004ebb30`.
- *An esi/edi swap between a loop index and a list pointer* -> read the loop bound through an inline const getter
  (`j < list->GetSize()`). `0x005e7120`.
- *A zero cached in `ebx`, or a pointer cursor where the original uses base+offset* -> read the array pointer through
  an inline getter (`data->GetVertices()[i]`). 139 to 55 lines, `0x007952f0`.
- *A pointer-adjust test or component field read that you fold* -> a joining getter (`type == 1 ? GetOwner() : 0`),
  or a member of the component class whose ternary rereads the field. `0x007bcff0`, `0x00776670`.
- *A byte read once for both a test and a push* -> the two bytes are one `unsigned short` read through masking getters,
  which are not CSE'd. `0x006bd420`.

### 2.3 Named locals, block scopes and declaration placement

Extends `large_functions.md` "Stack slots under /O2" (blocks for sharing, use counts).

- *Frame too big by N x 12* -> put each short-lived `NiPoint3` temporary (out-param, by-value return, copy) in its own
  `{ }` block, and keep a `float` result local outside. `0x007d2380`. The same goes for 16-byte vectors and 36-byte
  matrices: `0x006b9320`, `0x0075aaf0`, `0x005b7c10`.
- *A long-lived local declared after a sibling block keeps its own slot* -> wrap it and its code in a sibling `{ }`
  block. `0x004f31a0`.
- *The converse: frame 4 bytes short, an address-taken local sharing a spilled index's slot* -> declare it at function
  scope, not in the inner `if` where FNV has it. `0x0045afe0`.
- *Disjoint blocks still do not pack* -> the scope can decide it, not only liveness. Nesting under FNV's
  `if (pInfo) { ... }` rather than `if (!info) continue;` let two locals share. `0x006c8e30`.
- *An out-param slot is off* -> declare the out local inside the innermost block that sets it. `0x00554dc0`,
  `0x0071a690`.
- *One load hoisted above an `if`/`else` for both arms* -> declare the local before the `if` and assign it in each arm.
  *A condition chain laid out unlike the original* -> repeat the success statement in two arms. `0x0075f960`.
- *A pointer chain loaded at the wrong time, or esi/ebx swapped around a global's member* -> hoist the chain into a
  named local (`Map* map = g->map;`). `0x006d63b0`.
- *The opposite: one named intermediate too many* -> fold it (`Entry* e = arr[i]->getBegin();`). `0x00a26e70`. Old
  drafts can carry "compensating" spare locals: remove them one at a time after a type fix (123 to 8, `0x008e48b0`).
- *A fresh pointer passed by `T* const&`, which the original keeps in a register* -> pass a named copy
  (`T* entry = p; list.Append(entry);`). If the home slot is written at the definition instead, use one variable plus a
  noinline append body (`0x004e3dc0`). If the swap remains, assign the select to the *copy* (`0x0061c5b0`).
- *x87 locals reloaded in the wrong order* -> reload order follows first *definition*. A dead `= 0.0f` initialiser on
  the late ones fixed it. `0x007a2ea0`.
- *Two 12-byte vectors in swapped slots* -> the source had two named locals (`kDelta`, then `kFlat = kDelta`), not one
  local plus the operator's temporary. `0x007e3f20`.
- *A late local reuses the wrong parameter home* -> copy that parameter into a local at the top. `0x006d36e0`. *A float
  result in a fresh slot instead of the dead parameter home* -> declare it after the first load from the parameter.
  `0x007952f0`.
- *Two spill reloads swapped after an inlined block* -> declare the block's pointer at function scope with an
  initialiser (`S* phantom = 0;`). `0x008d8370`.
- *A call result compared with the cached zero* -> keep it in a local that starts at 0
  (`int found = 0; if (g) found = g->Query();`). `0x006dae50`.
- *Constant arguments pushed before a call in the same argument list* -> name the first call's result as a `double`
  local. `0x006598d0`. *A bool argument that the original stores to a byte slot in both arms* -> name it,
  `bool aim = p ? p->IsAiming() : false;` (239 to MATCH, `0x006ff2a0`).
- *`rand()` called after the getter where the original calls it first* -> sequence it with a comma and a function-scope
  local: `(roll = rand() % 100, roll < (unsigned)*s.Get())`. `0x0071c3f0`.
- *Only the x lane of an inline `a + b` swapped* -> bind the left operand first, `const NiPoint3& pos = ...;`.
  `0x0075aaf0`, `0x006fb6c0`.
- *Base/index swapped in every `[a+b]` of parallel-array loops* -> a named local copy of the output pointer flips the
  rank of all of them (38 to 2). `0x0058e230`. Extends tips "Operand order".
- *Frame 4 bytes too big with a cursor struct* -> split FNV's cursor structs into scalar locals; a struct keeps a slot
  even for its register-held member. `0x0045b4b0`.
- *A by-ref temp that sits last in the frame* -> pass a bound temporary (`prev->Remove((T)id)`); a named local takes a
  slot ahead of the others. `0x0045b4b0`. *A key temp that rotates later registers* -> a block-local copy,
  `{ T* item = this; map->RemoveKey(&item); }`. `0x004f6570`.
- **Contradicts `large_functions.md`** ("names make no difference at /O2"): in `0x006d1490` two `int`s swapped slots
  until one was renamed, and the FNV twin's own local names matched. This is rare; try it last.

### 2.4 By-value vs by-reference helper parameters

- *A stack copy of a pointer you also keep in a register, later passed by address into a `const T&` callee* -> the
  original inlined a helper whose *parameter* is passed by reference. Write the helper with a local copy for the
  register uses and the parameter for the reference. `0x00bee1c0`.
- *A call result stored at once and later passed by `T* const&`, with its slot reused by a spill* -> make that block an
  inline helper taking the pointer *by value*. Parameters pack by liveness. `0x006c8e30`.
- *Frame 4 too big, a by-ref pointer copy that will not share with a `NiPointer` argument's EH temp* -> pass a
  one-member struct (`struct Ref { T* p; };`, callee takes `const Ref&`). `0x005e8650`.
- *Six float parameters with odd slot reuse* -> two `NiPoint3` by value; a struct parameter's home is reused only once
  all of its members are dead. `0x006c5e20`. Three stack args copied as three `mov`s are one `NiPoint3` by value,
  `0x007010f0`. Three floats passed as `&x, &y, &z` to scattered slots are three scalars, `0x007d2380`.
- *A by-value struct argument evaluated late* -> give the struct an inline copy ctor and an inline `~T() {}`.
  `0x00664aa0`.
- *A list call that stores the pointer into a fresh temp first* -> cast to the list's base type, which takes
  `const T&` (`h->AddHead((Actor*)p)`). A same-type cast makes no temp. `0x00791a20`.
- *Walker and item registers swapped in a list scan* -> the inline `AddHead(T*& item)` reference form. `0x00783ce0`,
  `0x00633ff0`.
- *Entry-block loads out of order around one same-file call* -> call it through a plain inline forwarder (`0x00923f00`).
- *Thiscall `ret 0x1c` with an inlined string init before every call* -> one `std::string` by value, passed on by
  value. `0x00be4b10`.
- *An inlined Find that reloads the data pointer in the loop* -> keep FNV's `Find(item, start, compare)` with an inline
  compare function passed by pointer. `0x005d5490`.

### 2.5 Types

- *A flag test kept as `movzx`/`shr`/`test` that every form you write folds into a memory `test`* -> the field is
  `signed char`, converted before the shift: `((unsigned int)flags >> 1) & 1`. This form also fixed vtable registers
  far away. `0x00564030`, `0x00767660`.
- *A byte load plus byte shift where every char form gives a memory `test`* -> the field is `unsigned short`; VS2005
  narrows the load itself. One test fixed 115 instructions 0x100 bytes away. `0x0071a690`.
- *`add word [m],-1`* -> a `short` refcount (Havok `m_referenceCount`); `unsigned short` gives `0xffff`. `0x009e3e00`,
  `0x008e48b0`, `0x00a4d550`.
- *A call result pushed one instruction early, or `setne` after a call* -> the callee returns `bool`, not a pointer,
  `int` or `unsigned char`. `0x004f9c50`, `0x004399f0`. *A `mov ax,imm` early exit* -> `unsigned short` return and
  parameter. `0x006989d0`.
- *A saved flag kept in `bl` where the original spills it to a dead parameter slot* -> type it `bool`, not
  `unsigned char`. `0x0044b980`.
- *`jbe` on `count > 0`, or `movsx` pushes* -> an `unsigned` count, an `int` parameter (`0x008d4180`, `0x00540270`).
- *Havok setters copy a byte through the wrong register* -> flags are `hkBool` (a one-char struct) passed by value.
  `0x00946380`.
- *`fcomp qword` where the original has `dword`* -> the left side is `double`; make the callee return `float`. A double
  sentinel must be bit-exact: `(double)FLT_MAX` is not `-3.402823466e+38`. `0x007da3d0`, `0x0049d080`.
- *A qword constant equal to a rounded float* -> `double fTolerance = 0.0001f;`. `0x005e2110`.
- *Two complete x87 store arms where you get one hoisted conversion* -> a *float*-typed ternary (`s ? n * 2.0f : n`).
  `0x00bc7380`. Extends tips "Floating point".
- *`fiadd` where you get `fild`+`faddp`* -> the int term is cast to `float`. *A dword 2^32 fixup after an unsigned
  `fild`* -> a `(float)` cast of the unsigned value. `0x004cfe50`, `0x0063f060`.
- *Four ints scaled by one float with the wrong dup form* -> `r.left *= ratio;` (int `*=` float). `0x00624de0`.
- *A bool member copied as a byte where you get a dword* -> write a member-wise inline `operator=`. `0x0049d080`.
- *An empty stand-in member sitting at the next byte* -> give it its real fields. `0x0051d140`. *A field 2 bytes off*
  -> check `short` alignment after a `char`. `0x005a85f0`.
- *A `/GS` cookie the original lacks* -> any byte array member makes a struct a GS buffer (`unsigned char rules[4]`,
  and `__m128`'s union). Use `int` members or an aligned float struct. `0x00a47ca0`, `0x008d2120`.
- *Named string locals placed at the top of the frame* -> under `/GS` they go next to the cookie as GS buffers, and
  temporaries do not. A diagnostic `/GS-` compile shows which ones moved. `0x00bba060`. Extends `large_functions.md`.

### 2.6 Volatile reads and views

The tips endorse volatile views (cf. tips "Registers: colouring by cost"). Tonight's extensions and limits:

- *A byte global tested by load-then-test where you get a memory `cmp`, with rotated vtable registers after it* ->
  `extern volatile bool DAT_x;`. 278 lines to MATCH, `0x006edbe0`; also `0x00626e70`.
- *A pointer parameter that the original rereads from its stack home at every call* -> declare that parameter
  `volatile`. It fixed the frame and every slot. `0x009ddf50`.
- *An out-param result loaded into scratch and then copied to `esi`* -> `void* volatile found;` (`0x005d9f90`), or a
  volatile read of the out (`0x006d0200`).
- *One scratch register off on a parameter that the loop head re-reads* -> a volatile view of it. `0x008e48b0`.
- **Limit:** any volatile access in a function seems to turn off slot packing for disjoint block locals (frame +8).
  `__declspec(noalias)` on the filler gave the same registers and kept the frame. `0x00608760`.
- **Limit:** `volatile` keeps a dead store but makes it share a slot. Identical-arm `if (b) { ...; G(); } else G();`
  keeps both the store and its own slot. `0x00438c80`.
- **Do not add volatile where the original keeps a plain value**: an alloc-tag scope wants `int allocTag`
  (`0x004ce6b0`), and an `InterlockedIncrement` counter wants a plain `extern long` (`0x004c2d70`).

### 2.7 Barriers and scheduling

Extends tips "One instruction out of place: scheduling".

- *An inlined Havok TLS freelist push reuses a loaded count or links early* -> put `_ReadWriteBarrier();` before the
  push (declare `extern "C" void _ReadWriteBarrier();`). `0x00a4d000`.
- *A barrier does not give "fld, int store, fst"* -> barriers also pin x87 constant loads. Stores made by an inlined
  member method of a sub-object with two or more stores hold *later stores* (not loads) behind them. The pattern is a
  2-byte sub-object, `void Reset() { a = false; _ReadWriteBarrier(); b = false; }`. `0x00783ce0` (~140 checks).
- *A zero `xor` and the next member's `lea` in the wrong order in a ctor* -> inline ctor stores of a sub-object fence
  the scheduler; both stores need one two-store ctor of a non-polymorphic 8-byte sub-object. `0x0091ba60` (this was a
  pack type; section 5).
- *A store order pinned for no reason* -> look for a stray barrier or `goto` in the block. `0x007a20e0`.
- *Stores to an escaped local all before a vtable-cast slot load* -> the cast read is an ordinary load that may alias.
  Real `virtual` stand-ins let it move up. `0x006fe160`.
- *Endian swaps with all loads hoisted* -> swap each field through `inline void Swap(unsigned& v)`. `0x00500d20`.
- *A ctor of member stores whose order defies every flat ordering* -> write the real hierarchy with inline base ctors
  that repeat stores (`reset()` in each). The duplicates fold where the original has them. `0x0096a7f0`.
- *`cbSize` stored mid-zeroing* -> `T s = { 0 }; s.cbSize = sizeof(s);`. `0x006e5130`. *A zero cached in a register
  for every use* -> `MSG msg = {};`, not `{ 0 }`. `0x006197c0`.
- *A tie between two webs* -> duplicate a statement in both arms. An inline `AddHead` store in both arms brought back a
  lock web (`0x004e0890`), and `min()` computed in two arms with their own stores (`0x008d8370`).

### 2.8 x87 FPU-build Havok vectors

FO3's Havok 5.5 is the FPU build; FNV's is SSE. These work on `/O2` x87 code.

- *Operand order diffs per lane* -> store `hkVector4` as `float m_quad[4]` (or an `hkQuadReal` with `float v[4]`) and
  write every method on the lanes (43 to 25 lines, `0x0091fe80`; also `0x009776f0`).
- *But: frame 0x20 too big and dead `w`-lane ops kept* -> read lanes by name where the index is constant. A `(&x)[i]`
  accessor makes the vector address-taken, which stops packing and dead-lane removal. 193 to 11, `0x009c6780`.
  Conversely, the accessor fixed operand choices in `0x00972180`. Try both.
- *Single-lane `fld`/`fmul` order that ignores source order* -> write every op 4-lane (`w` too) and splat scalars into
  a vector (`setAll(s)`) before multiplying. The dead lanes renumber symbols and flip the rank sort. `0x00a50cd0`
  (from a 12021-score give-up to MATCH).
- *No `and esp,-16` frame* -> `__declspec(align(16)) hkVector4`. Do not use `__m128` members in x87 code (GS buffer).
  `0x008d4180`, `0x008d2120`.
- *Every field 0xc too far in a polymorphic shape* -> an `align(16)` member pads the vfptr to 16; keep `hkVector4`
  members in derived shape structs. `0x00975d50`.
- *A vector copied as `fld`/`fstp` pairs where you get integer `mov`s* -> member-wise copies or a member-wise inline
  `operator=`. A whole-struct copy gives `mov`s. For an integer copy of a float, use `memcpy(&f, &m, 4)`. `0x00931450`,
  `0x00972930`, `0x006b0ef0`.
- *Scale-in-place order* -> `v.setMul4(r, v)` instead of `v.mul4(r)`, and `t.setMul4(ext, v)` instead of copy-then-
  `mul4`. `0x00972930`, `0x00a6b1f0`.
- *A scale reloaded or copied wrongly* -> copy the scale into a local inside `mul4`/`addMul4` (`hkReal f = r;`), take
  `hkSimdReal` by `const&`, or make `hkSimdReal` a class wrapping `hkReal`. `0x009efd00`, `0x0091e390`, `0x00a6bb60`.
- *`dot3` evaluates y before x* -> name the x product as a `double` local, `double a = x * v.x; return a + ...;`.
  `0x00a2ee70`.
- *`setCross` loads the wrong operand first* -> pass that member through a named `const hkVector4& p = m_member;`
  (`0x00a6b1f0`). If named `nx/ny/nz` locals outrank the other vector's temps, store the lanes directly
  (`0x00a2ee70`).
- *`normalize3` loads in the wrong order or merges two copies* -> put the zero-tested `1/sqrt` in a free inline helper
  (`hkSqrtInverseSafe`), and write `l2 ? hkSqrtInverse(l2) : 0`. `0x008dfb90`, `0x0091fe80`. *Its scratch scalar in
  one shared slot* -> split the length and the inverse into two locals. `0x00a75860`.
- *Float homes rotated across three slots* -> move the chained computation into an inline helper returning `float`.
  `0x009776f0`.
- *`setMax4` spills through a temp* -> `if (a.x > b.x) x = a.x; else x = b.x;`; `setMin4` is the plain ternary.
  `0x00705930`.
- *`equals3` against zero with the wrong compare* -> a local eps vector filled with the literal, a forceinline
  `AllNear3` and a float-returning `AbsF`. `0x008d2480`. A 4-lane approx-equal mask wants one named `int` per lane.
  `0x00767f10`.
- *A missing or extra `fxch` after a dup of one constant* -> swap the two locals' declarations (515 to 25, `0x00a87330`).
- *Timer slots* (cf. tips "SSE code"): a `volatile` ticks local keeps its own slot, and the two-line rdtsc block shares
  slots. Havok world-callback loops want the matched neighbour's plain `TlsGetValue` plus rdtsc form, not FNV's
  forceinline timer. `0x009c1070`, `0x00989280`.

### 2.9 Loops

- *A loop tested at the top on every pass where you get a rotated loop* -> VS2005 rotates only simple conditions. Use a
  compound guard that folds away (`bool done = false; ... !done && i < n`), on *both* loops when they are nested.
  `0x00438c80`, `0x0043a040`, `0x00497160`.
- *A loop bound spilled as a qword, frame too big* -> VS2005 hoists the bound of a `for` that contains calls; the
  original used guarded do-whiles (`if (y < n) do { ... } while (++y < n);`). Probe it first with an opaque
  `Probe(&n)`. `0x004932e0`.
- *The loop-count store and the index zero in the wrong order* -> write the plain `for` loop and let VS2005 build the
  countdown; a hand countdown puts the store first. `0x007a20e0`.
- *Loop invariants reloaded inside the loop* -> declare the index first, `count = index`, and walk an explicit cursor in
  `if (n) do { ... } while (i);`. `0x0048fff0`.
- *An inner loop compares against the count's slot while the outer loop keeps it in a register* -> write the inner
  bound as the array's size field, not the cached count. 92 to 2, `0x00a8a830`.
- *A warning-and-skip branch laid out at the end* -> an explicit `continue;` after the warning. `0x006d0200`.
- *An inlined find drops its test on the found pointer* -> `T* result = 0; ... { result = p; break; }` (`0x007a5620`).
  The converse, `return n->item->tile;` inside the loop, was right in `0x00664ea0`. Try both.
- *A set and a loop index swapped* -> a BSSimpleArray-shaped template with inline `GetSize`/`GetAt` returning `T&`.
  `0x005e5e60`. *A list walk's entry null test lost* -> use the member directly, not a pointer local (same function).

### 2.10 Destructors and EH

Extends tips "Constructors, destructors, exceptions".

- *An EH frame you do not get* -> a ctor of plain stores is inferred nothrow. Give it a call that folds away:
  `T(unsigned n = 0) { if (n) Reserve(n); }`. `0x007114f0`; Gamebryo `NiTPrimitiveSet(n = 0)`, `0x00aafcc0`.
- *An EH frame you do not want* -> `throw()` on callees (`0x00975d50`), and placement `new` with the class's own
  `operator new(size_t, void*) throw()` and no placement delete (`0x009e3e00`). If the pack's inline global
  `operator delete` is not nothrow, redeclare it with `throw()` (`0x00be5db0`). A Havok local with a dtor (hkPointerMap,
  hkInplaceArray) should be declared without a C++ dtor, with the release called by hand (`0x00a4d550`, `0x0098fce0`).
- *A missing `-1` store between an inlined `new` and the next state* -> the call in between is nothrow; declare it
  `throw()`. `0x004e0890`. An RAII counter adds an EH frame; use inline set/clear calls (`0x004c2d70`).
- *Member-by-member dtor calls through the CRT's `eh vector destructor iterator`* -> declare member *arrays* whose
  elements have a real dtor (`NiPointer<T> idles[2]`). The compiler emits the calls and state numbers. `0x00743580`
  (16 states, first check).
- *A destructor with an unknown layout* -> count its EH states (one step per member dtor). A member that FNV gives a dtor
  but that has no state in FO3 is a plain struct there. `0x006ace30`.
- *A lone high state on one inlined `new`* -> write the inlined callee's *whole* body as an inline, with its own
  inline/call choices per site. `0x005a9540`.
- *An unwind funclet that only stores a vtable* -> a polymorphic class with an inline `virtual ~T() {}`. An empty
  non-virtual dtor drops the frame. `0x007de400`, `0x006096b0`.
- *A zeroing dtor whose free call lands mid-stores* -> the zeroing is split between the class dtor and a member's dtor.
  Use the real layout. `0x00bd7330`.
- *A local array whose dtor calls through vtable+8* -> a real virtual class whose `Clear()` calls `Free(data)`
  (`0x005f0070`). If the vtable has no symbol, use an explicit table struct `extern ArrayTable<X> DAT_<vtbl>;`
  (`0x007aec10`).
- *A `NiPointer` dtor called at one early return where the original inlines it everywhere* -> a namespace copy of
  NiPointer with only the dtor `__forceinline`. `0x00bcc7a0`.
- *A by-value object-returning call that never inlines* (`str = str.substr(0, n)`) -> write it as
  `*this = hkString(buf, n)` with an inline ctor. `0x0093df80`.
- *NiPointer assigns with old and new pointers in swapped registers* -> use the pack's `NiPointer<T>` template
  (`operator=(T*)`) over a refobject with inline `IncRefCount`/`DecRefCount` (`0x0049d910`). The old pointer outranks
  the new one only when the same `DecRefCount` is inlined elsewhere, so give every refcounted class one shared
  `NiRefObject` base (`0x0069a4b0`, solved after 3 give-up rounds).
- *Members FNV types as `NiPointer<T>`* -> use `::NiPointer<T>` even when they are only read. 276 to 117, `0x005b6500`.
  A global smart-pointer copy whose value stays in a register is `operator=(T*)` fed the raw source (`0x00612f70`).
- *An inlined `!= 0` pointer test that materialises a bool (`setne`)* -> the source compared against a refcounting
  temporary, `data[i] != NiPointer<T>(0)`. `0x00bed540`.

### 2.11 Allocation

- *`new T[n]` as out-of-line CRT calls* -> add a global `operator new[]` that forwards to the memory manager. It may
  clash in the project file. `0x004d04b0`. A `seto`-guarded size before an allocator call is `new T[n]` with a class
  `operator new[]`. `0x009ec920`.
- *EH states around inlined `new NiXProperty`* -> real classes with class `operator new`/`delete`, an out-of-line base
  ctor and virtual dtors. `0x00612f70`, `0x0074e520`.
- *Havok `new hkX` that will not take your class* -> derive a stand-in with a static `operator new` calling
  `allocateChunk` and an undefined ctor (it binds by position). Redefining the pack's class was silently ignored.
  `0x00904470`.
- *Havok thread-memory stack alloc with a stack temp and a reload* -> make it single-exit (`char* p = cur; if (p + n
  <= end) cur = p + n; else p = allocSlow(n); return p;`; -94 lines). The rounding is `(n + 16) & ~15`, with a `ret`
  local assigned in both arms. `0x00705930`, `0x009efd00`.
- *Havok `hkArray` release* -> `if ((m_capacityAndFlags & 0x80000000) == 0) dealloc(..., getCapacity() * sizeof(T),
  0x17);` with an inline `getCapacity()`. A temp's release and a local's dtor can need different forms in one function.
  `0x0091fdb0`, `0x009a1000`. A `pushBack` grow copy with two cursors wants `noalias` on the swap (`0x009a1000`).
- *An inlined 12-byte Havok `delete`* -> `deallocateChunkConstSize` in Havok's `FreeList::put` order. 207 to 2,
  `0x00a63f10`.
- *An inlined array append storing `capacity` twice on one path* -> inline the pack's real grow helper, not a simplified
  one. `0x007a5620`.
- *A pool-allocator free with a spin-lock unlock* -> an inline member of a lock struct, with `volatile long owner`
  and `long o = owner;` before the compare-exchange. The same struct fixed slots 0x300 bytes earlier. `0x00af4210`,
  `0x0043a040`, `0x00bee1c0`.
- *`and esp,-64` in the prologue* -> needs no `align`; VS2005 picks it for big char buffers. `0x005357e0`.

### 2.12 Calling conventions and arity

Extends tips "Inputs in registers (private calling conventions)".

- *A static callee's private convention has the wrong registers* -> the convention follows the *callee's* own
  colouring, so change the callee body, not the call site. `0x009ec920`.
- *One argument of a private convention should stay on the stack* -> take its address once (`int* p = &type;`)
  (`0x0093e650`), or read it through a volatile view in the stub (`0x0095e590`).
- *Same-file callees in two flavours* -> `static` with a body gets a register convention, while non-static with a body
  keeps cdecl but still shows no escape. `0x00938610`.
- *A callee takes its hidden return in a register* -> a `static` same-file function (a formatter). Put a static body
  under your own name. `0x00bc08b0`, `0x00bbca30`.
- *A free function whose FNV twin is a member that never uses `this`* -> write it as a free `__stdcall`. The hidden
  `this` shifts the numbering behind x87 `fadd` order. `0x006096b0`.
- *`ecx` loaded with a global right before each call* -> a thiscall member of that global, not `__stdcall` (three
  give-ups, `0x00523970`). A function that forwards `ecx` untouched is a thiscall member (`0x004aaba0`, `0x004eb8f0`).
- *A callee fed only `ecx`/`edx`, ending in a plain `ret`* -> `__fastcall(a, b)`. `0x009ded20`.
- *`lea ecx,[subobject]` right before a branch* -> receiver setup for a member call in one arm. `0x006ce8a0`.
- *Pushes in the wrong place around nested calls* -> check every callee's `ret N`. Seven pushes split 4 + 3
  (`0x0075fe70`), a push that belongs to the outer call (`0x0076f560`), a two-float call (`ret 8`, `0x0068a7e0`), and a
  mid-function `push edi` faking a fourth parameter (`0x004ee3e0`).
- *Two equal switch cases merged into one* -> give one case its own overload of the link-folded helper. Overloads bind
  by name. `0x0093e650`.
- *Vtable-cast calls vs real virtuals* -> real `virtual` stand-ins (script-generated padding slots) fixed
  `0x00704050`, `0x00652000`, `0x006fe160` and `0x00534b20`. The direct cast call fixed `0x007010f0`. Try both. Call
  through the original field expression, not an alias, to keep the receiver formation (`0x005b78d0`).
- *Hand-cast `this` adjusts with a scratch swap* -> declare the real multiple-inheritance class and `static_cast`
  (`0x007181b0`). An `add` kept before field loads with no null test is a this-adjust through an MI node
  (`0x007de400`). A second-base list adds its own null test (`0x00664ea0`).
- *Import pointers not hoisted into callee-saved registers* -> call through `__declspec(dllimport)`, not extern
  function-pointer globals. `0x006197c0`, `0x00902620`. Write `::InterlockedDecrement` (unqualified is C2668 in these
  packs). `0x00460090`.

### 2.13 Constants and CRT idioms

Extends tips "Constants" and "Library and system calls".

- *A float constant with a `DAT_`/`FUN_` name* -> try the plain literal first. `extern const float` turns `fcomp` into
  `fld`+`fcompp`. `0x007da3d0`. To see it bound while the code is shifted, define it by address with its value.
  `0x00737460`.
- *A double constant still unbound in an aligned diff* -> `extern const double DAT_<addr>;` (`0x0063f060`). But a
  qword constant scheduled above a store wants the plain literal (`0x004932e0`), and a `-1.0f` test is a literal
  (`0x0044b980`).
- *A magic divide by a negative constant* -> `-(x / 120)` folded by the compiler; write FNV's form. `0x00634f90`.
- *Folded arithmetic you need unfolded* (`0.5 + r * -1.0`, `-1.0 * c + y * x`) -> build it in an inline helper with a
  named intermediate (`double d = (b - a) * r; return a + d;`). `0x00499b30`, `0x004932e0`.
- *A zero or small constant cached in a callee-saved register* -> caching follows the use count (about 6 or more);
  probe by changing one use at a time to another constant. `0x004d9bd0`, `0x006931c0` (open).
- *A function's address used as a value* -> declare it by its symbols-file name: a `""` fallback that keeps its null
  test is `(const char*)FUN_<addr>` (`0x0050caf0`); FNV's `if (!(Func > 0))` tests a `FUN_` address (`0x0076b4e0`).
- *A constant select argument compiled as a branch* -> two calls in an `if`/`else` (`0x00622520`).
- **CRT shapes:** `cdq`/`xor`/`sub` is `abs()` from `<stdlib.h>` (`0x004399f0`); `0xc046e0` is the float `tan`
  (`0x007b8200`); `(float)fabs(g)` rounding twice means route it through a `double` helper (`0x006598d0`); VC8
  `<math.h>` float `pow(float,int)`, `sqrt` and `atan2` are FNV's `ForwardFloatAndInt`, `FUN_004579e0` and
  `FUN_004b5550` (`0x00660030`); inline `fnstcw`/`fistp qword` is plain `(unsigned int)f` (`0x0063f060`); a `_memmove`
  call is `memmove` (`0x004d04b0`).
- **Name things by FO3 address.** Data externs bind by position, so name them `DAT_<addr>`. A `FUN_` member named
  after the FNV address shows up as a diff line or binds to the wrong function. `0x008d8370`, `0x006ac670`.

### 2.14 String literals, extern arrays and reworks

- *An inline `strcpy` as a byte loop where a literal gives dword moves* -> the source is an `extern const char
  DAT_<addr>[];` of unknown length. `0x00533a20`.
- *Rework "matches in the pack but not in the project file"* -> the candidate is placed where the pack *declares* the
  target. Use only names declared above that point, use string literals rather than extern arrays (`0x00852f40`), read
  wrongly shaped pack classes through private view structs (`0x0095e4d0`, `0x00a87830`), and give helpers and emitting
  callers unique names. Never redefine members of shared classes (`0x00834fc0`). Rebind unmapped symbols to their map
  names (`0x008899e0`).
- *Rework "compiles 115 vs 98 in the project file" for a register-convention helper* -> write `static` on your own
  definition too (MSVC keeps it after an extern prototype), plus a uniquely named caller. `0x00a8c2f0`.
- *Pack globals clash on type, or names are ambiguous (C2872)* -> wrap your externs in a namespace, keep
  `dynamic_cast` targets at global scope (a namespace changes the `.?AV` name), and qualify casts as `::Actor`.
  `0x00704050`, `0x004d2fb0`, `0x00762750`.

## 3. Porting from a New Vegas twin [needs FNV]

- **Port literally first, refine second.** A high-confidence twin beat an earlier contributor's restructured near miss
  every time it was tried. `0x00517950` (first compile, over a 13699-score give-up), `0x0053eae0`, `0x0045afe0`,
  `0x0075c0e0` (over a 194-line give-up), `0x00bbca30`, `0x00676150`, `0x007ce6e0`.
- **Keep FNV's redundancy.** Keep its redundant null tests, duplicated switch arms and extra `if (size)` guards. `/O2`
  merges identical tails by itself. `0x00517950`, `0x00564030`.
- **Keep FNV's inline calls, even trivial ones** (`SetFlag(1)`, `CanFire()`, a call chain inside a flag getter, nested
  inline members). `0x007d7bf0`, `0x004eb8f0`, `0x007181b0`.
- **FNV out-of-line helpers usually inline in FO3.** Getters, setting reads (`*setting.Get()` and `.Float()->f` become a
  plain `extern float`), `IsEmpty`/`GetAt`, script-command getters, and vector add/sub/length all inline to field loads
  or operators. `0x00646cc0`, `0x007e2a70`, `0x005357e0`, `0x007b8200`, `0x00773290`.
- **Known FO3 shapes of FNV calls:** `SetWarningState` is an `InterlockedIncrement` plus a clamp (`0x004c2d70`);
  `Tile_Set_Helper::Set(trait, int)` is a forceinline `SetInt` that calls the float setter (`0x00629620`); `Mem960(...)`
  is the alloc-tag scope (`0x004ce6b0`); `SetTranslate`/`SetRotate` are member assignments (`0x005e4890`);
  `FUN_004623f0(false/old)` is an inlined TLS bit plus a real call (`0x0044b980`); `MinInt(Max(x,0),4)` is two inline
  helpers (`0x0065be50`); `FUN_00401460(&f,&m,4)` is `memcpy` (`0x006b0ef0`).
- **Where FO3 calls a helper at some sites and inlines it at others**, either declare the out-of-line one without a
  body and write an inline copy for the inlined site (`0x00767f10`, `0x004e9c50`, `0x005a85f0`), or give one in-class
  body under its `FUN_` name and let `/O2` choose (`0x004c0260`, `0x00660030`). Try both.
- **Rebuild FNV's helper layers for slot packing.** In `0x006df2a0` the layers were Gamebryo `NiBinaryStream::Write`
  under FNV's `SaveData`, with FNV's own locals. They matched on the first check after ten permuter passes had failed.
- **FO3 offsets differ.** Members are often 8 bytes lower (`~MagicBoltProjectile`, `0x006ace30`), and
  `TESObjectREFR::baseForm` is at +0x1c (`0x0074e520`). Havok FPU layouts differ too (inverse masses at
  +0x60/+0xd0, `0x00a7d5c0`). Take offsets from the target, not from FNV headers.
- **Take struct sizes from slot gaps, not from FNV `static_assert`s.** FNV's pathfind builder is 0xb4 and its search
  state 0x2108, but they are 0xb8 and 0x2104 in FO3. `0x005f4990`.
- **Renumber enums and states from the jump tables.** ExtractArgs lacks cases 62-69 (`0x00517950`); HUD modes are FNV
  minus one from 20 up, and the visibility masks are one bit narrower (`0x0064de10`); package types match FNV up to
  at least 24 (`0x00743b00`); check case groups (`0x005a85f0`).
- **Drop what FO3 lacks.** FNV-only tests (`0x0074e520`), the `hkStringPtr` prefix test (`0x0093df80`), a `count = 0`
  in a release (`0x0091fdb0`), and the dead `int aiD[N]` arrays in `/Ob1` variant twins (`0x00bc58c0`).
- **Translate SSE to x87.** Write FNV's `__m128` copies as four float member copies (`0x009ded20`) and SSE side tests as
  a dots local returned by value (`0x00a2ee70`); see section 2.8. FNV's `static __declspec(noinline)` signatures can
  reproduce FO3's private conventions as they are (`0x00a50cd0`).
- **FO3 Havok 5.5 is not FNV's Havok.** The `CollectStats` collector vtable order differs and there are no
  `m_clearDontDeallocate` tests (`0x0090b350`, `0x00a26e70`). FNV's `GetSingleton()->m_10` allocator is FO3 thread
  memory (`0x00a63f10`). FNV's router `new` is FO3 `allocateChunk` (`0x00904470`).
- **Call sites can merge or split.** FO3 had one call where FNV has two that the compiler tail-merges, which explains a
  `/GS` shadow copy (`0x0042ea50`). FNV's two-arm form tail-merges into FO3's single call (`0x0076a670`).
- **Subsystems that port almost literally:** StartMenu from `startmenu.cpp` (`0x00682fd0`), script commands from
  `tesscriptfunctions.cpp` (`0x005357e0`), `LowProcess` from `lowprocess_rtm_variant.cpp` (`0x0074e520`), SpeedTree
  readers from the matched pack siblings (`0x00bc58c0`). FOSE's `DataHandler` layout helped with `0x00446220`.
- **Where twins hide.** Look in `src/staging` blocks (`0x006096b0`, `0x0046b830`; navmesh obstacle cutting is
  `blk_006a0000_od.cpp`, `0x005e2110`), the `*_variant.cpp` files (`tile_ob1_variant.cpp` for `0x00bed540`),
  `blk_*_od.cpp` (`0x00773290`), the function next to candidate 1 (`0x005ee080`), candidates 2-3 read for *call order*
  (`0x0069b430`, `0x0060c850`, `0x00713470`, `0x00626e70`, `0x0091fdb0`), the packet's `starting_draft` even at
  similarity 0.32 (`0x005a85f0`, `0x009a1000`), the same body under another name (`0x006c8e30`), and class destructors
  `~FUN_<fnv>`, which twins.py misses (`0x004f6570`).
- **Twin confidence is only a hint.** A `high` twin backed only by float evidence was wrong (`0x004dd7d0`); `medium`
  twins were unrelated in `0x005f0070`, `0x008d2480` and `0x007bcff0`. `low` twins were right in `0x00497160`,
  `0x007de400`, `0x007b8200`, `0x00743b00` and `0x007c9d80`.

## 4. Finding the model when no twin is obvious

Most of these need fnv_decomp to grep **[needs FNV]**. The neighbour and library tips do not.

- **Strings**: grep FNV for format strings and debug names (`CellRefLockEnter`, `0x004d63a0`; `0x007d9f60`), or for a
  string used by a *pack neighbour* (`"SpecialAnims"` led to `animation.cpp`, `0x00464330`). **[needs FNV]**
- **Float tuples**: `rg "1.0f, 0.0f, 1.0f, 0.5"` found `CreateObstacleBox` (`0x005e4890`); `512.0` (`0x005f0070`); a
  `0.01f` PathingLocation offset (`0x006096b0`). **[needs FNV]**
- **Flag masks and ids**: `0xfae` (`0x00bed540`), a flag-select constant (`0x004932e0`), menu id `0x3f1`
  (`0x00776670`), an anim-slot index sequence (`0x006ff2a0`), several form-type constants together with `rg -l`
  (`0x004c0260`). **[needs FNV]**
- **MEM_CONTEXT and TLS tags**: MEM_CONTEXT 45 plus `0xffff` triangle locals (`0x005f4990`), TLS tag 0x33
  (`0x00464330`). **[needs FNV]**
- **`new` sizes and AV numbers**: `new X(<small int>, this, ...)` with the allocation size, plus
  `GetActorValue(0x2a) >= 100` (`0x007111a0`). **[needs FNV]**
- **Parameter-type tuples**: name the arguments from their callees, then grep the signature
  (`(TESObjectREFR*, TESObjectCELL*...`, `0x004ee3e0`). **[needs FNV]**
- **RTTI of the vtables the target stores**: read the COL and type descriptor behind the vtable of a local
  (`LockFreeMap<...>` iterator, `0x00608760`) or of a destructor's stores (`0x006ace30`, `0x00743580`).
- **Callee argument counts**: name cdecl callees by their `add esp` arity, then grep their FNV names (`0x00773290`).
  Callee shapes work too (`getBoneModelSpace`, `0x008dfb90`). **[needs FNV]**
- **Users of the same globals**: grep for the getters of the globals the target reads (`g_thePlayer->GetParentCell`,
  `0x007e2a70`), or for distinctive logic (the explode/head case, `0x0071c3f0`). **[needs FNV]**
- **Neighbours of the same file**: a staging neighbour that names the offsets points at the FNV subsystem
  (`0x007e2a70`). Read beside a neighbour's twin (`0x005e2110`). Grep `work/` for a matched sibling that uses the same
  globals (`0x008d2480`, sibling `0x008d8370` of `0x008d4180`).
- **Matched pack neighbours inlined with constants folded**: if the target's blocks look like neighbours, copy their
  bodies under your own names with `__forceinline` (plain `inline` cost 200 diff lines). `0x00616e70`. Havok compat
  `Update_*` patches follow the pack's accessor neighbours, not generic twins (`0x009345e0`, `0x00935ab0`).
- **Recognise library bodies**: VC8 `basic_filebuf<char>::uflow` (`0x00be5db0`); `std::vector::_Insert_n` pasted as
  `FUN_<addr>` of a class deriving the vector (`0x00be2450`, `0x00bc60c0`); Gamebryo `LoadBinary` readers
  (`0x00aafcc0`); newran `PosGen` (`0x00bc7380`); a real `std::vector` with a custom allocator (`0x00ba8c40`).
- **No model at all**: write from the target. Several matched this way (`0x006fd3d0`, `0x005fc160`, `0x007a2ea0`,
  `0x007081b0` with only an FNV header).
- **Check notes before acting on them**: a `known_flags` note described a different address and an `fsincos` that
  the target lacks (`0x007111a0`).

## 5. Pack and flag problems, and how to prove them

- **`/Od`-listed `/O2` code.** Tells: an aligned `esp` frame, `this` in `esi`, no parameter homes, registers read at
  entry (cf. tips "Frame" and "Inputs in registers"). 33 proofs tonight, many of them x87 Havok (`0x0098fce0`,
  `0x00a50cd0`, `0x009a1000`) and many plain game code (`0x005357e0`, `0x00540270`, `0x00787580`).
- **The proof procedure.** Check with `--flags /MT,/O2,/GS,/EHsc,/Gy`, comma-separated: a space-separated list silently
  checks the pack's own flags. On MATCH, save a `checkpoint` (with work notes: `phase: "attempt"` plus `change`,
  `observed`, `why`, `expect`), then `flag` with `compile_flags` and `checkpoint_id`. That releases the claim, and the
  build host credits it. `0x005fd1e0`.
- **A `known_flags` entry that already carries an exact `/O2` checkpoint**: fetch its source, re-check it once, save
  your own checkpoint and flag with it (~10 minutes). Never flag with another contributor's proof: give the claim back
  so they keep the credit.
- **Missing `fnv_asm_helpers.h`** (a bare `fsincos`, or `fld`/`fistp` with no `_ftol2`, and the helper is undefined,
  C3861): copy the pack to `work/<claim>/packtest/`, add the header and its `#include` after the pack header, match
  there, checkpoint, and flag `pack_problem` with the `checkpoint_id`. 9 tonight: `0x006d1490`, `0x006fb6c0`,
  `0x004ee3e0`, `0x004399f0`, `0x0043a040`, `0x004cb4f0`, `0x006d36e0`, `0x00554dc0`, `0x004dd7d0`.
- **Wrong pack symbol** (`canary: false`, or a mangled name whose return type or convention contradicts the target, so
  every candidate is NO_SYMBOL): set `"symbol"` and `"canary": true` in a pack copy, or prove it without `--pack`
  (`--pack` silently overrides `--symbol`; pass `--addr`, `--size`, `--source`, `--symbol` and the pack flags with
  `F3CHECK_TREE` set). The checkpoint needs `request_id`. `0x007fa880`, `0x00652db0` (9 earlier give-ups), `0x006103a0`,
  `0x0098de10`.
- **Wrong stand-in base type**: if a pack type contradicts the code (an 8-byte sub-object whose two-store ctor fences
  the scheduler), change it in a pack copy, match there, and flag. The candidate cannot change a pack type.
  `0x0091ba60`. A pack *class* you can redefine (cf. tips "Library and system calls"), but for Havok `new` the
  redefinition was silently ignored, so derive from it instead (`0x00904470`).
- **Other flag mismatches**: `/GS-` vs listed `/GS` (`0x00a80ba0`). `/fp:fast` listed when the target is precise
  (`fstp`/`fld` of a float sum is the precise-model spill, `0x0095e590`).
- **`index_problem`**: catch funclets cut off at the `ret` (`0x00ba8c40`, `0x00be2450`, `0x00bc60c0`, `0x00ba7860`),
  two functions in one span (`0x00962850`, `0x00a3d0e0`), and a jump table decoded as code ("jump outside the extent",
  `0x007e3f20`). Prove the full size with a local wrapper that sets the span cache to the full size (never edit the
  kit), then flag it with the checkpoint.
- **`checker_problem`**: a `$LN` label in the symbols (`0x0087df80`).
- **Pack-problem flags often do not reproduce, so always compile once first.** "Unit does not compile" (`0x00931450`,
  `0x0093df80`), C2761 (`0x007c9d80`), "private conventions make it impossible" (`0x00938610`), two give-ups that
  blamed the pack (`0x00aafcc0`), and import targets that were display only (`0x00af4210`) all matched as normal
  candidates. Many open flags predate pack rebuilds.

## 6. Tooling and operations

- **git-bash mangles `/MT`** into `C:/Program Files/Git/MT`, so every `--flags` check silently loses its first flag.
  Prefix the call with `MSYS2_ARG_CONV_EXCL=/MT`. `MSYS_NO_PATHCONV=1` breaks the launcher's script path. For a raw
  `/FAs` compile, use `MSYS2_ARG_CONV_EXCL="*"`.
- On Windows, plain `bash` from Python can be WSL: call git-bash by its full path. If `f3check` is a shell function,
  `timeout f3check` fails; background the plain command instead.
- Results are cached, so edit the candidate once per check. Scripts that import `fc_common`/`fc_check` must set
  `F3CHECK_TREE` and `F3CHECK_TOOLS` first and use `C:/`-style paths. `fc_check.aligned_diff` returns both listings
  when you want to diff your own build.
- Bash heredocs can collapse `\\` in C string literals (LITERAL_MISMATCH): write literals with an editor tool.
- **Batch variants.** Write 4-6 files per batch (about 1.5 s per check natively). `f3check --sweep "<what varies>"`
  takes one note for the whole loop. Use itertools for cross products: 150 files took about 5 minutes. Rank variants by
  the count of `ORIG`/`YOURS` lines in `--full-diff`; region counts are too coarse.
- **Standalone `cl /FAs` tests** (5 lines, about 1 s) answer escape, slot and convention questions faster than the full
  unit, and the listing shows every local's frame offset and sharing.
- **Diagnostic probes.** Delete one region or statement, replace one value with a constant, break an expression on
  purpose (`flags * 3 & 8`), force one call out of line, or add an opaque `Probe(&x)`. Then watch what moves far away.
- **Rate cap.** Each account gets 6000 requests per hour. Checks with notes count, so a busy pool hits the cap (it
  delayed a submit at 21:00). Use `--sweep` for loops instead of noted single checks.
- **Work notes (Power tier).** `f3check` refuses checks without notes. A `checkpoint` that carries `source` needs
  `phase: "attempt"` and `change`/`observed`/`why`/`expect`, plus `region_summary` at 1 KB and up. Unsent checks stay
  in the spool: `f3check --spool <claim>` prints them, `--spool-sent <claim> N` marks them sent and `--flush` retries.
  Check that the count reaches zero before you submit or give up.
- **REGION labels.** A plan checkpoint is refused with "REGION lines cover 0%" unless every line is labelled
  (`REGION R1 0x000-0x039 ...`). A MATCH prints no region block, so write `regions of 0x100 bytes: 5 of 5 exact` plus
  one `R<n> 0x....-0x.... exact` line per region.
- **Claim collisions.** A band claim that finds nothing open joins a held function (co-work), and two workers can land
  in one claim folder. Use claim-id folders, and check `function_info` before you start. One worker lost its time on a
  collided claim.
- **Never re-claim your own give-up.** Hand it on with `best_code` and a precise `still_differs`. Fresh eyes on earlier
  give-ups produced about 70 matches tonight.
- **The permuter rarely closes register ties.** In about a dozen cases, 200-1200 trials found nothing that hand
  variants and sweeps then fixed. It did fix one slot (`0x005fc160`) and one rename (`0x006d1490`). Run it, but do not
  wait on it.
- **Stand-in generators.** A 20-line script that expands `vlist(0, 0x790, {...})` and `fields(...)` markers into
  `virtual void vNNN();` and `int unkNNN;` keeps big vtables and field gaps readable without filler arrays.
  `0x00762750`. Separate `extern __declspec(thread)` variables bind by position for TLS fields (`0x006fe160`).
- The queue skipped 0x9A0000-0x9FFFFF (x87 Havok collision agents) after 4 of 5 attempts gave up. Pick those only with
  a fresh idea for section 7.

## 7. Known unsolved patterns (worth a fresh idea)

- **x87 single-lane operand order in large Havok functions** (`fld [m]; fmul st(i)` vs `fld st(0); fmul [m]`, or load
  vs memory `fadd`, on a few lanes of repeated inlined blocks, deaf to source order). `0x00949df0` (the count of unused
  declarations rotates some lanes with a period of about 7), `0x00a7d5c0`, `0x009c1ae0`, `0x00924ca0`, `0x009efd00`,
  `0x00a6bb60`, `0x00a75860`, `0x00a87330`, `0x004ccbb0`.
- **New-expression cleanup-temp slot placement**: the EH temp of `p = new T(...)` takes its own slot where the original
  shares it with an address-taken local. Solved with disjoint scopes in `0x004a2e30` and `0x006c8e30`; still open in
  `0x0049e490` (one slot over) and `0x006cc4e0`.
- **3-way callee-saved rotations** (`ebx`/`ebp`/`edi` over a TLS base, a saved tag and a param, tipped by the third
  inlined `NiPointer = 0` release): `0x0059ed00` (156 lines after about 50 variants and 400 permuter trials), and a
  global `ebx`/`esi` role rotation in `0x00567610`.
- **`xor esi,esi` then `cmp eax,esi` after an inlined `new`**: only an out-of-line factory compares with its zero
  register. `0x0042ea50` (one instruction, two claims).
- **Stack parameters loaded into `ebx`/`ebp` at entry** where you load them lazily: `0x00902620` (matches from +0x6d on).
- **Two `bool`s across calls competing for `bl`**: the loser lives in a stack byte; about 35 shapes compiled
  identically. `0x006f3cc0`.
- **A pushed field key in `ecx` where the original has `eax`**: the cause sits in the first 0xc0 bytes. `0x008e7d40`
  (11 give-ups).
- **Spill reloads swapped at an outer back edge**: they moved only when an inner-loop float became address-taken.
  `0x0058e230`.
- **A small constant cached in `ebx`** that every source form of `x <= 2` keeps: `0x006931c0` (4 bytes off).
- **A named filename local at the frame bottom under `/GS`**: every form either moves to the top or becomes a temp.
  `0x00bba060`.
- **Two variable-indexed vectors sharing one 16-byte slot**: they pack only if both addresses escape to a real call.
  `0x00a3cc40`.
- **An address-taken out-param reused from `esi`/`ebx` across later calls**: every copy-local form reloads it.
  `0x00bcc7a0`.
