# ShowMe

ShowMe helps workers point to an object in an approved work photo and check which rule applies. A supervisor turns photos and notes into a guide, reviews each step, and shares a published version that stays fixed when the draft changes.

[Watch the three-minute demo](https://moondh99.github.io/showme/) · [한국어 README](README.ko.md)

## Run the demo

Use Python 3.10 or later. From the repository root, run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/seed_demo.py
python scripts/serve.py
```

Open the [English demo](http://127.0.0.1:8765/demo). Use the language switch or open the [Korean demo](http://127.0.0.1:8765/demo?lang=ko). Both approval links show the staged photo, approved instruction, and completion criteria without a sign-in or API key.

To select objects and ask live questions, copy `.env.example` to `.env.local`, set `MODEL_API_KEY` to your Meta Model API key, and restart the server. The server reads the key. To create a guide, open the [author workspace](http://127.0.0.1:8765/) and use the password set in `SHOWME_AUTHOR_PASSWORD` or generated in `state/author-password.txt`.

### Try the three decisions

Choose **Select an object in the photo**, then click the center of the front white tag in the specified tray. Select the yellow tag before the second question. Send the third question independently with the same yellow tag selected.

| Selected tag | Ask | Expected decision |
| --- | --- | --- |
| Blue tray, personal storage | I completed training. Can I use this tag to borrow equipment? | **Blocked.** Storage tags cannot be used to borrow equipment. The yellow tag's issuance criteria are shown separately. |
| Yellow tray, equipment rental | I have not completed training, but my supervisor is with me. Can I issue this tag? | **Allowed.** Supervisor accompaniment satisfies one of the two alternative conditions. |
| Yellow tray, equipment rental | Can I issue this tag? | **Needs confirmation.** Confirm completed training or supervisor accompaniment. |

Read **Decision and full approved text** under each verdict to check the rule in context. Each language has its own approved version. Existing Korean approval links continue to open their original content.

## How it works

- **SAM 3.1** outlines the object the learner selects in an approved photo.
- **Muse Spark 1.3** drafts guide steps from author notes and connects learner questions to the selected object and the applicable rule. Rule questions receive a separate model review.
- **ShowMe** verifies each quote against the published instruction or completion criteria. The learner marks work complete.

## Verification

The English demo was recorded in the running app with live Meta models. The recording starts with the blocked blue tag, then shows the allowed and unresolved yellow tag cases. Captions identify shortened model waits and show the original duration. The [verification record](docs/PRODUCT_DECISIONS.md#2026-11-03--english-demo-verification) covers three questions on one [staged photo](public/demo/reception-setup/photo-sources.json).

In a small AI benchmark using two newly staged photos, ShowMe and a single-call Muse Spark baseline both returned the correct decision and cited the applicable approved rule on all four tasks. Mean processing times were 23.58 seconds for ShowMe, including SAM object selection, and 5.57 seconds for the baseline, which received the photo and approved text directly. The benchmark measured system processing time. It did not measure how long people took to find the rule.

## Tests

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -q
node --test tests/*.mjs
```
