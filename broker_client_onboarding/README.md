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

## Demo walkthrough

Demo data only loads on a database created with demo data. With Docker, from this repository:

```bash
docker compose up -d
```

Open http://localhost:8069, create the database with **Demo data** ticked, and install **Broker Client Onboarding** from Apps.

From a local Odoo 19 install, put this repository on the addons path and run:

```bash
odoo-bin -d brokerage --addons-path=/path/to/odoo/addons,/path/to/broker-client-onboarding -i broker_client_onboarding --with-demo
```

Then follow the same path a broker does. Every screen is already filled in.

1. **Brokerage → Clients.** Amina El-Sayed is approved, Jonas Meier is in review, and Chloe Martin was rejected. On Amina's form, the badge shows her KYC status, and the smart buttons open her accounts, documents and transactions.
2. **Brokerage → Trading Accounts.** Amina's live account `CFI-000001` is active with a balance of 8,000. Her demo account is active and stays at zero. Jonas's live account is still in draft.
3. **Brokerage → KYC Documents.** The kanban is grouped by state. Amina's passport and proof of address are approved. Jonas has one document under review and one submitted. Chloe's national ID is rejected, with the reason on the form.
4. **Brokerage → Deposits & Withdrawals.** Amina's 8,000 bank deposit is done. Her 12,000 card deposit is waiting: it is above the Low risk threshold of 10,000, so it needs Compliance and then Finance. Her 500 withdrawal is still in draft.
5. **Brokerage → Approval Log.** This is the audit trail: Amina's two KYC approvals, the submit, level-1 approval and completion of the 8,000 deposit, and Chloe's rejection. The 12,000 deposit was loaded already waiting for approval, so it has no log row yet. Rows cannot be edited or deleted.
6. **Brokerage → Introducing Brokers → IB Commissions.** Horizon Bridge Ltd earned 640 on Amina's settled deposit (8% of 8,000). It is still pending.

### Try the controls yourself

- **KYC gate.** Open Jonas's draft live account and press **Activate**. Odoo refuses until he has an approved, in-date identity document and proof of address.
- **Four-eyes rule.** Open the 12,000 deposit and press **Approve** while logged in as Administrator. That user is the one who submitted it, so Odoo refuses. A different Compliance Officer has to give the first approval, then a Finance Manager the second.
- **Limits.** Submit Amina's 500 withdrawal. It is inside the balance, so it moves to To Approve. Create a second withdrawal for 9,000 on the same account and submit that. Odoo refuses: the 500 is already reserved, and 9,000 is more than the remainder. The amount on a submitted request stays locked.

## Licence

LGPL-3.
