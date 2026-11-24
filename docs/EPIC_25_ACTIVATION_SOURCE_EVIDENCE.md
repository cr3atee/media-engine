# EPIC 25 - Actual Subscription Conditions

Checked on 2026-11-24. Scope: the existing three monthly subscriptions,
public unauthenticated source observations and a bounded set of alternative
offers. No canonical decision, profile, price or availability was written.

**Subsequent product decision, 2026-11-24:** the user accepts the curated launch
products without exhaustive seller checks. The questions below are optional
research, not a blocker for the first version. Public price comparison can
proceed with unknown conditions, clearly labelled `price_only`; this does not
confirm the full equivalence of the source descriptions. See the current
[MVP boundary](EPIC_25_THREE_PRODUCT_MVP.md#curated-price-comparison-2026-11-24).

## Outcome

All three GGSEL launch sources and all three FunPay listing categories were
reachable. Nine known offer pages returned HTTP 200 and exposed their expected
description blocks. This proves source access and text capture, not successful
activation, seller reliability, equivalence, resale permission or net profit.

No complete comparable activation profile is established for any launch pair.
The published catalog remains the same three GGSEL offers. Playerok credentials
were not supplied or used; this run does not claim new Playerok coverage.

## Source Access

The existing GGSEL verifier returned complete category responses according to
the source's declared totals:

| Service | Returned category items | Exact monthly candidates | Retained offer | Observed RUB price |
| --- | ---: | ---: | --- | ---: |
| ExitLag | 99 | 23 | `5077855` | 599.00 |
| Duolingo | 28 | 1 | `103585387` | 50.00 |
| Spotify | 405 | 14 | `102361507` | 250.00 |

These are observations, not new persisted prices. The verifier's GGSEL selection
remains an identity-based source example, not a cheapest-offer claim.

The existing FunPay verifier returned:

| Service | Returned rows | Monthly source variants | Listing-screened review candidates | Title-duration conflicts |
| --- | ---: | ---: | ---: | ---: |
| ExitLag | 2000 | 656 | 458 | 19 |
| Duolingo | 330 | 29 | 0 | 6 |
| Spotify | 1526 | 312 | 0 | 7 |

FunPay's returned rows are not proven marketplace-wide coverage. Screening
rejects missing launch plan/method evidence; zero review candidates does not
mean zero monthly offers. The loaded month field is still used, not a guessed
title duration. Additional detail sampling selected at most two monthly offers
per Duolingo/Spotify source with the existing `BestOfferSelector` in explicit
price-discovery mode; no new price-ranking algorithm or comparison was added.
Those sampled prices are not guaranteed current/global minima.

## GGSEL Launch Facts

### ExitLag: 5077855

[Source page](https://ggsel.net/en/catalog/product/podpiska-exitlag-30-dnei-kliuc-rossiia-157-stran-5077855).

- Seller: Профессионал™. Source title specifies 30 days; preserve `P30D`, not an
  assumed `P1M` just because the reviewed canonical name contains one month.
- The description offers a key/pin or set of keys for redemption in an ExitLag
  account and enumerates eligible countries, including Russia. It does not
  establish worldwide eligibility. Country-list spelling/translation ambiguities
  must not be silently expanded into a larger valid scope.
- Device entitlement, exact plan, prior subscription/trial eligibility, active
  subscription restrictions, VPN and key-use deadline are not established by
  the captured description. No mention of a deadline does not mean unlimited.

### Duolingo: 103585387

[Source page](https://ggsel.net/en/catalog/product/kliuc-duolingo-super-1-mesiac-momentalnaia-avto-vydaca-103585387).

- Seller: Reseller Hub. The source describes a one-month Super activation
  key/promo code, immediate digital delivery and self-redemption in the buyer's
  account without handing the seller a password. It explicitly advertises all
  countries. These remain seller claims, not a tested entitlement.
- A personal account is not sufficient evidence of Individual versus a Family
  seat. Neither paid-versus-promotional eligibility nor prior-trial/current-Super
  restrictions are settled. Device coverage, VPN and expiry are unknown.
- The 30-day warranty is not a verified 30-day subscription period or key expiry.

### Spotify: 102361507

[Source page](https://ggsel.net/en/catalog/product/premium-podpiska-dlia-individualnyx-polzovatelei-na-1-mesiac-v-spotify-10-legalno-102361507).

- Seller: ZGSTopUp. Title: one-month Premium Individual. The actual description
  requests account credentials and provides account activation with an Egypt
  subscription region; this is not evidence of a transferable activation key.
- It advertises support for old/new accounts and separately offers account
  creation. Those are distinct fulfillment choices, not a single interchangeable
  delivery profile. MediaEngine does not collect those credentials or order it.
- Its stated short fulfillment time is not a key activation deadline. Device
  coverage, activation/use VPN requirements, active-subscription restrictions
  and prior region-enforcement history are not fully specified. Egypt account
  region is not proof that every customer country can activate/use it equally.

## FunPay Detail Samples

| Service / offer | Observation | Why it is not yet an equivalent sourcing offer |
| --- | --- | --- |
| ExitLag [82792757](https://funpay.com/lots/offer?id=82792757) | 208.96 RUB in the listing response; PC, code, monthly filter | New-account claims, VPN, one-hour code use, country and subnational exclusions, plus device/IP-history rules. Description also contains contradictory account wording. No normalization can resolve this safely. |
| ExitLag [19847269](https://funpay.com/lots/offer?id=19847269) | Existing historical proposal; PC, code, monthly filter | Description forbids an active subscription and provides a mixed-language country list. VPN, deadline and precise duration remain unsettled. It is not today's verified cheapest offer; its old persisted price was not refreshed. |
| Duolingo [82765333](https://funpay.com/lots/offer?id=82765333) | 18.25 RUB; Super Individual, monthly filter, account-access activation | This is explicitly trial activation with eligibility depending on the account; an active Super subscription is excluded. It is not the launch source's advertised key fulfillment. |
| Duolingo [81387965](https://funpay.com/lots/offer?id=81387965) | 28.51 RUB; Super Family, monthly filter, no account access | Description supplies a gift link, not an account or proven key, with no warranty. Family entitlement differs and the title names December. Validity and exact benefit period need confirmation. |
| Spotify [21964871](https://funpay.com/lots/offer?id=21964871) | 164.44 RUB; Individual, monthly filter | Seller enters the account via an emailed code, changes region to Egypt and excludes active subscriptions. Ongoing use may require Egypt VPN/proxy; this is not an unconditional equivalent. |
| Spotify [48132628](https://funpay.com/lots/offer?id=48132628) | 164.46 RUB; Individual, monthly filter | Account access, Egypt region, no active subscription and possible VPN during use. Prior cancellation for region mismatch is an additional exclusion; optional account creation is a different service. |

The existing ExitLag proposal was not replaced by the cheap sample and neither
new Duolingo nor Spotify sample was staged, linked or published. Numeric price
spread is deliberately not presented as savings/profit.

## Actual Contract Limits

The current `ActivationConditions` supports country sets, device, plan, exact
period, delivery, new/existing account, activation VPN and a code-use window.
The following observed restrictions are not fully represented:

- Whether an active subscription is forbidden, and whether prior paid/trial
  usage or promotional eligibility matters. Existing/new account age alone does
  not encode those facts.
- IP/device history, previous region-enforcement cancellation and subnational
  restrictions. Do not invent ISO country codes or drop these clauses.
- Subscription/account region versus customer location, and VPN needed during
  ongoing use versus specifically during activation.
- Gift-link fulfillment: the current key/own-account/new-account choices do not
  make an unauthenticated gift link a key or a seller account-access service.

Therefore do not enter an approximately complete profile in the existing form
and place these extra restrictions only in a reason: the comparator does not
interpret free-text reasons. Keep the profile unknown rather than claiming
verified equivalence. The later user-approved price-only public mode can rank
the curated offers with a notice; strict equivalence still requires complete
facts without losing source restrictions.
This report does not extend the model or silently change matching semantics.

## Precise Seller Questions

These are optional, not mandatory release questions. Only sellers can resolve
their remaining commercial claims. No purchase, account
password, session cookie or activation code is needed for these questions.

Ready-to-forward questions in Russian (the public country lists are already
captured; do not ask the user to transcribe them):

**ExitLag, GGSEL 5077855**

> Здравствуйте! Уточните, пожалуйста, условия товара 5077855: какой именно
> тариф и для каких устройств, срок ровно 30 дней или календарный месяц?
> Подходит ли старый аккаунт, если раньше был пробный период или платная
> подписка, и можно ли активировать при действующей подписке? Нужен ли VPN
> при активации или дальнейшем использовании? Сколько времени после покупки
> действителен неиспользованный ключ? Разрешаете ли хранить и перепродавать
> неактивированные ключи другим покупателям?

**Duolingo, GGSEL 103585387**

> Здравствуйте! По товару 103585387: это индивидуальная подписка Super или
> место в семейной? Обычный оплаченный месяц, пробный период или промокод
> с условиями участия? Подойдёт ли аккаунт, где уже был пробный Super или
> сейчас есть подписка? На каких устройствах действует, нужен ли VPN?
> Есть ли срок активации после выдачи кода? Разрешена ли передача и
> перепродажа неиспользованного кода другому покупателю?

**Spotify, GGSEL 102361507**

> Здравствуйте! По товару 102361507: подходит ли аккаунт с действующей
> подпиской, с прошлой подпиской или с прежней отменой из-за региона?
> В каких странах может находиться покупатель при регионе подписки Египет?
> Нужен ли VPN только при активации или при дальнейшем использовании?
> Обязателен ли ваш вход в аккаунт покупателя? Допускаете ли оформление
> подписок для моих покупателей при перепродаже услуги? Сейчас интересует
> активация на существующем аккаунте, без создания нового.

MediaEngine must not receive buyer passwords, one-time login codes or cookies
while collecting these answers. A seller's answer is evidence to review, not
certification that the subscription provider permits resale or region changes.

Do not expand the first version into an exhaustive seller questionnaire or
larger assortment. Verified-equivalence work can continue later; the curated
price-only view does not need to wait for these answers.

## Reproducible Evidence Capture

`scripts/collect_epic25_activation_evidence.py` is a read-only research tool,
not a parser/pipeline implementation. It uses existing `HttpClient`,
`GGSelFetcher` and `FunPayFetcher`, and Python's standard HTML parser. It captures
only observed product title/description/parameter blocks, never reviews,
embedded scripts, checkout/payment forms or authenticated account data.

```powershell
$env:EPIC25_ACTIVATION_EVIDENCE_LIVE = 'I_UNDERSTAND_THIS_READS_PUBLIC_OFFER_PAGES'
.\.venv\Scripts\python.exe scripts/collect_epic25_activation_evidence.py
```

The fixed nine known URLs are not an arbitrary URL input or a claim of full
coverage. Output goes to a new OS temporary directory, outside Git and `tmp/`.
It contains source URL/ID, UTC observation time, HTTP status, uninterpreted text,
SHA-256 of decoded HTML and normalized captured sections. FunPay also records
the fetcher's observed URL. The successful capture window was approximately
`2026-11-24 05:28:18-05:28:33 UTC`. The artifact can be used for local review;
it is not permanent application evidence or a substitute for current source
verification. Full seller descriptions are deliberately not committed here.

Unknown markup, duplicate/missing description blocks and request failures are
reported, not converted into successful empty offers. Partial results remain
diagnostic artifacts and return nonzero. Missing opt-in also returns nonzero,
before opening a network client. No database/repository or approval service is
imported by the collector and no domain profile is constructed.

## Verification

- Existing live GGSEL verifier: `3/3` source examples, source URLs HTTP 200.
- Existing live FunPay verifier: `3/3` source access; comparability remains
  blocked as described above, not falsely marked passed.
- New bounded collector: `9/9` page captures, no successful activation or
  canonical-equivalence test claimed.
- Focused offline tests: `12 passed`, including scoped extraction, malformed or
  ambiguous responses, explicit live guard, partial failure, safe diagnostics
  and temporary artifact output. Fixtures are synthetic and do not query sites.
- Strict MyPy: `577` source files. Changed-file Ruff and Ruff format pass.
- Full Pytest: `903 passed, 65 skipped`; the existing guarded skips and
  Starlette/httpx deprecation warning remain unchanged.
- No application code, dependencies, schema, UI, scheduler, source refresh,
  catalog promotion or Telegram/AI integration changed. Earlier PostgreSQL and
  browser results are not represented as newly rerun by this research step.
