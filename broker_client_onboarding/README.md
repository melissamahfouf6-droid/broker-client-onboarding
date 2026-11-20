# Client Onboarding & KYC

`broker_client_onboarding` is an Odoo 19 Community module for an online trading broker. It covers the operational path from a referred lead to a funded live account: trader and introducing-broker profiles, trading accounts, KYC documents, deposits and withdrawals, an immutable approval log, and IB commissions.

It depends only on `base`, `mail` and `contacts`. Accounting is intentionally not required; balances live on the trading account and are derived from settled money movements.

## Business flow

1. Back office opens a contact as a **trader** and assigns a **risk level**. If an introducing broker referred them, that partner is set on the trader. The risk level caps leverage and how much money can move in one request or in one day, and it decides when a second approval is required.
2. The trader is given a **demo** account (practice money, no real deposits) and, when they are ready, a **live** account. A live account cannot be activated until KYC is approved, and its leverage cannot exceed the risk level.
3. The client uploads an identity document (passport, national ID or driving licence) and a proof of address. Compliance starts the review. The person who uploaded a document cannot approve it. Rejection goes through a wizard and always stores a reason.
4. KYC is **approved** only when both a valid identity document and a valid proof of address are approved and not past their expiry date. A daily job marks approved documents past expiry as expired, which recomputes the trader's KYC status and suspends active live accounts. Funding stops until compliance accepts a replacement and back office activates the account again.
5. A deposit or withdrawal can be submitted only on an **active live** account whose owner has **approved KYC**. The request is checked against the single-transaction cap, the available balance (pending withdrawals are reserved) and the daily withdrawal limit.
6. Amounts above the risk level's second-approval threshold need two approvals. Compliance gives the first, a Finance Manager the second. The requester cannot approve their own request, and the same person cannot approve twice. Finance then marks the request done, which is what changes the account balance.
7. Every submit, review, approval, rejection, expiry, completion and cancellation is written to `broker.approval.log`. Rows are created by the business methods and cannot be edited or deleted, including by the administrator.
8. When a referred client's deposit is settled, a percent-of-deposit plan accrues an IB commission. A per-lot plan accrues when a trade is recorded on a live account. Finance confirms the batch and marks it paid.

## Roles

All four roles sit under the **Broker Operations** privilege. Each role implies the one above it.

| Role | What they do |
| --- | --- |
| Back Office User | Create traders, introducing brokers, accounts, KYC uploads and money-movement requests. Read the approval log and commission figures. |
| Compliance Officer | Review KYC and give level-1 approvals. |
| Finance Manager | Give level-2 approvals, mark requests done, and confirm or pay IB commissions. |
| Broker Administrator | Maintain risk levels and commission plans. |

## Menus

**Brokerage** contains Clients, Trading Accounts, KYC Documents, Deposits & Withdrawals and the Approval Log. Introducing Brokers, the trade blotter and IB Commissions sit together under Introducing Brokers. Risk levels and commission plans are under Configuration, visible to administrators.

## Install

Put the repository root on the Odoo addons path (the module is the `broker_client_onboarding` directory) and install **Client Onboarding & KYC**. Demo data loads three traders — one approved and funded, one still in review, one rejected — plus an introducing broker, sample accounts, a deposit that has already accrued commission, and the matching approval-log rows.

```bash
odoo-bin -d <database> --addons-path=<odoo>/addons,<this-repo> -i broker_client_onboarding --with-demo
```

Odoo 19 leaves demo data out unless `--with-demo` is set. The flag loads the three sample traders, the introducing broker, their accounts and the funding requests.

## Tests

```bash
odoo-bin -d test_db -i broker_client_onboarding --test-enable --stop-after-init
```

Add `--addons-path` the same way as for a normal install. The suite is tagged `post_install` and covers KYC status (including expiry), the funding gate, the leverage cap, single / daily / balance limits, one versus two approvals, the four-eyes rule, the immutable approval log, and commission generation.

## Licence

LGPL-3.
