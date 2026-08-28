# Launch pack

Everything that has to be typed into X by hand. Nothing here posts itself.

## Profile

**Display name** (50 char limit)

    Days Since The Last Major AI Lab F**kup

**Handle** — staying `@xRiskMemes` (decided 2026-08-28). The sign's small
handle text follows the `COUNTER_HANDLE` repo variable, already set to match.

**Bio** (160 char limit)

    One number, once a day: days since the last major AI lab f**kup. Resets when a frontier lab has to apologise. Rules in the pinned post. Run by @Actuallykeltan.

**Avatar** `out/avatar.png` (400x400) · **Header** `out/header.png` (1500x500)
Regenerate either with `python profile_assets.py`.

## Pinned rules thread

Five posts, all under 280 characters, none containing a URL — a post with a
link costs $0.20 against the pay-per-use API instead of $0.015, and the thread
has no link worth paying for while the repo is private.

That's also why the rubric is spelled out here rather than linked. If the repo
ever goes public, post 5 is the place to add the link, and the bio line
"Rules in the pinned post" can become the repo URL.

Post it as a self-thread, then pin post 1.

---

**1/5**

```
This account posts one number a day: how many days since a major AI lab did something it had to apologise for.

It resets more often than you would like.

The rules are in this thread. They are the same for every lab.
```

**2/5**

```
The counter resets when a frontier lab - OpenAI, Anthropic, Google DeepMind, Meta, xAI, Microsoft, DeepSeek, Mistral, Amazon, Alibaba - is answerable for:

harmful model behaviour at scale
exposed user data
a governance or safety-team collapse
deception
large-scale misuse
```

**3/5**

```
What does not reset it:

Lawsuits. At any stage - filed, settled, decided. This tracks what labs did, not what they were sued for.

Companies that don't train frontier models.

Capability announcements.

Anything without a primary source.
```

**4/5**

```
Every entry has a primary source before it posts. The date is when it became public, not when it happened.

Smaller things get logged as replies without resetting the counter.

When an incident involves a death or a child, the joke comes off: no sign, no swear, no record line.
```

**5/5**

```
Run by @Actuallykeltan. Personal project, mine alone.

If I have got something wrong, reply with a source. I will correct it and say that I did.

If I have missed something, same.
```

---

## Still outstanding

- X Developer Console → Billing → Credits → set a spending limit. Not set. A
  loop in the poster could otherwise run up the card.
- Verify the `low` and `medium` confidence entries in `incidents.yaml` before
  one of them ends up on a screenshot.
