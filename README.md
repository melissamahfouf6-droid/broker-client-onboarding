# Client Onboarding & KYC

Odoo 19 Community module for an online trading broker: traders, introducing brokers, trading accounts, KYC, deposits and withdrawals, an immutable approval log, and IB commissions.

The installable addon is [`broker_client_onboarding`](broker_client_onboarding/README.md). Put this repository on the Odoo addons path and install that module.

```bash
odoo-bin -d test_db --addons-path=<odoo>/addons,<this-repo> -i broker_client_onboarding --test-enable --stop-after-init
```

Odoo 19 does not load demo data unless you pass `--with-demo`. Add that flag to install the sample clients, accounts and funding requests.
