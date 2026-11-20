# Client Onboarding & KYC

Odoo 19 Community module for an online trading broker: traders, introducing brokers, trading accounts, KYC, deposits and withdrawals, an immutable approval log, and IB commissions.

The installable addon is [`broker_client_onboarding`](broker_client_onboarding/README.md). Put this repository on the Odoo addons path and install that module. With Docker, from this directory:

```bash
docker compose up -d
```

Open http://localhost:8069, create a database with **Demo data** ticked, then install **Broker Client Onboarding** from Apps. The click-by-click path through the sample clients is in the module README.

```bash
odoo-bin -d test_db --addons-path=/path/to/odoo/addons,/path/to/broker-client-onboarding -i broker_client_onboarding --test-enable --stop-after-init
```

Odoo 19 does not load demo data unless you pass `--with-demo`. Add that flag to install the sample clients, accounts and funding requests.
