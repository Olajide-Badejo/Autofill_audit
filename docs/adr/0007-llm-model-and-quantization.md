# 0007: the local model, its quantization, the serving route, and the VRAM policy

Date: 2026-08-26. Phase P6. Status: accepted.

## Context

<!-- traceability: a specification section number, not a measurement -->
Spec section 0.3 pins the research layer's local model to "a ~12B-class
instruction-tuned model at 4-bit quantization", served through Ollama's
OpenAI-compatible `/v1/chat/completions` endpoint with structured output
enforced. Spec section 3.4 requires this ADR to record the resolved choice, the
observed VRAM headroom, and which fallback was taken if any.

The machine is the one spec section 3.1 pins: an RTX 5070 with 12 GB of VRAM,
shared with a desktop compositor, a browser, and Playwright's Chromium. A 12B
model at 4-bit is close to the ceiling on that card once the rest is resident,
which is why the fallback ladder was decided in advance rather than under
pressure.

Two facts about the environment shaped the route and neither is a preference:

1. **Ollama was already installed on the Windows host**, with
   `mistral-nemo:12b-instruct-2407-q4_K_M` pulled, along with three other tags.
   The repository and the whole toolchain live in WSL2.
2. **The Windows Ollama binds `127.0.0.1` only.** From inside WSL2 neither the
   default gateway nor `localhost` reaches it; both are refused. So the already
   downloaded 7.5 GB blob was visible on disk and unreachable over the network.

## Decision

**Model: `mistral-nemo:12b-instruct-2407-q4_K_M`.** A 12B-class instruction model
<!-- traceability: a specification section number, not a measurement -->
at 4-bit quantization, which is what spec section 0.3 requires. It being already
resident on the machine was the tiebreaker against the other 12B-class tag
available, `mistral-nemo:12b-instruct-2407-q5_K_M`, which is 8.7 GB and would
have left roughly a gigabyte less headroom for no reason the specification asks
for.

**Serving route: Ollama installed inside WSL2, serving the Windows model store
over the mount.** This is resolution step 1 of the task's ladder and it worked,
so no fallback was taken.

```
OLLAMA_MODELS=/mnt/c/Users/jidro/.ollama/models
OLLAMA_HOST=127.0.0.1:11434
OLLAMA_CONTEXT_LENGTH=8192
OLLAMA_KEEP_ALIVE=10m
```

The store is read across the `/mnt/c` DrvFs mount. Blob reuse works: all four
tags list, and the chosen one loads and generates. Nothing was re-pulled, so the
route cost an install and no download.

**Quantization: Q4_K_M, unchanged.** No step of the spec section 3.4 fallback
ladder was needed. In particular the third item, "silently letting the model spill
to CPU and reporting the resulting latency as GPU latency", did not arise and
would have been labelled `cpu-offload` if it had.

## Observed VRAM headroom

Measured with the model loaded and generating, at the context length the
benchmark runs at. `ollama ps` reports the processor split and `nvidia-smi`
reports the card.

These are readings off the card taken by hand, not quantities any result file
carries, so each row is annotated rather than cited: there is no run log for
`nvidia-smi` and inventing one would be worse than saying where the numbers came
from.

```
context   resident   processor   VRAM used   VRAM free   card total
4096       7.9 GB     100% GPU    8252 MiB    3692 MiB    12227 MiB
8192       8.6 GB     100% GPU    8873 MiB    3071 MiB    12227 MiB
```

<!-- traceability: the same hardware reading as the table above, restated -->
**The headroom the benchmark ran with is 3071 MiB, at 100% GPU with no CPU
offload.** The idle baseline on this machine is roughly 500 MiB of compositor and
browser, so the figure is a real margin rather than an accounting artefact.

**8192 was chosen over the 4096 default deliberately.** Spec section 3.4 observes
that "prompt inputs here are small by construction (Section 12.2 sends pruned
descriptors, never HTML), so a small context window costs nothing", and that is
true of the input but not of the whole request: the corpus's widest pages carry
around eighteen controls, which is roughly 2000 prompt tokens after pruning, and
the response carries one object per field. 4096 would have been enough for the
median page and would have truncated the widest, and a truncation would have
failed the page rather than the field. The extra 621 MiB of key-value cache is
the price of that not happening, and 3 GB of remaining headroom is enough to pay
it.

## The VRAM policy: bounded keep-alive, explicit unload

`OLLAMA_KEEP_ALIVE` is **10 minutes**, and the model is explicitly unloaded
between working sessions with `ollama stop`. This is a policy rather than a
default and it is recorded here because the alternative is quietly expensive.

A long keep-alive holds 8.6 GB, three quarters of the card, for as long as it
lasts, including every idle stretch between benchmark batches and every hour
spent writing code that makes no inference call. What it buys is a model load,
which costs about 55 seconds from the DrvFs mount and about 20 from a warm page
cache.

**A reload costs nothing methodologically as long as the warm-up precedes the
timing**, and it always does: every latency figure in this project is taken
against a warmed session, because a cold load reported as request latency would
be reporting the disk rather than the model. So the trade is a minute of wall
clock against three quarters of a GPU, and the minute is cheaper.

The operating rule, in full:

- **During a benchmark run or a live-test session**, loaded is correct. Warm
  before timing, and never measure a cold load as a request.
- **The moment a run finishes**, and during any long stretch of work between
  calls, unload explicitly.
- **Never a keep-alive measured in hours.** Ten minutes covers the gap between
  consecutive batches of one run and expires long before the next session.
- **At the end of the phase**, verify with `ollama ps` and `nvidia-smi` that the
  card is released, and leave it released.

## Decoding parameters, and what is not being claimed

Temperature 0 and seed 20260825, both passed on every request and both recorded
in `engine_describe` and therefore in every run manifest.

**Determinism is not claimed and the report says so.** The server is free to
ignore the seed, batched GPU reductions are not order stable, and a
constrained decoder's behaviour under a schema is not specified to be
reproducible. Spec section 12.3 point 7 requires the parameters be recorded and
requires the report to say this rather than "implying reproducibility the stack
does not provide", so the sentence travels with the numbers.

## Consequences

**The comparison is against a named artefact.** The tag and the quantization are
in `engine_describe` on every run-log row and in every row of the headline table,
so a reader can see which model produced which number. A later phase that changes
the tag changes those rows and the difference is visible rather than inferred.

**The serving route is reproducible on this machine and stated as such.** It
depends on a Windows-side model store reachable at a mount point, which is a
property of this machine rather than of the project. A clean-machine reproduction
pulls the tag inside WSL2 and gets the same model at the cost of a download; the
environment variable is the only difference and `docs/environment.md` carries it.

**The 4-bit quantization is part of what is being measured.** The headline table
compares a 50-kilobyte linear model against this model at this quantization, not
against the full-precision weights, and the write-up says so. A Q4 model is not
the same classifier as its Q8 or FP16 self and reporting the comparison without
the quantization in the row would be reporting a different experiment.

**Nothing in CI depends on any of this.** Spec section 16 forbids CI from calling
a network service and from running LLM tests. The client is tested against
recorded transcripts, the live tests are skipped unless
`AUTOFILL_AUDIT_LLM_TESTS=1` **and** a reachable server agree, and the audit path
never imports the research layer.
