# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

{
    'name': 'Broker Client Onboarding',
    'version': '19.0.1.0.0',
    'category': 'Finance',
    'summary': 'Client onboarding, KYC and funding controls for an online trading broker',
    'description': """
Client onboarding and KYC for an online CFD / forex broker.

A trader cannot fund a live account until compliance has approved a current
identity document and a current proof of address. Deposits and withdrawals
then follow the client's risk level: single-ticket caps, a daily withdrawal
limit, and a second approval above a threshold. Every decision is written to
an immutable approval log. Introducing brokers accrue commission on referred
deposits or on traded volume, depending on their plan.
    """,
    'author': 'Broker Client Onboarding',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'contacts'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/broker_risk_level_data.xml',
        'data/ir_cron_data.xml',
        'wizards/kyc_reject_wizard_views.xml',
        'wizards/transaction_reject_wizard_views.xml',
        'views/broker_risk_level_views.xml',
        'views/res_partner_views.xml',
        'views/broker_trading_account_views.xml',
        'views/broker_kyc_document_views.xml',
        'views/broker_transaction_views.xml',
        'views/broker_approval_log_views.xml',
        'views/broker_trade_views.xml',
        'views/broker_commission_views.xml',
        'views/menus.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
}
